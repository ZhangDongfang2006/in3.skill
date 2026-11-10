"""normalize_currency 单测：用 md.currency 字典做 156↔CNY 表示归一（不换汇）。

字典来源 = md.currency 记录（真实字段：iso_currency_no 数值串如 "156"、currency_code/
iso_currency_code 字母如 "CNY"）。归一到统一**字母**表示（currency_code 为规范形）。
未知码原样返回（兜底，不抛）。
"""
from in3_client.gotchas import build_currency_index, normalize_currency

# 取自真实 md.currency 记录形状
_CCY_RECORDS = [
    {"currency_code": "CNY", "iso_currency_code": "CNY", "iso_currency_no": "156"},
    {"currency_code": "USD", "iso_currency_code": "USD", "iso_currency_no": "840"},
    {"currency_code": "AED", "iso_currency_code": "AED", "iso_currency_no": "784"},
]


def test_build_index_maps_both_numeric_and_alpha_to_canonical():
    idx = build_currency_index(_CCY_RECORDS)
    assert idx["156"] == "CNY"
    assert idx["CNY"] == "CNY"
    assert idx["840"] == "USD"


def test_numeric_iso_normalizes_to_alpha():
    idx = build_currency_index(_CCY_RECORDS)
    assert normalize_currency("156", idx) == "CNY"
    assert normalize_currency("784", idx) == "AED"


def test_alpha_passes_through_as_canonical():
    idx = build_currency_index(_CCY_RECORDS)
    assert normalize_currency("CNY", idx) == "CNY"
    assert normalize_currency("USD", idx) == "USD"


def test_numeric_int_input_also_normalized():
    # 后端有时给 int 156 而非 "156"
    idx = build_currency_index(_CCY_RECORDS)
    assert normalize_currency(156, idx) == "CNY"


def test_unknown_code_passes_through_unchanged():
    idx = build_currency_index(_CCY_RECORDS)
    assert normalize_currency("999", idx) == "999"
    assert normalize_currency("XYZ", idx) == "XYZ"


def test_none_and_empty_pass_through():
    idx = build_currency_index(_CCY_RECORDS)
    assert normalize_currency(None, idx) is None
    assert normalize_currency("", idx) == ""


def test_index_tolerates_missing_fields():
    # 某些记录可能缺 iso_currency_no 或 currency_code，不应炸
    idx = build_currency_index([{"currency_code": "JPY"}, {"iso_currency_no": "356"}])
    assert idx["JPY"] == "JPY"
    assert normalize_currency("JPY", idx) == "JPY"
