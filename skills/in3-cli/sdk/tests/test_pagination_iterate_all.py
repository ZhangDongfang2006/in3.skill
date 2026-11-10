"""pagination.iterate_all 单测：纯函数，靠 page.has_next 判停，绝不按 total 循环。"""
from in3_client.envelope import Page
from in3_client.pagination import iterate_all


def _pages(*specs):
    """specs: list of (items, has_next[, total]) → 返回一个按页号返回 Page 的 fetch_page，
    并记录被请求过的页号。"""
    calls = []

    def fetch_page(page_no):
        calls.append(page_no)
        items, has_next, *rest = specs[page_no]
        total = rest[0] if rest else None
        return Page(items=list(items), page=page_no, total=total, has_next=has_next)

    fetch_page.calls = calls
    return fetch_page


def test_single_page_stops_immediately():
    fetch = _pages((["a", "b"], False))
    result = iterate_all(fetch)
    assert result.items == ["a", "b"]
    assert result.truncated is False
    assert fetch.calls == [0]


def test_walks_pages_until_has_next_false():
    fetch = _pages(
        (["a"], True),
        (["b"], True),
        (["c"], False),
    )
    result = iterate_all(fetch)
    assert result.items == ["a", "b", "c"]
    assert result.truncated is False
    assert fetch.calls == [0, 1, 2]


def test_does_not_use_total_to_decide_loop():
    # total 说还有一万条，但 has_next=False 必须立刻停（证明不按 total 翻页）。
    fetch = _pages((["only"], False, 10000))
    result = iterate_all(fetch)
    assert result.items == ["only"]
    assert result.truncated is False
    assert fetch.calls == [0]


def test_total_none_does_not_break_iteration():
    # Spring Slice：total=None，全靠 has_next 启发式（envelope 已算好）继续翻。
    fetch = _pages(
        (["a"], True, None),
        (["b"], False, None),
    )
    result = iterate_all(fetch)
    assert result.items == ["a", "b"]
    assert result.truncated is False


def test_caps_at_max_pages_and_marks_truncated():
    # has_next 永远 True（后端坏掉/启发式恒满页）→ 封顶早停并标 truncated。
    def fetch_page(page_no):
        return Page(items=[page_no], page=page_no, total=None, has_next=True)

    result = iterate_all(fetch_page, max_pages=3)
    assert result.items == [0, 1, 2]
    assert result.truncated is True
    assert result.pages_fetched == 3


def test_empty_first_page():
    fetch = _pages(([], False))
    result = iterate_all(fetch)
    assert result.items == []
    assert result.truncated is False
    assert fetch.calls == [0]
