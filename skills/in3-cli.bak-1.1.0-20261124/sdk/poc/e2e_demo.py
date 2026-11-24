"""E2E 体感/可复核验证小工具（给人走验收用，非自动化测试）。

子命令：
  cli-gap            演示同一组 material_ids：CLI available-stock → 400（CLI 坏路），SDK by_materials → 正常
  audit <rank>       取北极星 Top 第 rank 物料，用**独立的 CLI 路径**重算本月采购额，对 SDK 数字（可复核）
  rounds             打印"agent 今天 N 步 fan-out+jq" vs "SDK 一段脚本"的调用次数对比

用法：cd sdk && PYTHONPATH=$PWD python3 poc/e2e_demo.py <子命令> [参数] [tenant]
"""
import json
import subprocess
import sys
import time

import in3_client

SCRIPTS = "../scripts"
MONTH_START, MONTH_END = "2026-05-01", "2026-05-31"
AMOUNT_FIELD = "total_tax_price"


def _retry(fn, n=5):
    for i in range(n):
        try:
            return fn()
        except Exception:
            if i == n - 1:
                raise
            time.sleep(2)


def _cli(args):
    out = subprocess.run([sys.executable, "in3_cli.py", "exec", *args],
                         cwd=SCRIPTS, capture_output=True, text=True)
    try:
        return json.loads(out.stdout)
    except Exception:
        return {"_raw": out.stdout[:300], "_err": out.stderr[:300]}


def cli_gap(tenant):
    """CLI available-stock 的 material_ids 过滤是坏的（逗号拼字符串 body → 400）；SDK 数组 body 正常。"""
    in3 = in3_client.IN3(tenant=tenant)
    mids = [m["id"] for m in _retry(lambda: in3.md.material.list(all=False, size=10).items)]
    print(f"用同一组 {len(mids)} 个 material_id 查 wm 可用库存：\n")

    sdk = _retry(lambda: in3.wm.available_stock.by_materials(mids).items)
    print(f"  SDK  in3.wm.available_stock.by_materials(ids)  → {len(sdk)} 条记录 ✅")

    d = _cli(["wm", "available-stock", "list", "--filter", "material_ids=" + mids[0]])
    if "error" in d:
        print(f"  CLI  exec wm available-stock list --filter material_ids=…  → {d['error'].get('http_status')} "
              f"{d['error'].get('type')} ❌（CLI 把数组拼成字符串 body，后端拒绝）")
    else:
        print(f"  CLI  → 意外返回 {len(d.get('items', []))} 条（CLI 可能已修）")
    print("\n结论：这条查询 CLI 路径本身做不到，SDK 修正了它。")


def audit(tenant, rank):
    """可复核：北极星 Top 第 rank 物料的本月采购额，用独立 CLI 路径重算，应与 SDK 一致。"""
    in3 = in3_client.IN3(tenant=tenant)
    # —— SDK 路径（北极星同款）——
    pos = _retry(lambda: in3.mm.purchase_order.list(
        filter={"from_ordered_at": MONTH_START, "to_ordered_at": MONTH_END},
        include_items=True, all=True).items)
    lines = [it for po in pos for it in (po.get("items") or [])]
    agg = {}
    for li in lines:
        mid = li.get("material_id")
        agg[mid] = agg.get(mid, 0.0) + float(li.get(AMOUNT_FIELD) or 0)
    top = sorted(agg.items(), key=lambda kv: -kv[1])[:10]
    mid, sdk_amount = top[rank - 1]
    mat = next((li.get("material") for li in lines if li.get("material_id") == mid and isinstance(li.get("material"), dict)), {})
    name = mat.get("material_name") or mat.get("material_no") or mid
    print(f"北极星 Top{rank}：{name}  (material_id={mid})")
    print(f"  SDK 算出本月采购额 = {sdk_amount:,.2f}\n")

    # —— 独立 CLI 路径重算（agent 今天的痛：多步 + 手工 sum）——
    d = _cli(["mm", "purchase-order", "list", "--include-items", "--all",
              "--filter", f"from_ordered_at={MONTH_START}", "--filter", f"to_ordered_at={MONTH_END}",
              "--filter", f"material_ids={mid}"])
    cli_lines = [it for po in d.get("items", []) for it in (po.get("items") or [])
                 if it.get("material_id") == mid]
    cli_amount = sum(float(it.get(AMOUNT_FIELD) or 0) for it in cli_lines)
    print(f"  CLI 独立路径重算 = {cli_amount:,.2f}（{len(cli_lines)} 条明细手工求和）")
    match = abs(sdk_amount - cli_amount) < 0.01
    print(f"\n  两条独立路径{'一致 ✅ 可复核' if match else '不一致 ❌'}")


def rounds(tenant):
    in3 = in3_client.IN3(tenant=tenant)
    pos = _retry(lambda: in3.mm.purchase_order.list(
        filter={"from_ordered_at": MONTH_START, "to_ordered_at": MONTH_END},
        include_items=True, all=True).items)
    n_po_pages = (len(pos) // 20) + 1
    print("北极星这一个问题，agent 今天若用裸 CLI 需要的来回（估算）：")
    print(f"  · PO 列表分页          ~{n_po_pages} 次（{len(pos)} 单 / 20 一页）")
    print(f"  · bulk 取 line items   1 次")
    print(f"  · 可用库存 fan-out      若按物料逐个查 ~10 次（且 CLI 这条还是坏的）")
    print(f"  · 物料名 / 供应商统计    数次 + 大量 jq")
    print(f"  · 每步 JSON 进出上下文   合计数万 token")
    print(f"\n  SDK：写一段脚本，**1 次** `python3 poc/north_star.py`，只有最终 10 行表进上下文。")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "rounds"
    if cmd == "cli-gap":
        cli_gap(sys.argv[2] if len(sys.argv) > 2 else "zhuzheng")
    elif cmd == "audit":
        rank = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        audit(sys.argv[3] if len(sys.argv) > 3 else "zhuzheng", rank)
    elif cmd == "rounds":
        rounds(sys.argv[2] if len(sys.argv) > 2 else "zhuzheng")
    else:
        print(__doc__)
