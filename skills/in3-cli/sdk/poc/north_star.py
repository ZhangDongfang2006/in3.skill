"""北极星主任务（issue #9）：2026-05 本月采购金额 Top10 物料 × wm 可用库存 × 独家供应。

跨 mm（采购）+ wm（库存）+ md（物料主数据），全在子进程内存里 join，只 print 最终表。
A surface 直跑：`python3 poc/north_star.py`（或经 C 壳 `in3_cli.py run`）。

演示 SDK 价值面：坑层（chunk/open_qty/分页/POST-body/多值 filter）全下沉，agent 只写这几十行。
"""
import sys

import in3_client

TENANT = sys.argv[1] if len(sys.argv) > 1 else "zhuzheng"
MONTH_START, MONTH_END = "2026-05-01", "2026-05-31"
AMOUNT_FIELD = "total_tax_price"  # 含税采购金额（line item 级）
TOP_N = 10


def main():
    in3 = in3_client.IN3(tenant=TENANT)

    # 1) 本月 PO + line items（一次调用：分页 + bulk-get-by-po + open_qty 兜底全下沉）
    pos = in3.mm.purchase_order.list(
        filter={"from_ordered_at": MONTH_START, "to_ordered_at": MONTH_END},
        include_items=True, all=True,
    ).items
    lines = [it for po in pos for it in (po.get("items") or [])]

    # 2) 按物料聚合采购金额 → Top10（pandas groupby/nlargest，不手搓 jq）
    d = in3.df(lines)
    top = d.groupby("material_id")[AMOUNT_FIELD].sum().nlargest(TOP_N)
    top_ids = [str(x) for x in top.index]
    amount_rows = [{"material_id": mid, "purchase_amount": round(float(top.loc[mid]), 2)} for mid in top_ids]

    # 3) 各自 wm 可用库存（by_materials fan-out：POST-body 分页 + 数组 filter，CLI 做不到）
    stock = in3.wm.available_stock.by_materials(top_ids).items
    stock_by_mat: dict = {}
    for r in stock:
        stock_by_mat[r["material_id"]] = stock_by_mat.get(r["material_id"], 0.0) + float(r.get("available_qty") or 0)
    stock_rows = [{"material_id": mid, "available_qty": stock_by_mat.get(mid)} for mid in top_ids]

    # 4) 物料名（md.material 主数据；缺记录的料品会在 join 里标 _orphan）
    name_rows = []
    for mid in top_ids:
        try:
            m = in3.md.material.get(mid)
            name_rows.append({"material_id": mid, "material_name": m.get("material_name"), "material_no": m.get("material_no")})
        except Exception:
            pass  # 无主数据 → join 时自动 _orphan

    # 5) 独家供应（三态：1 供=独家风险 / ≥2 / 0=孤儿）
    ss = in3.sole_source(top_ids)

    # 6) 内存 join（左主表=金额 Top10，孤儿保留）
    rows = in3.join(amount_rows, stock_rows, name_rows, on="material_id")
    for r in rows:
        info = ss.get(r["material_id"], {})
        r["supplier_count"] = info.get("supplier_count")
        r["sole_source"] = info.get("sole_source")

    # 输出
    print(f"=== {TENANT} · {MONTH_START}~{MONTH_END} 采购金额 Top{TOP_N} 物料 × 可用库存 × 独家供应 ===")
    print(f"（PO {len(pos)} 单 / line {len(lines)} 行；金额字段={AMOUNT_FIELD}）\n")
    hdr = f"{'#':>2} {'物料名':<20} {'采购金额':>14} {'可用库存':>10} {'供应商数':>8} {'独家':>4} {'孤儿':>4}"
    print(hdr)
    print("-" * len(hdr))
    for i, r in enumerate(rows, 1):
        name = (r.get("material_name") or r.get("material_no") or r["material_id"][:12])[:20]
        amt = f"{r['purchase_amount']:,.2f}"
        stk = "—" if r.get("available_qty") is None else f"{r['available_qty']:,.1f}"
        sc = r.get("supplier_count")
        sole = "★" if r.get("sole_source") else ""
        orphan = "孤" if r.get("_orphan") else ""
        print(f"{i:>2} {name:<20} {amt:>14} {stk:>10} {str(sc):>8} {sole:>4} {orphan:>4}")


if __name__ == "__main__":
    main()
