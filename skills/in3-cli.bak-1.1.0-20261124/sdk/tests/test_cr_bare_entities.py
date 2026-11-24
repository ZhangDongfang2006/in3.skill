"""#13 M2 cr 模块 bare-array 实体单测（直接实例化，不经 facade）。

覆盖 service_person（裸 List + query(*, q) 必填）/ fee_category（list-only 裸 List，
path 含 /page 但仍裸 list）/ work_log_category（list-only 裸 List）。

cr 模块结构性坑：端点是 app-prefix（/flsc/...）**非** /v2/api/tenants/<tid>/ 模板——
实体覆写 _list_path 时忽略 tenant_id 参数，返回固定 app-prefix 路径。
base = cred.base_url('cr') = api_host + /mom/cr（config 已支持，无需改 config）。

桩照 tests/test_entities_simple.py：FakeResponse / FakeTransport。
裸 List 走 #10 的 _list_bare/coerce_to_page，**不**经 envelope.normalize、**不**被 or {} 吞空。
"""
from dataclasses import dataclass, field

import pytest

from in3_client.auth import Session
from in3_client.config import Credentials
from in3_client.envelope import Page
from in3_client.entities.cr import (
    FeeCategoryEntity,
    ServicePersonEntity,
    WorkLogCategoryEntity,
)


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

_CR_BASE = "https://apiv3.industics.com/service/mom/cr"


def _wire(entity_cls, data_responses, **kw):
    from in3_client.http import HttpClient

    sess = Session(_CRED, transport=FakeTransport([FakeResponse(200, _TOKEN)]))
    data_tr = FakeTransport(data_responses)
    http = HttpClient(sess, transport=data_tr)
    return entity_cls(_CRED, sess, http, **kw), data_tr


# ---------- cr.service_person ----------

def test_service_person_list_wraps_bare_list_into_page():
    # 后端返裸 List<TenantUserVO>（非 Spring Page 信封）。
    ent, tr = _wire(ServicePersonEntity, [
        FakeResponse(200, [{"id": "u1", "username": "alice"}, {"id": "u2", "username": "bob"}]),
    ])
    page = ent.list()
    assert isinstance(page, Page)
    assert page.items == [{"id": "u1", "username": "alice"}, {"id": "u2", "username": "bob"}]
    assert page.page == 0
    assert page.total == 2
    assert page.has_next is False


def test_service_person_list_empty_bare_not_swallowed():
    # 空裸数组不被 or {} 吞成空 dict —— total=0 而非数据丢失。
    ent, tr = _wire(ServicePersonEntity, [FakeResponse(200, [])])
    page = ent.list()
    assert page.items == []
    assert page.total == 0


def test_service_person_list_app_prefix_path_not_tenant_templated():
    # cr 端点是 /flsc app-prefix，URL 里**不**出现 /v2/api/tenants/<tid>/。
    ent, tr = _wire(ServicePersonEntity, [FakeResponse(200, [])])
    ent.list()
    url = tr.calls[0]["url"]
    assert url.startswith(_CR_BASE + "/flsc")
    assert "/v2/api/tenants/" not in url
    assert tr.calls[0]["method"] == "GET"


def test_service_person_query_requires_q_fail_loud():
    # q 必填，缺则 fail-loud raise ValueError，绝不发空查询。
    ent, tr = _wire(ServicePersonEntity, [])
    with pytest.raises(ValueError):
        ent.query(q="")
    with pytest.raises(ValueError):
        ent.query(q=None)
    # 不打网络。
    assert tr.calls == []


def test_service_person_query_sends_q_and_wraps_bare_list():
    ent, tr = _wire(ServicePersonEntity, [
        FakeResponse(200, [{"id": "u9", "username": "zhang", "display_name": "张三"}]),
    ])
    page = ent.query(q="张")
    assert isinstance(page, Page)
    assert page.items[0]["display_name"] == "张三"
    assert page.total == 1
    assert tr.calls[0]["params"]["q"] == "张"
    assert tr.calls[0]["method"] == "GET"


# ---------- cr.fee_category（list-only） ----------

def test_fee_category_list_wraps_bare_list_despite_page_in_path():
    # path 含 /page 但返回裸 List —— 仍走 _list_bare，别被 path 名骗去当分页端点。
    ent, tr = _wire(FeeCategoryEntity, [
        FakeResponse(200, [{"id": "fc1", "code": "TRAVEL"}, {"id": "fc2", "code": "LABOR"}]),
    ])
    page = ent.list()
    assert page.items == [{"id": "fc1", "code": "TRAVEL"}, {"id": "fc2", "code": "LABOR"}]
    assert page.total == 2
    assert page.has_next is False
    assert tr.calls[0]["method"] == "GET"
    assert "/v2/api/tenants/" not in tr.calls[0]["url"]


def test_fee_category_has_no_get():
    # list-only —— 忠实不假装 get（照 sd.sales_order_item 的诚实约定）。
    ent, _ = _wire(FeeCategoryEntity, [])
    assert not hasattr(ent, "get")


# ---------- cr.work_log_category（list-only） ----------

def test_work_log_category_list_wraps_bare_list():
    ent, tr = _wire(WorkLogCategoryEntity, [
        FakeResponse(200, [{"id": "wl1", "name": "巡检"}]),
    ])
    page = ent.list()
    assert page.items == [{"id": "wl1", "name": "巡检"}]
    assert page.total == 1
    assert tr.calls[0]["method"] == "GET"
    assert "/v2/api/tenants/" not in tr.calls[0]["url"]


def test_work_log_category_has_no_get():
    ent, _ = _wire(WorkLogCategoryEntity, [])
    assert not hasattr(ent, "get")


# ---------- 只读边界守护 ----------

@pytest.mark.parametrize("cls", [ServicePersonEntity, FeeCategoryEntity, WorkLogCategoryEntity])
def test_cr_entities_no_write_methods(cls):
    ent, _ = _wire(cls, [])
    for w in ("create", "update", "delete", "post_write", "save", "remove"):
        assert not hasattr(ent, w)
