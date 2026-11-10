"""#4 wm.available_stock 真后端集成验证（@slow，默认不跑）。

**为何不是 CLI parity**：已对真后端核实——wm CLI 的 `available-stock list --filter
material_ids=<x>` 把多值（甚至单值）经 mergeFilterPairs 逗号拼成**字符串** body
`{"material_ids":"x"}`，而后端 `/stocks/available-stocks/page` 要 **JSON 数组**，故 CLI 这
条路对任意 material_ids 过滤一律 400（已抓证据：单值也 400）。SDK 发数组 body → 正常返数据。
即 **CLI 该路径本身坏掉、SDK 修正了它**（story 4/9 的价值实证），无可比 CLI 基线 → 改为
直接对真后端断言 SDK by_materials 的正确性（handoff 核心指令"对真后端验"）。

`pytest -m slow` 触发。
"""
import pytest


@pytest.mark.slow
def test_by_materials_against_real_backend():
    import in3_client  # noqa: PLC0415

    in3 = in3_client.IN3(tenant="zhuzheng")
    mids = [m["id"] for m in in3.md.material.list(all=False, size=30).items]
    page = in3.wm.available_stock.by_materials(mids)

    # 该租户这批物料里至少有若干条可用库存（真实数据已确认 >0）。
    assert len(page.items) > 0, "by_materials 对真后端应返回非空（这批物料有库存）"

    requested = set(mids)
    for rec in page.items:
        # 字段选择封装：available_qty 必在（可为负=超提）。
        assert "available_qty" in rec
        # 去重主键唯一性 + 回挂 _matched_filter_values。
        assert rec["material_id"] in requested
        matched = set(rec["_matched_filter_values"]["material_ids"])
        assert matched.issubset(requested)
        # 返回的 material_id 必在交集里（它确实匹配上了）。
        assert rec["material_id"] in matched

    # (material_id, plant_no) 复合主键无重复。
    keys = [(r["material_id"], r.get("plant_no")) for r in page.items]
    assert len(keys) == len(set(keys)), "by_materials 结果应已按 (material_id,plant_no) 去重"


@pytest.mark.slow
def test_empty_filter_returns_zero_confirms_by_materials_is_primary_path():
    # 真后端实锤：空 filter 的 list 返 0 → by_materials 才是主入口。
    import in3_client  # noqa: PLC0415

    in3 = in3_client.IN3(tenant="zhuzheng")
    page = in3.wm.available_stock.list(all=False, size=20)
    assert page.items == []
