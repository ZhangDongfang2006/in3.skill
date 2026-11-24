"""价值面 value.py 单测：join(孤儿保留) + compute_sole_source(三态) + df。

join 用 stdlib（确定性、left/outer、未匹配标 _orphan），不依赖 pandas——本身即降级路径。
df 用 pandas（环境已装）；空 items 返空 DataFrame 不抛。
"""
import pytest

from in3_client.value import compute_sole_source, df, join


# ---------- join 孤儿保留 ----------

def test_join_left_outer_keeps_all_left_rows():
    left = [{"material_id": "a", "amt": 10}, {"material_id": "b", "amt": 20}]
    right = [{"material_id": "a", "name": "螺栓"}]
    out = join(left, right, on="material_id")
    assert len(out) == 2  # 左表两行都在
    a = next(r for r in out if r["material_id"] == "a")
    b = next(r for r in out if r["material_id"] == "b")
    assert a["name"] == "螺栓" and a["_orphan"] is False
    assert b.get("name") is None and b["_orphan"] is True  # 右表无匹配 → 孤儿


def test_join_orphan_count_exact():
    left = [{"material_id": str(i)} for i in range(5)]
    right = [{"material_id": "0", "x": 1}, {"material_id": "2", "x": 1}]
    out = join(left, right, on="material_id")
    assert sum(1 for r in out if r["_orphan"]) == 3  # 1,3,4 无匹配


def test_join_three_tables_equivalent_to_pairwise():
    a = [{"material_id": "m", "amt": 10}]
    b = [{"material_id": "m", "stock": 5}]
    c = [{"material_id": "m", "name": "件"}]
    out = join(a, b, c, on="material_id")
    assert len(out) == 1
    r = out[0]
    assert r["amt"] == 10 and r["stock"] == 5 and r["name"] == "件" and r["_orphan"] is False


def test_join_orphan_if_any_table_missing_key():
    a = [{"material_id": "m", "amt": 10}]
    b = [{"material_id": "m", "stock": 5}]
    c = []  # 第三表无记录
    out = join(a, b, c, on="material_id")
    assert out[0]["_orphan"] is True  # 任一表缺 key → 孤儿
    assert out[0]["stock"] == 5


def test_join_empty_left_returns_empty():
    assert join([], [{"material_id": "a"}], on="material_id") == []


# ---------- sole_source 三态 ----------

def test_sole_source_single_supplier_is_risk():
    line_items = [
        {"material_id": "m1", "supplier_id": "s1"},
        {"material_id": "m1", "supplier_id": "s1"},  # 同供应商多条
    ]
    res = compute_sole_source(line_items, ["m1"])
    r = res["m1"]
    assert r["supplier_count"] == 1
    assert r["sole_source"] is True
    assert r["_orphan"] is False


def test_sole_source_multi_supplier_not_risk():
    line_items = [
        {"material_id": "m1", "supplier_id": "s1"},
        {"material_id": "m1", "supplier_id": "s2"},
    ]
    r = compute_sole_source(line_items, ["m1"])["m1"]
    assert r["supplier_count"] == 2
    assert r["sole_source"] is False


def test_sole_source_no_supplier_is_orphan_not_sole():
    # m2 在请求里但无任何 PO/供应商记录 → 孤儿，既非独家也不静默吞
    r = compute_sole_source([], ["m2"])["m2"]
    assert r["supplier_count"] == 0
    assert r["sole_source"] is False
    assert r["_orphan"] is True


def test_sole_source_ignores_null_supplier():
    line_items = [{"material_id": "m1", "supplier_id": None}, {"material_id": "m1", "supplier_id": "s1"}]
    r = compute_sole_source(line_items, ["m1"])["m1"]
    assert r["supplier_count"] == 1
    assert r["sole_source"] is True


# ---------- df ----------

def test_df_builds_dataframe_and_groupby_works():
    items = [
        {"material_id": "a", "total_price": 10},
        {"material_id": "a", "total_price": 5},
        {"material_id": "b", "total_price": 20},
    ]
    d = df(items)
    top = d.groupby("material_id")["total_price"].sum().nlargest(1)
    assert top.index[0] == "b" and top.iloc[0] == 20


def test_df_empty_items_no_raise():
    d = df([])
    assert len(d) == 0
