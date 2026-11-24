# -*- coding: utf-8 -*-
"""主数据巡检框架编排器：一次拉 info-record，跑多条规则，合并成一份多规则报告。

规则：
  R1 单价异常（包装单位错配）—— 复用 mdm_sentinel（C 包装 + P 现价离散 + Q 数量佐证）
  R2 价格记录 vs 实际 PO 成交价偏离 —— 现价与近 N 月 PO 实付偏离 ≥ 阈值（价格记录过时/错）
  R5a 无当前有效价格 —— 有价格记录但当前一条有效的都没有（全失效/未生效）
  R5b 有采购无价格记录 —— 在 PO 里出现但没有任何 info-record（交易了却没维护现价）
  R7 独家供应 —— 当前仅 1 家供应商有现价

凭证默认走用户登录（同 mdm_sentinel.get_in3）。跑法：python3 mdm_inspect.py [out.html]
"""
import html as _html
import json
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mdm_sentinel as S  # noqa: E402

DIVERGE_RATIO = 3.0   # R2 现价 vs 成交价 偏离阈值
PO_MONTHS = 12        # R2 取近 N 月 PO


def material_index(irs):
    """info-record 按物料聚合（含每供应商现价 effective），覆盖所有 PCS 物料。"""
    today = datetime.now().strftime("%Y-%m-%d")
    by_mat = defaultdict(list)
    for r in irs:
        by_mat[r.get("material_id")].append(r)
    idx = {}
    for mid, recs in by_mat.items():
        if not mid:
            continue
        r0 = recs[0]
        unit = (r0.get("material_unit") or "").strip().upper()
        eff = S._effective_prices(recs, today)
        idx[mid] = {
            "mid": mid, "material_no": r0.get("material_no"), "name": r0.get("material_name"),
            "unit": unit, "category": r0.get("material_category"),
            "n_records": len(recs), "eff": eff, "n_cur_sup": len(eff),
            "cur_min": eff[0]["price"] if eff else None,
            "cur_med": statistics.median([e["price"] for e in eff]) if eff else None,
        }
    return idx


def rule_sole_source(idx, spend, top=40):
    """R7 独家供应。**按近 12 月采购金额收口**——独家 + 买得多才是真风险（否则几千条噪音）。
    无 PO 金额数据时退回"独家 + 有现价"，但仍 cap，并提示未按金额排序。"""
    sole = [a for a in idx.values() if a["unit"] == "PCS" and a["eff"] and a["n_cur_sup"] == 1]
    if spend:
        sole = [a for a in sole if spend.get(str(a.get("mid")), 0) > 0]
        sole.sort(key=lambda a: -spend.get(str(a.get("mid")), 0))
    out = []
    for a in sole[:top]:
        sp = spend.get(str(a.get("mid")), 0) if spend else 0
        spstr = f"近12月采购 {sp:,.0f} 元，" if sp else ""
        out.append({"rule": "R7 独家供应", "material_no": a["material_no"], "name": a["name"],
                    "tier": "提示", "detail": f"现价 {a['cur_min']:.4f}",
                    "note": f"{spstr}当前仅 1 家供应商有现价（{a['cur_min']:.4f}），独家供应风险，建议开发备选源。"})
    return out, len(sole)


def rule_no_current_price(idx):
    out = []
    for a in idx.values():
        if a["unit"] == "PCS" and a["n_records"] > 0 and not a["eff"]:
            out.append({"rule": "R5a 无当前有效价格", "material_no": a["material_no"], "name": a["name"],
                        "tier": "中度疑似", "detail": f"{a['n_records']} 条记录全失效/未生效",
                        "note": f"有 {a['n_records']} 条价格记录但当前无一有效，无法按现价采购/MRP，需补维护当前价。"})
    return out


def rule_price_vs_po(idx, in3):
    """R2：拉近 N 月 PO 实付价，与现价比；返回 (findings, no_inforecord_mids, ok)。"""
    today = datetime.now()
    frm = today.replace(year=today.year - 1).strftime("%Y-%m-%d") if PO_MONTHS >= 12 else None
    fil = {"from_ordered_at": frm, "to_ordered_at": today.strftime("%Y-%m-%d")} if frm else {}
    try:
        pos = S._retry(lambda: in3.mm.purchase_order.list(filter=fil, include_items=True, all=True).items)
    except Exception as e:
        print(f"  ⚠ R2/R5b：PO 近{PO_MONTHS}月拉取失败（{type(e).__name__}）→ 跳过 PO 相关规则")
        return [], [], {}, False
    paid = defaultdict(list)
    spend = defaultdict(float)  # 每料近 N 月采购金额（给 R7 按金额收口）
    qf = None
    amtf = None
    for po in pos:
        for it in (po.get("items") or []):
            if qf is None:
                qf = next((k for k in ("unit_price", "tax_unit_price", "net_price") if k in it), "unit_price")
                amtf = next((k for k in ("total_tax_price", "total_price", "amount", "tax_amount") if k in it), None)
            mid = it.get("material_id") or (it.get("material") or {}).get("material_id")
            p = it.get(qf)
            if mid and isinstance(p, (int, float)) and p > 0:
                paid[str(mid)].append(float(p))
                amt = it.get(amtf) if amtf else None
                spend[str(mid)] += float(amt) if isinstance(amt, (int, float)) else 0.0
    findings = []
    for mid, a in idx.items():
        if a["unit"] != "PCS" or a["cur_med"] is None:
            continue
        ps = paid.get(str(mid))
        if not ps:
            continue
        pm = statistics.median(ps)
        hi, lo = max(pm, a["cur_med"]), min(pm, a["cur_med"])
        if lo > 0 and hi / lo >= DIVERGE_RATIO:
            findings.append({"rule": "R2 价格记录vs成交价", "material_no": a["material_no"], "name": a["name"],
                             "tier": "高度疑似" if hi / lo >= 10 else "中度疑似",
                             "detail": f"现价中位{a['cur_med']:.4f} vs 成交中位{pm:.4f}（{hi / lo:.0f}×）",
                             "note": f"价格记录现价中位 {a['cur_med']:.4f} 与近{PO_MONTHS}月 PO 实付中位 {pm:.4f} 偏离 {hi / lo:.0f}×，价格记录疑过时/错，核对并更新。"})
    # R5b：在 PO 里出现但无任何 info-record
    no_ir = sorted(set(paid.keys()) - {str(m) for m in idx.keys()})
    return findings, no_ir, dict(spend), True


def render(sections, n_pcs, out):
    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    css = """body{font-family:-apple-system,'PingFang SC',sans-serif;margin:0;background:#f5f7fa;color:#1f2937}
.hero{background:linear-gradient(135deg,#1e3a8a,#2563eb);color:#fff;padding:22px 36px}.hero h1{margin:0;font-size:21px}
.hero .s{opacity:.85;font-size:12.5px;margin-top:5px}
.tabbar{display:flex;gap:4px;flex-wrap:wrap;padding:0 28px;background:#fff;border-bottom:1px solid #e5e7eb;position:sticky;top:0;z-index:9}
.tab{border:none;background:none;padding:13px 16px;font-size:13px;color:#6b7280;cursor:pointer;border-bottom:3px solid transparent;font-family:inherit}
.tab:hover{color:#1f2937}.tab.active{color:#2563eb;border-bottom-color:#2563eb;font-weight:600}
.tab .cnt{display:inline-block;margin-left:6px;background:#eef2ff;color:#4338ca;border-radius:10px;padding:0 8px;font-size:11px;font-weight:600}
.tab.active .cnt{background:#2563eb;color:#fff}.tab .cnt.hi{background:#fee2e2;color:#dc2626}
.panel{padding:6px 0 30px}.panel.hidden{display:none}
.desc{margin:14px 36px 2px;color:#6b7280;font-size:12.5px}
table{width:calc(100% - 72px);margin:10px 36px 8px;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.06)}
th,td{padding:8px 11px;text-align:left;font-size:12.5px;border-bottom:1px solid #f1f1f1;vertical-align:top}th{background:#f8fafc;color:#475569}
.t-hi{color:#dc2626;font-weight:700}.t-md{color:#f59e0b;font-weight:600}.note{color:#374151}
.more{margin:2px 36px 0;color:#9ca3af;font-size:11.5px}.empty{margin:24px 36px;color:#9ca3af}"""
    # 每个规则的一句话说明（TAB 下方）
    DESC = {
        "rule#1": "价格记录单位口径错配（按包错录成 PCS）/ 现价跨供应商异常离散。每条点名要改的供应商记录 + 建议纠正 PCS 单价。",
        "R2": "标准价格记录 vs 近 12 月实际 PO 成交价偏离 ≥3×——价格记录过时/录错，两个方向都抓。",
        "R5a": "有价格记录但当前一条有效的都没有（全失效/未生效），无法按现价采购/MRP，需补维护。",
        "R5b": "在 PO 出现但没有任何价格记录，交易了却没维护现价（物料以 id 显示，待 md 反查料号）。",
        "R7": "当前仅 1 家供应商有现价；已按近 12 月采购金额收口，只列买得最多的（全租户独家很多）。",
    }

    def short(title):
        return title.split("（")[0]

    def desc_of(title):
        for k, v in DESC.items():
            if title.startswith(k):
                return v
        return ""

    def table_html(s):
        shown = s["rows"][:s.get("cap", 40)]
        if not shown:
            return '<p class=empty>本规则本期无命中。</p>'
        trs = []
        for i, r in enumerate(shown, 1):
            tc = "t-hi" if r.get("tier") == "高度疑似" else "t-md" if r.get("tier") == "中度疑似" else ""
            trs.append(f'<tr><td>{i}</td><td>{_html.escape(str(r.get("material_no")))}</td>'
                       f'<td>{_html.escape(str(r.get("name") or "")[:22])}</td><td class="{tc}">{r.get("tier","")}</td>'
                       f'<td class=note>{_html.escape(r.get("note") or r.get("detail") or "")}</td></tr>')
        t = (f'<table><thead><tr><th>#</th><th>物料编号</th><th>物料名称</th><th>等级</th><th>核验要点（建议动作）</th></tr></thead>'
             f'<tbody>{"".join(trs)}</tbody></table>')
        if len(s["rows"]) > len(shown):
            t += f'<p class=more>另 {len(s["rows"])-len(shown)} 条未展开（在同名 JSON 中，已按优先级/金额排序）。</p>'
        return t

    tabs, panels = [], []
    for i, s in enumerate(sections):
        cnt = len(s["rows"])
        hi = " hi" if any(r.get("tier") == "高度疑似" for r in s["rows"]) else ""
        act = " active" if i == 0 else ""
        tabs.append(f'<button class="tab{act}" onclick="showTab({i})"><span>{_html.escape(short(s["title"]))}</span>'
                    f'<span class="cnt{hi}">{cnt}</span></button>')
        d = desc_of(s["title"])
        panels.append(f'<div class="panel{"" if i==0 else " hidden"}" id="panel{i}">'
                      f'{("<p class=desc>"+_html.escape(d)+"</p>") if d else ""}{table_html(s)}</div>')
    js = ("function showTab(i){"
          "document.querySelectorAll('.panel').forEach((p,j)=>p.classList.toggle('hidden',j!==i));"
          "document.querySelectorAll('.tab').forEach((t,j)=>t.classList.toggle('active',j===i));}")
    total = sum(len(s["rows"]) for s in sections)
    doc = f"""<!doctype html><html lang=zh><head><meta charset=utf-8><title>主数据巡检·多规则</title><style>{css}</style></head><body>
<div class=hero><h1>主数据质量巡检 · 多规则报告</h1><div class=s>tenant=indx · {now} · 扫描 PCS 物料(有价格记录) {n_pcs} · 命中合计 {total} · 框架 rule#1 + R2/R5/R7</div></div>
<div class=tabbar>{''.join(tabs)}</div>
{''.join(panels)}
<p class=more style="margin:8px 36px 30px">确定性脚本算 → 判读层策展（ADR-0001）。只读快照，Sourcing 按各 TAB 的核验要点人工核实后处理。</p>
<script>{js}</script></body></html>"""
    open(out, "w", encoding="utf-8").write(doc)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "mdm_inspect_report.html"
    in3 = S.get_in3()
    print("拉 info-record（多规则共享）…")
    irs = S._retry(lambda: in3.mm.info_record.list(size=100, all=True).items)
    print(f"  info-record {len(irs)} 条")
    idx = material_index(irs)
    n_pcs = sum(1 for a in idx.values() if a["unit"] == "PCS")

    # R1 单价异常（复用，传入已拉 irs）
    cands = S.build_candidates(in3, irs=irs)
    S.add_quantity_signal(in3, cands)
    for c in cands:
        c["score"], c["tier"], c["cause"], c["note"] = S.score(c)
    cands.sort(key=lambda c: -c["score"])
    r1 = [{"material_no": c["material_no"], "name": c["name"], "tier": c["tier"], "note": c["note"]}
          for c in cands if c["tier"] != "观察"]

    # R5a（info-record only）
    r5a = rule_no_current_price(idx)
    # R2 / R5b（PO，顺手算每料金额给 R7）
    print(f"拉近 {PO_MONTHS} 月 PO 算 R2/R5b…")
    r2, no_ir_mids, spend, po_ok = rule_price_vs_po(idx, in3)
    r5b = [{"rule": "R5b 有采购无价格记录", "material_no": mid, "name": "(无 info-record)", "tier": "中度疑似",
            "note": "在近期 PO 出现但无任何价格记录，交易了却没维护现价，需补建。"} for mid in no_ir_mids]
    # R7 独家供应（按金额收口）
    r7, n_sole_total = rule_sole_source(idx, spend)

    sections = [
        {"title": "rule#1 单价异常（包装单位错配/现价离散）", "rows": r1, "cap": 30},
        {"title": "R2 价格记录 vs 实际成交价偏离", "rows": sorted(r2, key=lambda x: x["tier"] != "高度疑似"), "cap": 40},
        {"title": "R5a 有价格记录但当前无一有效", "rows": r5a, "cap": 40},
        {"title": "R5b 有采购但无任何价格记录", "rows": r5b, "cap": 40},
        {"title": f"R7 独家供应风险（按近{PO_MONTHS}月采购金额 Top；全租户独家共 {n_sole_total}，只列买得多的）", "rows": r7, "cap": 40},
    ]
    render(sections, n_pcs, out)
    allf = {s["title"]: s["rows"] for s in sections}
    json.dump(allf, open(os.path.splitext(out)[0] + ".json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("\n=== 多规则巡检汇总 ===")
    for s in sections:
        print(f"  {s['title']}: {len(s['rows'])} 条")
    if not po_ok:
        print("  （R2/R5b 因 PO 拉取失败本次为空）")
    print(f"\n报告: {out}")


if __name__ == "__main__":
    main()
