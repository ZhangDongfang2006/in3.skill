# -*- coding: utf-8 -*-
"""主数据巡检 · rule#1 单价异常检测器（信号 C 命门 + Q/P co-primary + 评分 → shortlist + HTML）。

数据走 in3_client（AGENT client_credentials 机器令牌，无人值守）。凭证从环境变量读，**不进代码**：
  IN3_AGENT_CLIENT_ID / IN3_AGENT_CLIENT_SECRET （必填）
  IN3_API_HOST（默认 prod）/ IN3_TENANT_DOMAIN（默认 indx）

跑法：先 export 两个 AGENT 变量，再 `python3 mdm_sentinel.py [out.html]`。
信号权重经田野《疑似PCS包装单位异常物料分析结果.xlsx》3580 行校准，见 CONTEXT.md。
"""
import html as _html
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from pack_spec import extract_pack_spec  # noqa: E402
import in3_client  # noqa: E402

PACK_RATIO_TOL = 0.15  # 价差倍数 ≈ 包装规格 的相对容差（确诊"包装单位错配"）


def _retry(fn, tries=6, base=2.0):
    """瞬时 5xx/网络抖动重试（指数退避）。后端实测偶发 503。"""
    import time
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            msg, tn = str(e), type(e).__name__
            transient = (any(c in msg for c in ("503", "502", "504", "500", "SSL", "EOF", "Max retries", "Connection", "timed out"))
                         or any(t in tn for t in ("Timeout", "SSL", "Connection")))
            last = e
            if not transient or i == tries - 1:
                raise
            print(f"  ⚠ 瞬时错误重试 {i + 1}/{tries - 1}（{tn}: {msg[:50]}）")
            time.sleep(base * (i + 1))
    raise last


def get_in3():
    """数据源认证。优先用现有 workspace 登录用户（password grant，PO+价格全可读、信号 Q 可用）；
    仅当显式给了 AGENT client_credentials 时才走机器令牌（无人值守，但当前 AGENT 无 PO 读权限→Q 降级）。

    实测：indx 用户令牌 info-record 价格 50/50 非空、PO 200——`has_privilege:False` 只挡 UI 导出、不挡 API。
    """
    cid = os.environ.get("IN3_AGENT_CLIENT_ID")
    csec = os.environ.get("IN3_AGENT_CLIENT_SECRET")
    if cid and csec:
        return in3_client.IN3.from_client_credentials(
            api_host=os.environ.get("IN3_API_HOST", "https://apiv3.industics.com/service"),
            tenant_domain=os.environ.get("IN3_TENANT_DOMAIN", "indx"),
            client_id=cid, client_secret=csec,
        )
    return in3_client.IN3()  # 当前租户登录用户


def _qty_field(line: dict):
    """PO 行项的数量字段名各租户可能不同，动态探。"""
    for k in ("quantity", "order_quantity", "purchase_quantity", "qty", "demand_quantity", "num"):
        if k in line and isinstance(line[k], (int, float)):
            return k
    for k in line:
        if ("quant" in k.lower() or k.lower().endswith("_qty") or k.lower() == "qty") and isinstance(line[k], (int, float)):
            return k
    return None


def _effective_prices(recs, today):
    """每供应商取其「最近新建（created_date 最新）且当前有效」的记录 = 该供应商当前价。

    - 同供应商被更新的旧记录不算（如某供应商 6-22 建了改正价 0.0568，则其旧 14.2 排除）；
    - 某供应商一直没改、当前价仍按包错录的，仍作为它的当前价被算进来（不漏未改的供应商）。
    返回 [{supplier, price, valid_from, valid_to, created, created_by}]，按 price 升序。
    """
    bysup = defaultdict(list)
    for r in recs:
        p = r.get("unit_price")
        if not isinstance(p, (int, float)) or p <= 0:
            continue
        vf, vt = (r.get("price_valid_from") or ""), (r.get("price_valid_to") or "")
        if vf and vf > today:      # 尚未生效
            continue
        if vt and vt < today:      # 已失效
            continue
        key = r.get("created_date") or vf or ""   # "最近新建" 按 created_date
        bysup[r.get("supplier_id")].append((key, p, r))
    eff = []
    for sup, lst in bysup.items():
        lst.sort(key=lambda x: x[0])              # 最近新建在末尾
        _, p, r = lst[-1]
        eff.append({"supplier": sup, "price": p,
                    "valid_from": r.get("price_valid_from"), "valid_to": r.get("price_valid_to"),
                    "created": r.get("created_date"), "created_by": r.get("created_by_name")})
    eff.sort(key=lambda e: e["price"])
    return eff


def build_candidates(in3, irs=None):
    """拉 info-record → 按物料聚合 → PCS 门槛 + C(包装) + P(**每供应商最新有效记录**跨供应商比) 选候选。

    irs 可传入已拉好的 info-record 列表（多规则共享一次拉取，免重复打 8564 条）。
    """
    if irs is None:
        irs = _retry(lambda: in3.mm.info_record.list(size=100, all=True).items)
    today = datetime.now().strftime("%Y-%m-%d")
    by_mat = defaultdict(list)
    for r in irs:
        by_mat[r.get("material_id")].append(r)

    cands = []
    for mid, recs in by_mat.items():
        if not mid:
            continue
        r0 = recs[0]
        unit = (r0.get("material_unit") or "").strip().upper()
        if unit != "PCS":  # R001 门槛
            continue
        name, desc = r0.get("material_name"), r0.get("material_desc")
        pack = extract_pack_spec(name, desc)

        eff = _effective_prices(recs, today)  # ★ 每供应商最新有效记录
        if not eff:
            continue
        pmin = eff[0]["price"]            # 现价最低供应商（≈ 已改对的 per-PCS）
        pmax = eff[-1]["price"]           # 现价最高供应商
        ratio = (pmax / pmin) if pmin > 0 else None
        susp = eff[-1]                    # 要改的就是这家现价最高、疑按包错录的

        sig_c = bool(pack and pack.get("qty"))
        sig_p = bool(ratio and ratio >= 3)
        if not (sig_c or sig_p):
            continue
        cands.append({
            "material_id": mid, "material_no": r0.get("material_no"), "name": name, "desc": desc,
            "pack": pack, "price_min": pmin, "price_max": pmax, "ratio": ratio,
            "n_record": len(recs), "n_effective": len(eff),
            "susp_supplier": susp["supplier"], "susp_valid_from": susp["valid_from"],
            "susp_valid_to": susp["valid_to"], "susp_created": susp["created"], "susp_created_by": susp["created_by"],
            "q_max": None, "q_round_ratio": None, "q_divisible": False,
        })
    return cands


def add_quantity_signal(in3, cands):
    """对候选拉 PO 行项 → 信号 Q（大额 / 整百整千 / 可被包装规格整除）。

    返回 True=Q 数据可用；False=PO 端点无权限（401）等 → 降级，仅用 C+P 评分。
    """
    # Q（整除判断）只对有包装规格的候选有意义；也大幅减少 PO 拉取量（抗网络抖动）。
    cand_for_q = [c for c in cands if (c["pack"] or {}).get("qty")]
    mids = [c["material_id"] for c in cand_for_q]
    if not mids:
        return False
    print(f"  （Q 仅对 {len(mids)} 个有包装规格的候选拉 PO）")
    try:
        pos = _retry(lambda: in3.mm.purchase_order.list(filter={"material_ids": mids}, include_items=True, all=True).items)
    except Exception as e:
        print(f"  ⚠ PO 拉取失败（{type(e).__name__}: {str(e)[:80]}）→ 降级，仅用 C+P 信号评分")
        return False
    qty_by_mat = defaultdict(list)
    qf = None
    for po in pos:
        for it in (po.get("items") or []):
            if qf is None:
                qf = _qty_field(it)
            mid = it.get("material_id") or it.get("material", {}).get("material_id") if isinstance(it.get("material"), dict) else it.get("material_id")
            q = it.get(qf) if qf else None
            if mid and isinstance(q, (int, float)):
                qty_by_mat[str(mid)].append(float(q))
    for c in cands:
        qs = qty_by_mat.get(str(c["material_id"]), [])
        if not qs:
            continue
        c["q_max"] = max(qs)
        c["q_round_ratio"] = sum(1 for q in qs if q >= 100 and (q % 100 == 0 or q % 1000 == 0)) / len(qs)
        pq = c["pack"].get("qty") if c["pack"] else None
        if pq:
            c["q_divisible"] = any(q >= pq and q % pq == 0 for q in qs)
    return True


def score(c):
    """规则化分级（C 命门 + Q/P co-primary）。返回 (分值, 等级, 根因, 核验要点)。

    分级按"最强信号"判，不靠单一加总阈值——避免"有包装规格但价差=1"这种被误升。
    score 仅作组内排序用。
    """
    pack, ratio, pq = c["pack"], c["ratio"], (c["pack"] or {}).get("qty")
    pmin, pmax = c["price_min"], c["price_max"]
    gold = bool(pq and ratio and abs(ratio - pq) / pq <= PACK_RATIO_TOL)  # 价差≈包装规格=确诊

    # 评分（仅排序）
    s = 10
    s += 20 if pq else (8 if pack else 0)
    if ratio:
        s += 20 if ratio >= 1000 else 16 if ratio >= 100 else 12 if ratio >= 10 else 6 if ratio >= 5 else 3 if ratio >= 3 else 0
    if gold:
        s += 15
    if c["q_max"]:
        s += 12 if c["q_max"] >= 50000 else 10 if c["q_max"] >= 10000 else 8 if c["q_max"] >= 7500 else 0
    if c["q_divisible"]:
        s += 10

    # 规则化分级按「当前有效价」的最强信号。Q（采购量整除）只作佐证/排序，不单独定级——
    # 否则"高价已失效、当前定价已正常、只是大批量下单"的料会被误升回高危（验证实测的坑）。
    if gold or (pq and ratio and ratio >= 10):
        tier = "高度疑似"
    elif (ratio and ratio >= 10) or (pq and ratio and ratio >= 3):
        tier = "中度疑似"
    else:
        tier = "观察"

    # 当前价记录（最近新建的有效记录）定位串，Sourcing 据此知道改哪条
    sup = str(c.get("susp_supplier") or "")[:8]
    vfrom, vto = c.get("susp_valid_from"), c.get("susp_valid_to")
    cby, cdt = c.get("susp_created_by") or "", c.get("susp_created")
    vstr = f"【当前价·供应商{sup}·{cdt}建{('('+cby+')') if cby else ''}·有效{vfrom}~{vto}】" if vfrom else ""

    # 根因 + 核验要点（确定性，从信号直接生成，给 Sourcing 可落地的动作）
    if gold:
        cause = f"包装单位错配（该供应商现价≈包装规格{pq}×）"
        corr = (pmax / pq) if pq else None
        note = (f"供应商现价{pmax:.4f}{vstr}疑为整包价(÷{pq}={corr:.4f})；"
                f"同料已有供应商现价低至{pmin:.4f}(正确 PCS)。把该记录改为 PCS 单价。")
    elif ratio and ratio >= 10:
        cause = f"该供应商现价异常偏高（{ratio:.0f}倍最低现价）"
        note = (f"该供应商现价{pmax:.4f}{vstr}是同料最低现价{pmin:.4f}的{ratio:.0f}×。"
                + (f"包装规格{pq}，核对该记录是否按包/按盒录入。" if pq else "核对该记录报价单位口径或录入错误。"))
    elif c["q_divisible"] and pq:
        cause = f"采购量整除包装规格{pq}（数量疑似按包计）"
        note = f"采购数量可被{pq}整除、最大{c['q_max']}，疑似按包数下单。核对计划单位与下单单位是否一致。"
    elif pq:
        cause = "有明确包装规格、单PCS定价存疑"
        note = f"描述含包装规格{pq}、单位 PCS。价差不显著，低优先级，抽检价格记录单位口径即可。"
    else:
        cause = f"价格离散（{ratio:.0f}倍）" if ratio else "单价合理性存疑"
        note = f"同料价差{ratio:.0f}×，核对供应商报价单位。" if ratio else "信号弱，观察。"
    if c["q_divisible"] and pq and tier != "观察":
        note += f" 佐证：采购量(最大{c['q_max']:.0f})可被包装规格{pq}整除，疑按包数下单。"
    return s, tier, cause, note


def render_html(rows, n_total, out):
    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    hi = sum(1 for r in rows if r["tier"] == "高度疑似")
    md = sum(1 for r in rows if r["tier"] == "中度疑似")
    css = """body{font-family:-apple-system,'PingFang SC',sans-serif;margin:0;background:#f5f7fa;color:#1f2937}
.hero{background:linear-gradient(135deg,#1e3a8a,#2563eb);color:#fff;padding:28px 36px}
.hero h1{margin:0;font-size:22px}.hero p{margin:6px 0 0;opacity:.85;font-size:13px}
.kpis{display:flex;gap:16px;padding:20px 36px}.kpi{background:#fff;border-radius:10px;padding:16px 22px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
.kpi .n{font-size:26px;font-weight:700}.kpi.hi .n{color:#dc2626}.kpi.md .n{color:#f59e0b}.kpi .l{font-size:12px;color:#6b7280}
table{width:calc(100% - 72px);margin:8px 36px 36px;border-collapse:collapse;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.08)}
th,td{padding:9px 12px;text-align:left;font-size:12.5px;border-bottom:1px solid #f0f0f0}
th{background:#f8fafc;color:#475569;font-weight:600}
.t-hi{color:#dc2626;font-weight:700}.t-md{color:#f59e0b;font-weight:600}
.badge{display:inline-block;padding:1px 7px;border-radius:10px;font-size:11px;background:#fef2f2;color:#dc2626}
.cause{color:#b91c1c;font-size:11.5px}.num{font-variant-numeric:tabular-nums;text-align:right}"""
    head = "<tr><th>#</th><th>等级</th><th>物料编号</th><th>物料名称</th><th>包装</th><th>价差</th><th>价格区间(未税)</th><th>根因 / 核验要点（建议动作）</th></tr>"
    trs = []
    for i, r in enumerate(rows, 1):
        tc = "t-hi" if r["tier"] == "高度疑似" else "t-md" if r["tier"] == "中度疑似" else ""
        pk = (r["pack"] or {}).get("qty") or (r["pack"] or {}).get("container") or "—"
        rt = f'{r["ratio"]:.0f}×' if r["ratio"] else "—"
        pr = f'{r["price_min"]:.4f}~{r["price_max"]:.4f}' if r["price_min"] is not None else "—"
        trs.append(
            f'<tr><td>{i}</td><td class="{tc}">{r["tier"]}</td>'
            f'<td>{_html.escape(str(r["material_no"]))}</td><td>{_html.escape(str(r["name"] or "")[:22])}</td>'
            f'<td class="num">{pk}</td><td class="num">{rt}</td><td class="num">{pr}</td>'
            f'<td><b class="cause">{_html.escape(r["cause"])}</b><br><span style="color:#374151">{_html.escape(r.get("note") or "")}</span></td></tr>'
        )
    htmldoc = f"""<!doctype html><html lang=zh><head><meta charset=utf-8><title>主数据巡检·单价异常</title><style>{css}</style></head><body>
<div class=hero><h1>主数据巡检 · 采购单价异常</h1><p>tenant=indx · 巡检时间 {now} · 扫描 PCS 单位物料 {n_total} · 命中 {len(rows)}（信号 C 包装规格 + Q 数量模式 + P 价格离散，rule#1）</p></div>
<div class=kpis><div class="kpi hi"><div class=n>{hi}</div><div class=l>高度疑似</div></div><div class="kpi md"><div class=n>{md}</div><div class=l>中度疑似</div></div><div class=kpi><div class=n>{len(rows)}</div><div class=l>待 Sourcing 核验</div></div></div>
<table><thead>{head}</thead><tbody>{''.join(trs)}</tbody></table>
<p style="margin:0 36px 30px;color:#9ca3af;font-size:11px">确定性脚本算 → AI 判读 shortlist（见 ADR-0001）。本报告为只读快照，Sourcing 人工核验后统一更新价格记录单位。</p>
</body></html>"""
    with open(out, "w", encoding="utf-8") as f:
        f.write(htmldoc)


def main():
    import json
    out = sys.argv[1] if len(sys.argv) > 1 else "mdm_sentinel_report.html"
    cache = os.environ.get("MDM_CACHE")  # 设了路径=候选缓存：存在则复用(免重拉)，否则拉完写入
    if cache and os.path.exists(cache):
        cands = json.load(open(cache, encoding="utf-8"))
        print(f"复用候选缓存 {cache}（{len(cands)} 条），跳过拉数")
    else:
        in3 = get_in3()
        print("拉 info-record 建候选…")
        cands = build_candidates(in3)
        print(f"  PCS 物料中命中 C/P 信号的候选: {len(cands)}")
        print("对候选拉 PO 算数量信号 Q…")
        q_ok = add_quantity_signal(in3, cands)
        if not q_ok:
            print("  （本次 Q 信号不可用，评分仅基于 C 包装规格 + P 价格离散）")
        if cache:
            json.dump(cands, open(cache, "w", encoding="utf-8"), ensure_ascii=False)
            print(f"  候选已缓存 → {cache}")
    for c in cands:
        c["score"], c["tier"], c["cause"], c["note"] = score(c)
    cands.sort(key=lambda c: -c["score"])
    n_total = len(cands)
    shortlist = [c for c in cands if c["tier"] != "观察"]
    render_html(shortlist, n_total, out)

    import json
    jf = os.path.splitext(out)[0] + "_shortlist.json"
    with open(jf, "w", encoding="utf-8") as f:
        json.dump([{k: c.get(k) for k in ("material_no", "name", "desc", "pack", "price_min",
                    "price_max", "ratio", "n_effective", "susp_supplier", "susp_created",
                    "susp_created_by", "susp_valid_from", "susp_valid_to", "score", "tier", "cause", "note")}
                   for c in shortlist], f, ensure_ascii=False, indent=1)
    print(f"  shortlist JSON（喂 AI 判读层）: {jf}")

    print(f"\n=== shortlist（高/中度疑似 {len(shortlist)}）===")
    for i, c in enumerate(shortlist[:25], 1):
        rt = f'{c["ratio"]:.0f}×' if c["ratio"] else "—"
        print(f'{i:>2} [{c["tier"]}] 分{c["score"]:>3} {c["material_no"]:<10} 包装={(c["pack"] or {}).get("qty")} 价差={rt} Qmax={c["q_max"]}  {c["cause"]}')
    # 验证锚点：扎带 EL00556
    z = [c for c in cands if c["material_no"] == "EL00556"]
    if z:
        c = z[0]
        print(f'\n[验证] 扎带 EL00556 → 分{c["score"]} {c["tier"]}（田野给 28/观察）｜{c["cause"]}')
    print(f"\nHTML 报告: {out}")


if __name__ == "__main__":
    main()
