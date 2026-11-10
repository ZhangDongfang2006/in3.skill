"""价值面：df（pandas 聚合）+ join（孤儿保留 left/outer）+ compute_sole_source（三态）。

join 用 stdlib 实现（确定性、不依赖 pandas）——这也是 pandas 缺失时的降级路径。
df 用 pandas（缺失则打印降级提示并返回原 items，agent 失去 groupby 但不 hard-fail）。
"""
from __future__ import annotations

import sys
from typing import Optional


def df(items: list):
    """归一 items → pandas DataFrame，供 groupby/nlargest。pandas 缺失则降级返回 items。"""
    try:
        import pandas as pd  # noqa: PLC0415
    except ImportError:  # pragma: no cover - 环境已装 pandas
        print("[in3_client] pandas 不可用，IN3.df 降级返回原始 items（无 DataFrame 聚合）", file=sys.stderr)
        return list(items)
    return pd.DataFrame(list(items))


def join(*tables, on: str):
    """多表 left/outer join（首表为左主表）：左表每行都保留；任一右表缺该 key 的行标 _orphan=true。

    stdlib 实现，确定性、不依赖 pandas（即降级路径）。右表字段合并进左行（同名右覆盖左，
    与 pandas merge 后缀行为不同——v1 各表列名不冲突，简单覆盖即可）。
    """
    if not tables:
        return []
    left = [dict(r) for r in tables[0]]
    rights = tables[1:]
    indexes = [{r.get(on): r for r in tbl} for tbl in rights]

    out = []
    for row in left:
        key = row.get(on)
        orphan = False
        for idx in indexes:
            match = idx.get(key)
            if match is None:
                orphan = True
                continue
            for k, v in match.items():
                if k != on:
                    row[k] = v
        row["_orphan"] = orphan
        out.append(row)
    return out


def compute_sole_source(line_items: list, material_ids: list) -> dict:
    """从 PO line items 算每个 material 的独家供应风险（三态）。

    line_items：含 material_id + supplier_id 的 PO 明细（来自 mm.purchase_order include_items）。
    返回 {material_id: {supplier_count, suppliers, sole_source, _orphan}}：
      1 供应商 → sole_source=True（独家=风险）；≥2 → False；0（无任何记录）→ _orphan=True（既非独家也不吞）。
    """
    by_material: dict = {mid: set() for mid in material_ids}
    for it in line_items:
        mid = it.get("material_id")
        sup = it.get("supplier_id")
        if mid in by_material and sup is not None:
            by_material[mid].add(sup)

    result = {}
    for mid in material_ids:
        suppliers = by_material.get(mid, set())
        count = len(suppliers)
        result[mid] = {
            "supplier_count": count,
            "suppliers": sorted(suppliers),
            "sole_source": count == 1,
            "_orphan": count == 0,
        }
    return result
