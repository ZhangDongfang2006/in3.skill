"""#13 M2 pp 模块 bare-array 实体单测（直接实例化，不经 facade）。

覆盖 mrp_history（flat List，有 get(id)，filterless）/ mrp_rule（flat List，include_items
是 backend-native 真 query param 直接转发**不**做 client-side fan-out，路径双 /pp/ 段照字面）。

pp 是 tenant-templated（/v2/api/tenants/<tid>/）。flat List 走 #10 的 _list_bare/coerce_to_page，
不经 normalize、不被 or {} 吞空。mrp_rule 的 include_items 直接 ?include_items=true 转发。
"""
from dataclasses import dataclass, field

import pytest

from in3_client.auth import Session
from in3_client.config import Credentials
from in3_client.envelope import Page
from in3_client.http import HttpClient, HttpError
from in3_client.entities.pp import MrpHistoryEntity, MrpRuleEntity


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
        self.calls.append({"method": method, "url": url, "params": params, "json": kw.get("json")})
        return self.responses.pop(0)


_CRED = Credentials(
    api_host="https://apiv3.industics.com/service",
    tenant_domain="indx",
    username="corp:zhuzheng@indx",
    encrypted_password="AESCIPHER==",
    alias="zhuzheng",
)
_TOKEN = {"access_token": "jwt", "tenant_id": "10030", "tenant_domain": "indx", "user_id": "u-42"}

_PP_BASE = "https://apiv3.industics.com/service/mom/pp"


def _wire(entity_cls, data_responses, **kw):
    sess = Session(_CRED, transport=FakeTransport([FakeResponse(200, _TOKEN)]))
    data_tr = FakeTransport(data_responses)
    http = HttpClient(sess, transport=data_tr)
    return entity_cls(_CRED, sess, http, **kw), data_tr


# ---------- pp.mrp_history ----------

def test_mrp_history_list_wraps_flat_list():
    ent, tr = _wire(MrpHistoryEntity, [
        FakeResponse(200, [{"id": "h1", "run_at": "2026-01-01"}, {"id": "h2"}]),
    ])
    page = ent.list()
    assert isinstance(page, Page)
    assert page.items[0]["id"] == "h1"
    assert page.total == 2
    assert page.has_next is False
    assert tr.calls[0]["method"] == "GET"


def test_mrp_history_list_empty_flat_not_swallowed():
    ent, tr = _wire(MrpHistoryEntity, [FakeResponse(200, [])])
    page = ent.list()
    assert page.items == []
    assert page.total == 0


def test_mrp_history_list_tenant_templated_url():
    ent, tr = _wire(MrpHistoryEntity, [FakeResponse(200, [])])
    ent.list()
    assert tr.calls[0]["url"].startswith(_PP_BASE + "/v2/api/tenants/10030/")


def test_mrp_history_get_single_record():
    # mrp-history 有真 get(id)（区别于纯 list-only）。
    ent, tr = _wire(MrpHistoryEntity, [FakeResponse(200, {"id": "h1", "run_at": "2026-01-01"})])
    rec = ent.get("h1")
    assert rec["id"] == "h1"
    assert tr.calls[0]["url"].endswith("/h1")
    assert tr.calls[0]["method"] == "GET"


def test_mrp_history_get_404_raises():
    # id 不存在 → 按 M0 404 语义 raise HttpError（不静默返 {}）。
    ent, _ = _wire(MrpHistoryEntity, [FakeResponse(404, text="not found")])
    with pytest.raises(HttpError):
        ent.get("nope")


def test_mrp_history_list_is_filterless():
    # 签名保持 filterless（零 @RequestParam）——不接受暗示可过滤的 kwargs。
    import inspect

    sig = inspect.signature(MrpHistoryEntity.list)
    params = [p for p in sig.parameters if p != "self"]
    assert "filter" not in params


# ---------- pp.mrp_rule ----------

def test_mrp_rule_list_wraps_flat_list():
    ent, tr = _wire(MrpRuleEntity, [
        FakeResponse(200, [{"id": "r1", "rule_name": "默认"}]),
    ])
    page = ent.list()
    assert isinstance(page, Page)
    assert page.items[0]["rule_name"] == "默认"
    assert page.total == 1
    assert page.has_next is False


def test_mrp_rule_double_pp_path():
    # 路径有 double /pp/ 段照字面 hardcode（base 已含 /mom/pp，path 再带 /pp/mrp-rules）。
    ent, tr = _wire(MrpRuleEntity, [FakeResponse(200, [])])
    ent.list()
    url = tr.calls[0]["url"]
    assert url.startswith(_PP_BASE + "/v2/api/tenants/10030/")
    assert "/pp/mrp-rules" in url


def test_mrp_rule_include_items_forwarded_as_query_param_no_fanout():
    # include_items 是 backend-native 真 query param → 直接 ?include_items=true，**不**额外 fan-out。
    ent, tr = _wire(MrpRuleEntity, [FakeResponse(200, [{"id": "r1"}])])
    ent.list(include_items=True)
    # 单次请求（无 client-side fan-out 的多次 sub-fetch）。
    assert len(tr.calls) == 1
    assert tr.calls[0]["params"].get("include_items") == "true"


def test_mrp_rule_include_items_false_omits_param():
    ent, tr = _wire(MrpRuleEntity, [FakeResponse(200, [])])
    ent.list(include_items=False)
    assert len(tr.calls) == 1
    assert "include_items" not in (tr.calls[0]["params"] or {})


# ---------- 只读边界守护 ----------

@pytest.mark.parametrize("cls", [MrpHistoryEntity, MrpRuleEntity])
def test_pp_entities_no_write_methods(cls):
    ent, _ = _wire(cls, [])
    for w in ("create", "update", "delete", "post_write", "save", "remove"):
        assert not hasattr(ent, w)
