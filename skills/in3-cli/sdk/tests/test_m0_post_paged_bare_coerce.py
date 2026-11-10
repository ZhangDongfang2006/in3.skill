"""M0 基座① 单测：PostPagedEntity + coerce_to_page/_wrap_items/_list_bare + PagedEntity._sub_list。

对应 issue #10（全部）+ issue #11 的 _wrap_items。全程 FakeTransport 桩，不碰真后端/CLI。
桩模式照 tests/test_http.py：FakeResponse / FakeTransport 录 method/url/params/json/headers。
"""
from dataclasses import dataclass, field

import pytest

from in3_client.auth import Session
from in3_client.config import Credentials
from in3_client.envelope import Page, coerce_to_page, _wrap_items, normalize
from in3_client.http import HttpClient
from in3_client.entities.base import PagedEntity, PostPagedEntity


# ---------- 桩 ----------

@dataclass
class FakeResponse:
    status_code: int
    _json: object = None
    content_type: str = "application/json"
    text: str = ""

    @property
    def headers(self):
        return {"content-type": self.content_type}

    def json(self):
        return self._json


@dataclass
class FakeTransport:
    responses: list
    calls: list = field(default_factory=list)

    def __call__(self, method, url, headers=None, params=None, **kw):
        self.calls.append(
            {"method": method, "url": url, "headers": headers, "params": params, "json": kw.get("json")}
        )
        return self.responses.pop(0)


_CRED = Credentials(
    api_host="https://apiv3.industics.com/service",
    tenant_domain="indx",
    username="corp:zhuzheng@indx",
    encrypted_password="AESCIPHER==",
    alias="zhuzheng",
)
_TOKEN = {"access_token": "jwt", "tenant_id": "10030", "tenant_domain": "indx", "user_id": "u-42"}


def _http(data_responses):
    sess = Session(_CRED, transport=FakeTransport([FakeResponse(200, _TOKEN)]))
    data_tr = FakeTransport(data_responses)
    return HttpClient(sess, transport=data_tr), data_tr, sess


# 测试用具体子类：定 MOD + 端点路径，复用基座 _list/_sub_list/_list_bare。

class _FakePostPaged(PostPagedEntity):
    MOD = "pp"

    def __init__(self, http, sess):
        super().__init__(_CRED, sess, http)

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/production-plans/list"

    def list(self, *, filter=None, size=20, all=True):
        return self._list(base_params=filter, size=size, all_pages=all)


class _FakePaged(PagedEntity):
    MOD = "mm"

    def __init__(self, http, sess):
        super().__init__(_CRED, sess, http)

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/boms/page"

    def bare_list(self, *, size=20, all=False):
        return self._list_bare(base_params=None, size=size, all_pages=all)

    def sub(self, path, params=None, size=20, all=False, max_pages=1000):
        return self._sub_list(path, params=params, size=size, all_pages=all, max_pages=max_pages)


# =========================================================
# coerce_to_page —— 三形
# =========================================================

def test_coerce_bare_top_level_list():
    """① bare top-level JSON array → Page(items=list, page=0, total=len, has_next=False)。"""
    data = [{"id": 1}, {"id": 2}, {"id": 3}]
    page = coerce_to_page(data)
    assert isinstance(page, Page)
    assert page.items == data
    assert page.page == 0
    assert page.total == 3
    assert page.has_next is False


def test_coerce_dict_with_items():
    """② {items:[...]} dict-with-items → 同形 Page。"""
    data = {"items": [{"id": "a"}, {"id": "b"}]}
    page = coerce_to_page(data)
    assert page.items == [{"id": "a"}, {"id": "b"}]
    assert page.page == 0
    assert page.total == 2
    assert page.has_next is False


def test_coerce_single_tree_dict():
    """③ single tree dict（非 items 形裸 dict）→ dict→[dict] coerce 包成 total=1。"""
    tree = {"node": "root", "children": [{"node": "leaf"}]}
    page = coerce_to_page(tree)
    assert page.items == [tree]
    assert page.page == 0
    assert page.total == 1
    assert page.has_next is False


def test_coerce_empty_list_total_zero():
    """空数组 → Page(items=[], total=0)。"""
    page = coerce_to_page([])
    assert page.items == []
    assert page.total == 0
    assert page.has_next is False


# =========================================================
# _wrap_items（issue #11）—— {items} 薄 alias，委托 coerce_to_page
# =========================================================

def test_wrap_items_dict_with_items():
    """_wrap_items 吃 {items:[...]} → Page{items, page=0, total=len, has_next=False}。"""
    page = _wrap_items({"items": [{"q": 1}, {"q": 2}, {"q": 3}]})
    assert page.items == [{"q": 1}, {"q": 2}, {"q": 3}]
    assert page.page == 0
    assert page.total == 3
    assert page.has_next is False


def test_wrap_items_delegates_to_coerce():
    """_wrap_items 是 coerce_to_page 的薄入口：同一 {items} 输入两者等价（不另写一套）。"""
    data = {"items": [{"x": 1}]}
    assert _wrap_items(data) == coerce_to_page(data)


def test_wrap_items_empty():
    page = _wrap_items({"items": []})
    assert page.items == []
    assert page.total == 0


# =========================================================
# bare-array 旧路径回归 —— 证明旧路径不可走
# =========================================================

def test_bare_array_via_get_json_or_swallows_empty_to_empty_dict():
    """(a) 空裸 list 走 get_json → `or {}` → {} → normalize({}) → Page(items=[]) 静默丢。"""
    http, _, _ = _http([FakeResponse(200, [])])  # 后端返裸空数组
    raw = http.get_json("https://h/boms/list")
    assert raw == {}  # 空 list 被 `or {}` 吞成空 dict
    page = normalize(raw)
    assert page.items == []  # 数据形态已丢失（即便原本有也会被吞）


def test_bare_array_direct_into_normalize_raises_attribute_error():
    """(b) 非空裸 list 直进 envelope.normalize → AttributeError（_extract_total 调 .get）。"""
    bare = [{"id": 1}, {"id": 2}]
    with pytest.raises(AttributeError):
        normalize(bare)


def test_bare_array_via_get_json_then_normalize_also_raises():
    """非空裸 list 经 get_json（truthy 不被 or {} 吞）后喂 normalize 同样炸——旧路径双向死。"""
    http, _, _ = _http([FakeResponse(200, [{"id": 1}])])
    raw = http.get_json("https://h/boms/list")
    assert raw == [{"id": 1}]  # 非空 list truthy，or {} 不生效
    with pytest.raises(AttributeError):
        normalize(raw)


# =========================================================
# _list_bare —— 走 _request 原值路径，coerce_to_page 包形
# =========================================================

def test_list_bare_wraps_nonempty_bare_array():
    http, tr, sess = _http([FakeResponse(200, [{"id": "b1"}, {"id": "b2"}])])
    ent = _FakePaged(http, sess)
    page = ent.bare_list()
    assert page.items == [{"id": "b1"}, {"id": "b2"}]
    assert page.page == 0
    assert page.total == 2
    assert page.has_next is False
    assert tr.calls[0]["method"] == "GET"


def test_list_bare_empty_array_total_zero_not_swallowed():
    """空裸数组 → Page(items=[], total=0) 而非被吞成空 dict。"""
    http, tr, sess = _http([FakeResponse(200, [])])
    ent = _FakePaged(http, sess)
    page = ent.bare_list()
    assert page.items == []
    assert page.total == 0
    assert page.has_next is False


# =========================================================
# PostPagedEntity —— filter 进 body / 分页参进 query / has_next 翻页不按 total
# =========================================================

def test_post_paged_filter_in_body_paging_in_query():
    http, tr, sess = _http([FakeResponse(200, {"content": [{"id": 1}], "last": True})])
    ent = _FakePostPaged(http, sess)
    ent.list(filter={"plan_status": "RELEASED"}, size=20, all=False)
    call = tr.calls[0]
    assert call["method"] == "POST"
    assert call["json"] == {"plan_status": "RELEASED"}  # filter 进 body
    assert call["params"] == {"page": "0", "size": "20"}  # 分页参进 query（不含 filter）
    assert "plan_status" not in call["params"]


def test_post_paged_multi_page_terminates_on_last():
    """多页 POST-body 翻页：有 last 按 last 终止，不按 total。"""
    http, tr, sess = _http([
        FakeResponse(200, {"content": [{"id": 1}], "last": False, "total": 999}),
        FakeResponse(200, {"content": [{"id": 2}], "last": False, "total": 999}),
        FakeResponse(200, {"content": [{"id": 3}], "last": True, "total": 999}),
    ])
    ent = _FakePostPaged(http, sess)
    page = ent.list(filter={}, size=1, all=True)
    assert [it["id"] for it in page.items] == [1, 2, 3]  # total=999 不影响停页
    assert len(tr.calls) == 3
    assert all(c["method"] == "POST" for c in tr.calls)


def test_post_paged_heuristic_terminates_on_short_page():
    """无 last 字段：满页(len==size)续翻、不满则末页（启发式终止）。"""
    http, tr, sess = _http([
        FakeResponse(200, {"content": [{"id": 1}, {"id": 2}]}),  # 满页 size=2 → 续
        FakeResponse(200, {"content": [{"id": 3}]}),             # 不满 → 末页
    ])
    ent = _FakePostPaged(http, sess)
    page = ent.list(filter={}, size=2, all=True)
    assert [it["id"] for it in page.items] == [1, 2, 3]
    assert len(tr.calls) == 2


def test_post_paged_single_page_when_not_all():
    http, tr, sess = _http([FakeResponse(200, {"content": [{"id": 1}, {"id": 2}], "last": False})])
    ent = _FakePostPaged(http, sess)
    page = ent.list(filter={}, size=2, all=False)
    assert len(tr.calls) == 1  # all=False 只取单页
    assert [it["id"] for it in page.items] == [1, 2]


# =========================================================
# PagedEntity._sub_list —— 任意子路径分页，复用 iterate_all
# =========================================================

def test_sub_list_single_page():
    http, tr, sess = _http([FakeResponse(200, {"content": [{"id": "i1"}], "last": True})])
    ent = _FakePaged(http, sess)
    page = ent.sub("/v2/api/tenants/10030/boms/B1/items", params={"q": "x"}, size=20, all=False)
    assert page.items == [{"id": "i1"}]
    assert tr.calls[0]["method"] == "GET"
    assert tr.calls[0]["url"].endswith("/boms/B1/items")
    assert tr.calls[0]["params"]["q"] == "x"
    assert tr.calls[0]["params"]["page"] == "0"


def test_sub_list_all_true_delegates_iterate_all():
    """all=True 委托 iterate_all：多页子路径翻页合并成单 Page。"""
    http, tr, sess = _http([
        FakeResponse(200, {"content": [{"id": "i1"}], "last": False}),
        FakeResponse(200, {"content": [{"id": "i2"}], "last": False}),
        FakeResponse(200, {"content": [{"id": "i3"}], "last": True}),
    ])
    ent = _FakePaged(http, sess)
    page = ent.sub("/v2/api/tenants/10030/boms/B1/items", params=None, size=1, all=True)
    assert [it["id"] for it in page.items] == ["i1", "i2", "i3"]
    assert len(tr.calls) == 3


def test_sub_list_truncated_marked_when_capped():
    """封顶早停 → truncated 标记（复用既有 iterate_all 的 max_pages 封顶语义）。"""
    # 构造恒 has_next 的多页：每页满 size=1 且无 last → 启发式恒续，靠 max_pages=3 封顶。
    responses = [FakeResponse(200, {"content": [{"id": i}]}) for i in range(5)]
    http, tr, sess = _http(responses)
    ent = _FakePaged(http, sess)
    # 用一个低封顶验证 truncated（通过 _sub_list 的 max_pages 形参或 iterate_all 默认）。
    page = ent.sub(
        "/v2/api/tenants/10030/boms/B1/items", params=None, size=1, all=True, max_pages=3
    )
    assert page.truncated is True
    assert len(page.items) == 3


# =========================================================
# 只读边界守护 —— 基座层 not hasattr 写方法
# =========================================================

def test_post_paged_no_write_methods():
    http, tr, sess = _http([])
    ent = _FakePostPaged(http, sess)
    for w in ("create", "update", "delete", "post_write", "save", "remove"):
        assert not hasattr(ent, w)


def test_paged_base_no_write_methods():
    http, tr, sess = _http([])
    ent = _FakePaged(http, sess)
    for w in ("create", "update", "delete", "post_write", "save", "remove"):
        assert not hasattr(ent, w)
