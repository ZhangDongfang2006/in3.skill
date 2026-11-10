"""坑层 helper 单测（#6 wm.stock 用）：as_string_array + fan_out。"""
from in3_client.gotchas import as_string_array, fan_out


# ---------- as_string_array ----------

def test_filters_empty_string():
    assert as_string_array(["a", "", "b"]) == ["a", "b"]


def test_filters_literal_undefined():
    # cac/CLI 占位 quirk：字面量 "undefined" 不是真 id
    assert as_string_array(["a", "undefined", "b"]) == ["a", "b"]


def test_filters_non_strings():
    assert as_string_array(["a", 1, None, {"x": 1}, "b"]) == ["a", "b"]


def test_single_real_string_to_list():
    assert as_string_array("foo") == ["foo"]


def test_none_to_empty():
    assert as_string_array(None) == []


def test_non_real_single_to_empty():
    assert as_string_array("") == []
    assert as_string_array("undefined") == []
    assert as_string_array(123) == []


# ---------- fan_out ----------

class _P:
    def __init__(self, items, total):
        self.items = items
        self.total = total


def test_fan_out_flatmaps_items_in_id_order():
    def fetch(mid):
        return _P([f"{mid}-1", f"{mid}-2"], 2)
    out = fan_out(["a", "b"], fetch, concurrency=2)
    assert out.items == ["a-1", "a-2", "b-1", "b-2"]  # 顺序对应 id
    assert out.page == 0 and out.has_next is False


def test_fan_out_total_sums_when_all_numeric():
    out = fan_out(["a", "b"], lambda m: _P([m], 3), concurrency=2)
    assert out.total == 6


def test_fan_out_total_none_if_any_none():
    def fetch(mid):
        return _P([mid], None if mid == "b" else 3)
    out = fan_out(["a", "b", "c"], fetch, concurrency=3)
    assert out.total is None  # 一个 None 即污染全局


def test_fan_out_skip_on_error():
    # 参照真 CLI fanOutByMaterialIds：失败子调用整个跳过（if !r continue），**不**影响 total。
    def fetch(mid):
        if mid == "b":
            raise RuntimeError("404")
        return _P([mid], 1)
    out = fan_out(["a", "b", "c"], fetch, concurrency=3)
    assert out.items == ["a", "c"]  # b 被跳过、不抛、不污染其余 id
    assert out.total == 2  # 成功项 a+c=2（失败的 b 不计入，非 None）


def test_fan_out_concurrency_normalized_to_at_least_1():
    out = fan_out(["a"], lambda m: _P([m], 1), concurrency=0)
    assert out.items == ["a"]  # concurrency=0 → max(1,0)=1，不炸


def test_fan_out_empty_ids():
    out = fan_out([], lambda m: _P([m], 1))
    assert out.items == [] and out.total == 0
