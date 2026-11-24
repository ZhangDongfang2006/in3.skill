"""POC 四指标前后对比测量器（issue #9）。

同一任务集，CLI 现状路径 vs SDK 路径各跑一遍，**实测**：
  ① parity（业务数字逐位一致）② token 经济（进 LLM 上下文的 token 降幅，tiktoken 实算）
  ③ 轮次/调用次数（枚举）。④ doctor BARS 需另跑 in3-cli-doctor（HITL），本器只标注不臆造。

落机读 JSON 报告（照 test_price_privilege_e2e.py 形态）。跑法：
  cd sdk && PYTHONPATH=$PWD python3 poc/poc_eval.py   （或 in3_cli.py run poc/poc_eval.py）
"""
import json
import subprocess
import sys
import time

import tiktoken

import in3_client

_ENC = tiktoken.get_encoding("cl100k_base")
SCRIPTS = "../scripts"
TENANT = "zhuzheng"
MS, ME = "2026-05-01", "2026-05-31"
AMT = "total_tax_price"
TOKEN_THRESHOLD = 0.70  # ② 阈值（PRD §4.1②，建议 ≥70%↓）


def toks(obj) -> int:
    s = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    return len(_ENC.encode(s))


def _retry(fn, n=5):
    for i in range(n):
        try:
            return fn()
        except Exception:
            if i == n - 1:
                raise
            time.sleep(2)


def _cli_raw(args):
    """跑一条 exec，返回 (stdout 原文, 解析后的 dict/None)。stdout 原文 = 进 LLM 上下文的量。"""
    out = subprocess.run([sys.executable, "in3_cli.py", "exec", *args],
                         cwd=SCRIPTS, capture_output=True, text=True)
    try:
        return out.stdout, json.loads(out.stdout)
    except Exception:
        return out.stdout, None


# ---------------- Task 1：主任务（跨 mm+wm+md）----------------

def task_main(in3):
    # —— CLI 现状路径：agent 必须把中间 JSON 全量拉进上下文做 jq 聚合 ——
    # 本月 PO + line items（一次 --all --include-items 就是这么大的 JSON 回流）
    cli_po_raw, cli_po = _cli_raw(["mm", "purchase-order", "list", "--all", "--include-items",
                                   "--filter", f"from_ordered_at={MS}", "--filter", f"to_ordered_at={ME}"])
    cli_lines = [it for po in (cli_po or {}).get("items", []) for it in (po.get("items") or [])]
    cli_amount = {}
    for li in cli_lines:
        mid = li.get("material_id")
        cli_amount[mid] = cli_amount.get(mid, 0.0) + float(li.get(AMT) or 0)
    cli_top = sorted(cli_amount.items(), key=lambda kv: -kv[1])[:10]
    # CLI 还要为 Top10 各查库存——但 wm CLI 的 material_ids filter 是坏的（400），逐个也 400。
    cli_stock_attempts = []
    for mid, _ in cli_top:
        raw, d = _cli_raw(["wm", "available-stock", "list", "--filter", f"material_ids={mid}"])
        cli_stock_attempts.append({"material_id": mid, "ok": bool(d and "items" in d),
                                   "err": (d or {}).get("error", {}).get("http_status")})
    cli_ctx_tokens = toks(cli_po_raw)  # 主导项：3900 行明细 JSON 全量进上下文
    cli_rounds = 1 + len(cli_top)  # 1 次 PO + 每物料 1 次库存（且都 400）

    # —— SDK 路径：坑层全下沉，中间数据留子进程，只有最终表进上下文 ——
    pos = _retry(lambda: in3.mm.purchase_order.list(
        filter={"from_ordered_at": MS, "to_ordered_at": ME}, include_items=True, all=True).items)
    lines = [it for po in pos for it in (po.get("items") or [])]
    sdk_amount = {}
    for li in lines:
        mid = li["material_id"]
        sdk_amount[mid] = sdk_amount.get(mid, 0.0) + float(li.get(AMT) or 0)
    sdk_top = sorted(sdk_amount.items(), key=lambda kv: -kv[1])[:10]
    top_ids = [m for m, _ in sdk_top]
    stock = _retry(lambda: in3.wm.available_stock.by_materials(top_ids).items)
    stock_by_mat = {}
    for r in stock:
        stock_by_mat[r["material_id"]] = stock_by_mat.get(r["material_id"], 0.0) + float(r.get("available_qty") or 0)
    ss = _retry(lambda: in3.sole_source(top_ids))
    # SDK「进上下文」= 最终 10 行结果（agent 只 print 这个）
    sdk_result = [{"material_id": m, "amount": round(a, 2),
                   "available_qty": stock_by_mat.get(m),
                   "sole_source": ss[m]["sole_source"], "supplier_count": ss[m]["supplier_count"]}
                  for m, a in sdk_top]
    sdk_ctx_tokens = toks(sdk_result)
    sdk_rounds = 1  # 一次 `run`

    # —— ① parity：Top10 物料采购额逐位一致（报告脱敏：只留 match 布尔，不落真实金额/物料 id）——
    matches = [sm == cm and abs(sa - ca) < 0.01 for (sm, sa), (cm, ca) in zip(sdk_top, cli_top)]
    parity_ok = all(matches) and len(sdk_top) == len(cli_top) > 0

    drop = 1 - (sdk_ctx_tokens / cli_ctx_tokens) if cli_ctx_tokens else 0
    return {
        "task": "main · 2026-05 采购额 Top10 × wm 可用库存 × 独家供应（mm+wm+md）",
        "parity": {"ok": parity_ok, "matched": sum(matches), "rows_compared": len(matches),
                   "note": "Top10 物料采购额 SDK vs CLI 逐位一致（金额到分）；脱敏不落真实金额/物料 id"},
        "token": {"cli_ctx_tokens": cli_ctx_tokens, "sdk_ctx_tokens": sdk_ctx_tokens,
                  "cli_ctx_bytes": len(cli_po_raw.encode("utf-8")), "sdk_ctx_bytes": len(json.dumps(sdk_result, ensure_ascii=False).encode("utf-8")),
                  "drop_pct": round(drop * 100, 2), "threshold_pct": TOKEN_THRESHOLD * 100,
                  "pass": drop >= TOKEN_THRESHOLD},
        "rounds": {"cli_calls": cli_rounds, "sdk_calls": sdk_rounds,
                   "sdk_in_range_1_3": 1 <= sdk_rounds <= 3},
        "notes": {"po_count": len(pos), "line_count": len(lines),
                  "cli_stock_dimension_broken": all(not a["ok"] for a in cli_stock_attempts),
                  "cli_stock_http": sorted({a["err"] for a in cli_stock_attempts})},
    }


# ---------------- Task 2：大输出分页（Spring Slice → total=None）----------------

def task_pagination(in3):
    # SDK 内部翻完所有页，total 不可信置 None（不偷设 len），中间页不进上下文
    page = _retry(lambda: in3.mm.purchase_order.list(
        filter={"from_ordered_at": MS, "to_ordered_at": ME}, all=True))
    return {
        "task": "大输出分页 · Spring Slice total 不可信",
        "items_fetched": len(page.items),
        "total_is_none": page.total is None,   # ✅ 不被静默设成 len(items)
        "pass": page.total is None and len(page.items) > 0,
        "note": "SDK 内部 iterate_all 翻全部页；total<len 或缺失→None（¥111K 防御）；agent 不见中间页",
    }


# ---------------- Task 3：silent-filter（multi-value material_ids）----------------

def task_silent_filter(in3):
    # 取真实出现在 PO 里的 material_id（保证多值过滤能返回 PO 触发 _matched_filter_values）
    seed = _retry(lambda: in3.mm.purchase_order.list(
        filter={"from_ordered_at": MS, "to_ordered_at": ME}, include_items=True, all=False, size=20).items)
    mids = list({it["material_id"] for po in seed for it in (po.get("items") or [])
                 if it.get("material_id")})[:5]
    page = _retry(lambda: in3.mm.purchase_order.list(
        filter={"material_ids": mids}, include_items=True, all=True))
    annotated = [po for po in page.items if "_matched_filter_values" in po]
    # 任取一个被标注的 PO，看交集 ⊆ 请求
    sample = annotated[0]["_matched_filter_values"]["material_ids"] if annotated else []
    return {
        "task": "silent-filter 防御 · multi-value material_ids",
        "requested_count": len(mids),
        "pos_returned": len(page.items),
        "pos_with_matched_filter_values": len(annotated),
        "sample_matched_subset_of_requested": set(sample).issubset(set(mids)),
        "pass": len(annotated) > 0 and set(sample).issubset(set(mids)),
        "note": "SDK 回挂 _matched_filter_values=返回∩请求，区分『我传的』vs『后端并集』；silent ignore 不再静默吞",
    }


def main():
    in3 = in3_client.IN3(tenant=TENANT)
    report = {
        "poc": "in3_client v1 四指标前后对比",
        "tenant": TENANT, "month": f"{MS}~{ME}", "amount_field": AMT,
        "tasks": [task_main(in3), task_pagination(in3), task_silent_filter(in3)],
        "metric4_doctor": {"status": "DEFER", "note": "④ doctor BARS 需另跑 in3-cli-doctor（多 agent BARS 评测，HITL）；本器不臆造分数。目标=不退非翻 PASS。"},
    }
    t1 = report["tasks"][0]
    report["summary"] = {
        "parity_ok": t1["parity"]["ok"],
        "token_drop_pct": t1["token"]["drop_pct"],
        "token_pass": t1["token"]["pass"],
        "sdk_rounds": t1["rounds"]["sdk_calls"],
        "cli_rounds": t1["rounds"]["cli_calls"],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
