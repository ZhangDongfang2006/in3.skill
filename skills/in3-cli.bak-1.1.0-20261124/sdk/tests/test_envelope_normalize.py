"""单元测试：in3_client.envelope.normalize（纯函数）。

照 scripts/test_*.py 的 pytest + 纯断言风格。TDD vertical：一次一个行为。
对应 features/in3-client-envelope.feature（RTM #13, #14）。
"""
from in3_client.envelope import normalize


def test_items_unwrap_from_content():
    """RTM #13 — items 取自 content 形信封。"""
    raw = {"content": [{"id": 1}, {"id": 2}], "totalElements": 2}
    page = normalize(raw, requested_size=20)
    assert page.items == [{"id": 1}, {"id": 2}]


def test_items_unwrap_from_records():
    """RTM #13 — items 取自 records（MyBatis-Plus 形）。"""
    raw = {"records": [{"id": 1}]}
    assert normalize(raw, requested_size=20).items == [{"id": 1}]


def test_items_unwrap_from_items():
    """RTM #13 — items 取自 items（自定义形）。"""
    raw = {"items": [{"id": 9}]}
    assert normalize(raw, requested_size=20).items == [{"id": 9}]


def test_items_unwrap_from_list():
    """RTM #13 — items 取自 list（自定义形）。"""
    raw = {"list": [{"id": 7}, {"id": 8}]}
    assert normalize(raw, requested_size=20).items == [{"id": 7}, {"id": 8}]


def test_total_trustworthy_from_total_elements():
    """RTM #14 — totalElements >= len(items) 时取用。"""
    raw = {"content": [{"id": 1}, {"id": 2}], "totalElements": 57}
    assert normalize(raw, requested_size=20).total == 57


def test_total_from_snake_and_plain_keys():
    """RTM #14 — total 也认 total_elements / total。"""
    assert normalize({"records": [{"id": 1}], "total_elements": 9}).total == 9
    assert normalize({"items": [{"id": 1}], "total": 4}).total == 4


def test_total_missing_is_none():
    """RTM #14 — total 缺失 → None（不回退 len）。"""
    raw = {"content": [{"id": 1}, {"id": 2}]}
    assert normalize(raw, requested_size=20).total is None


def test_total_less_than_len_is_none():
    """RTM #14 — total < len(items)（Spring Slice 不可信）→ None，绝不回退 len。"""
    raw = {"content": [{"id": 1}, {"id": 2}, {"id": 3}], "total": 2}
    page = normalize(raw, requested_size=20)
    assert page.total is None
    assert page.total != len(page.items)


def test_has_next_prefers_last_field():
    """RTM #14 — 有 last 字段时 has_next = not last。"""
    assert normalize({"content": [{"id": 1}], "last": False}, requested_size=20).has_next is True
    assert normalize({"content": [{"id": 1}], "last": True}, requested_size=20).has_next is False


def test_has_next_heuristic_without_last():
    """RTM #14 — 无 last 时：满页(len==size)→可能有下页；不满→末页。"""
    full = {"content": [{"i": i} for i in range(20)]}
    assert normalize(full, requested_size=20).has_next is True
    partial = {"content": [{"i": i} for i in range(5)]}
    assert normalize(partial, requested_size=20).has_next is False


def test_page_from_various_sources():
    """RTM #14 — page 从 pageable.pageNumber / pageable.page_number / number / current 取。"""
    assert normalize({"content": [], "pageable": {"pageNumber": 3}}).page == 3
    assert normalize({"content": [], "pageable": {"page_number": 4}}).page == 4
    assert normalize({"content": [], "number": 2}).page == 2
    assert normalize({"content": [], "current": 5}).page == 5
