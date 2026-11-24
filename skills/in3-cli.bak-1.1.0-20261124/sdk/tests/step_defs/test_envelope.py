"""envelope / pagination 归一的 BDD step defs（issue #1 脊柱，纯函数）。

绑定 features/in3-client-envelope.feature → in3_client.envelope.normalize /
pagination.iterate_all。RTM #13（items 多形 unwrap）/ #14（total 不可信置 None、has_next
优先 last、iterate_all 不按 total 循环 + 封顶 truncated）。每个 then 都做**非空业务断言**。
"""
from pytest_bdd import scenarios, given, when, then, parsers

from in3_client.envelope import Page, normalize
from in3_client.pagination import iterate_all

scenarios("../../features/in3-client-envelope.feature")


# --- 假定（given）：构造录制后端响应 raw ---

@given(parsers.parse("后端返回 {container} 形信封"), target_fixture="bdd_context")
def _g_container(container):
    # 五信封之一：items 挂在 content/records/items/list 任一键下。
    return {"raw": {container: [{"id": "a"}, {"id": "b"}]}, "container": container}


@given("后端返回的 total 缺失，或 total 小于本页 items 条数", target_fixture="bdd_context")
def _g_untrustworthy_total():
    # 2 条 items 但 total=0（Spring Slice 不可信）。
    return {"raw": {"content": [{"id": "a"}, {"id": "b"}], "total": 0}}


@given("后端 totalElements 大于等于本页 items 条数", target_fixture="bdd_context")
def _g_trustworthy_total():
    return {"raw": {"content": [{"id": "a"}, {"id": "b"}], "totalElements": 5}}


@given("后端响应含 last 字段", target_fixture="bdd_context")
def _g_has_last():
    return {"raw": {"content": [{"id": "a"}], "last": False}}


@given("后端响应不含 last 字段", target_fixture="bdd_context")
def _g_no_last():
    # 满页（items 条数 == 请求 size）→ 走启发式判 has_next。
    return {"raw": {"content": [{"id": "a"}, {"id": "b"}]}, "size": 2}


@given("一个分页数据源，total 不可信（None）", target_fixture="bdd_context")
def _g_paged_source():
    return {}


# --- 当（when） ---

@when("envelope.normalize 归一")
def _w_normalize(bdd_context):
    bdd_context["page"] = normalize(bdd_context["raw"], requested_size=bdd_context.get("size"))


@when("pagination.iterate_all 翻页取全")
def _w_iterate_all(bdd_context):
    # 有限源：total 自称 99999（不可信），但第 2 页 has_next=False → 应只翻 2 页（证明不按 total）。
    pages = [
        Page(items=[{"id": "p0"}], page=0, total=99999, has_next=True),
        Page(items=[{"id": "p1"}], page=1, total=99999, has_next=False),
    ]
    calls: list = []

    def fetch(page_no):
        calls.append(page_no)
        return pages[page_no]

    bdd_context["agg"] = iterate_all(fetch)
    bdd_context["calls"] = calls


# --- 那么 / 并且（then）：非空断言 ---

@then(parsers.parse("Page.items 取自 {container} 字段"))
def _t_items_from(bdd_context, container):
    assert bdd_context["page"].items == bdd_context["raw"][container]


@then("Page.total 为 None")
def _t_total_none(bdd_context):
    assert bdd_context["page"].total is None


@then("绝不回退成 len(items)")
def _t_no_len_fallback(bdd_context):
    page = bdd_context["page"]
    assert page.total != len(page.items)  # 没被静默设成 2


@then("Page.total 等于该 totalElements")
def _t_total_equals(bdd_context):
    # 比 source 值（非硬编码 5）——证明 SDK 真的从 totalElements 抽取。
    assert bdd_context["page"].total == bdd_context["raw"]["totalElements"]


@then("Page.has_next 等于 not last")
def _t_has_next_from_last(bdd_context):
    raw = bdd_context["raw"]
    assert bdd_context["page"].has_next is (not raw["last"])  # last=False → True（比 source）
    # 反向再验一次：last=True → has_next=False（证明确实读 last、非恒返 True）。
    assert normalize({"content": [{"id": "a"}], "last": True}).has_next is False


@then("当本页 items 条数等于请求 size 时 has_next 为真，否则为假")
def _t_has_next_heuristic(bdd_context):
    size = bdd_context["size"]
    full = normalize({"content": [{"id": i} for i in range(size)]}, requested_size=size)
    partial = normalize({"content": [{"id": 0}]}, requested_size=size)
    assert full.has_next is True      # 满页 → 可能还有下页
    assert partial.has_next is False   # 不满 → 末页


@then("翻页按 last/启发式判停、不按 total 计算次数")
def _t_iterate_stop(bdd_context):
    # total 自称 99999，但 has_next=False 后立即停 → 只 fetch 了 2 页。
    assert bdd_context["calls"] == [0, 1]
    assert len(bdd_context["agg"].items) == 2
    assert bdd_context["agg"].truncated is False


@then("达到封顶上限时早停并把结果标 truncated")
def _t_truncated(bdd_context):
    # 无限源（has_next 恒 True）+ 小封顶 → 早停标 truncated。
    def fetch(page_no):
        return Page(items=[{"id": page_no}], page=page_no, total=None, has_next=True)

    agg = iterate_all(fetch, max_pages=3)
    assert agg.truncated is True
    assert agg.pages_fetched == 3
