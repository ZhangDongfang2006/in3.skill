"""本月采购金额 Top10 物料里，有几个是独家供应（★风险）。与北极星表里 ★ 数量对得上。"""
import in3_client

in3 = in3_client.IN3()
pos = in3.mm.purchase_order.list(
    filter={"from_ordered_at": "2026-05-01", "to_ordered_at": "2026-05-31"},
    include_items=True, all=True,
).items
lines = [it for po in pos for it in (po.get("items") or [])]

amount = {}
for li in lines:
    mid = li["material_id"]
    amount[mid] = amount.get(mid, 0.0) + float(li.get("total_tax_price") or 0)

top10 = sorted(amount, key=lambda m: -amount[m])[:10]
ss = in3.sole_source(top10)
sole = [m for m in top10 if ss[m]["sole_source"]]
print(f"本月采购 Top10 物料里，独家供应（★风险）= {len(sole)} 个 / 共 10 个")
