"""mm M1/M2 entity 单测（issue #12 info_record/rfq + #13 bom/currency）。

直接实例化 entity（FakeTransport，不经 facade）。覆盖：
- info_record（simple-list-get）：list/get URL（注意 /pages 复数 vs /page；info-record list 是 /page）、
  filter 透传、get 单条、only_latest bool 透传、404 抛错、只读边界。
- rfq（simple-list-get）：list URL 是 /pages（复数）、get 是 /<id>（单数 path 段）、
  multi filter rfq_categories/statuses 走 repeated query（list 值透传）、只读边界。
- bom（bare-array list-only + 特殊 get）：list 裸数组包 Page（不被 normalize 吞）、
  material_id 必填缺则 ValueError（不打网络）、get(material_id) 走 /boms/materials/<id> 返结构树、
  date filter 透传、只读边界。
- currency（bare-array、无 filter、query-param get）：list /mdm/currency/all/available 裸数组包 Page、
  list 无参、get(currency_no) 走 /mdm/currency/detail?currency_no=<no>（query param 不是 path 段）、
  不复用 md.CurrencyEntity（端点不同）、只读边界。

桩照 tests/test_entities_simple.py / test_m0_post_paged_bare_coerce.py。
"""
from dataclasses import dataclass, field

import pytest

from in3_client.auth import Session
from in3_client.config import Credentials
from in3_client.envelope import Page
from in3_client.http import HttpClient, HttpError
from in3_client.entities.mm import (
    BomEntity,
    CurrencyEntity,
    InfoRecordEntity,
    RfqEntity,
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
        self.calls.append(
            {"method": method, "url": url, "params": params, "json": kw.get("json")}
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

_MM_BASE = "https://apiv3.industics.com/service/mom/mm/v2/api/tenants/10030"


def _wire(entity_cls, data_responses):
    sess = Session(_CRED, transport=FakeTransport([FakeResponse(200, _TOKEN)]))
    data_tr = FakeTransport(data_responses)
    http = HttpClient(sess, transport=data_tr)
    return entity_cls(_CRED, sess, http), data_tr


_WRITE_METHODS = ("create", "update", "delete", "save", "remove", "post_write")


# ====================== mm.info_record ======================

def test_info_record_list_url_is_info_records_page():
    ent, tr = _wire(InfoRecordEntity, [FakeResponse(200, {"content": [{"id": "ir1"}], "last": True})])
    page = ent.list()
    assert isinstance(page, Page)
    assert page.items == [{"id": "ir1"}]
    assert tr.calls[0]["url"] == _MM_BASE + "/spm/info-records/page"


def test_info_record_get_url_single_path_segment():
    ent, tr = _wire(InfoRecordEntity, [FakeResponse(200, {"id": "ir1", "info_record_no": "IR-001"})])
    rec = ent.get("ir1")
    assert rec["info_record_no"] == "IR-001"
    assert tr.calls[0]["url"] == _MM_BASE + "/spm/info-records/ir1"


def test_info_record_list_passes_single_value_filter():
    ent, tr = _wire(InfoRecordEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(filter={"supplier_id": "S-9", "only_latest": True})
    p = tr.calls[0]["params"]
    assert p["supplier_id"] == "S-9"
    assert p["only_latest"] is True  # bool 透传不强转


def test_info_record_unknown_filter_key_raises():
    ent, _ = _wire(InfoRecordEntity, [FakeResponse(200, {"content": [], "last": True})])
    with pytest.raises(ValueError):
        ent.list(filter={"not_a_real_key": "x"})


def test_info_record_get_404_raises():
    ent, _ = _wire(InfoRecordEntity, [FakeResponse(404, text="not found")])
    with pytest.raises(HttpError):
        ent.get("nope")


def test_info_record_no_write_methods():
    ent, _ = _wire(InfoRecordEntity, [])
    for w in _WRITE_METHODS:
        assert not hasattr(ent, w)


# ====================== mm.rfq ======================

def test_rfq_list_url_is_pages_plural():
    ent, tr = _wire(RfqEntity, [FakeResponse(200, {"content": [{"id": "r1"}], "last": True})])
    ent.list()
    # 注意：list 端点是 /pages（复数）走 POST-body，区别于 info-record 的 GET /page
    # live parity 校正 2026-06-03：GET 触发后端 500，CLI rfq.js 用 postPage（POST），故 SDK 改 POST。
    assert tr.calls[0]["url"] == _MM_BASE + "/spm/request-for-quotations/pages"
    assert tr.calls[0]["method"] == "POST"
    # page/size 进 query，不进 body
    assert tr.calls[0]["params"]["page"] == "0"


def test_rfq_get_url_single_id_path_segment():
    ent, tr = _wire(RfqEntity, [FakeResponse(200, {"id": "r1", "rfq_no": "RFQ-7"})])
    rec = ent.get("r1")
    assert rec["rfq_no"] == "RFQ-7"
    # get 是 /<id> 单数 path 段（不是 /pages/<id>）
    assert tr.calls[0]["url"] == _MM_BASE + "/spm/request-for-quotations/r1"


def test_rfq_multi_filter_categories_and_statuses_pass_as_list():
    ent, tr = _wire(RfqEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(filter={"rfq_categories": ["A", "B"], "statuses": ["OPEN", "CLOSED"]})
    # POST-body 分页（live parity 校正）：filter 进 body JSON 数组，不再是 GET repeated query。
    body = tr.calls[0]["json"]
    assert body["rfq_categories"] == ["A", "B"]
    assert body["statuses"] == ["OPEN", "CLOSED"]
    # page/size 在 query、不在 body
    assert "page" not in body and tr.calls[0]["params"]["page"] == "0"


def test_rfq_unknown_filter_key_raises():
    ent, _ = _wire(RfqEntity, [FakeResponse(200, {"content": [], "last": True})])
    with pytest.raises(ValueError):
        ent.list(filter={"bogus": 1})


def test_rfq_no_write_methods():
    ent, _ = _wire(RfqEntity, [])
    for w in _WRITE_METHODS:
        assert not hasattr(ent, w)


# ====================== mm.bom (bare-array, required material_id) ======================

def test_bom_list_requires_material_id_raises_without_network():
    # 缺 material_id → fail-loud ValueError，绝不打网络（responses 为空，若打网会 IndexError）
    ent, tr = _wire(BomEntity, [])
    with pytest.raises(ValueError):
        ent.list()
    assert tr.calls == []  # 没有任何网络调用


def test_bom_list_bare_array_wrapped_to_page_not_swallowed():
    ent, tr = _wire(BomEntity, [FakeResponse(200, [{"id": "b1"}, {"id": "b2"}])])
    page = ent.list(material_id="M-100")
    assert isinstance(page, Page)
    assert page.items == [{"id": "b1"}, {"id": "b2"}]  # 裸数组未被 normalize 吞
    assert page.total == 2
    assert page.has_next is False
    assert tr.calls[0]["url"] == _MM_BASE + "/boms/list"
    assert tr.calls[0]["params"]["material_id"] == "M-100"


def test_bom_list_passes_extra_filter():
    ent, tr = _wire(BomEntity, [FakeResponse(200, [])])
    ent.list(material_id="M-1", filter={"bom_name": "主BOM", "from_created_date": "2026-01-01"})
    p = tr.calls[0]["params"]
    assert p["material_id"] == "M-1"
    assert p["bom_name"] == "主BOM"
    assert p["from_created_date"] == "2026-01-01"


def test_bom_get_url_is_boms_materials_material_id():
    ent, tr = _wire(BomEntity, [FakeResponse(200, {"material_id": "M-5", "components": [{"x": 1}]})])
    tree = ent.get("M-5")
    assert tree["components"] == [{"x": 1}]
    # get 走 /boms/materials/<material_id>（非 /boms/<id>）
    assert tr.calls[0]["url"] == _MM_BASE + "/boms/materials/M-5"


def test_bom_get_404_raises():
    # id 不存在 → 按 M0 404 语义 raise HttpError（不静默返 {}）。get 收 material_id。
    ent, _ = _wire(BomEntity, [FakeResponse(404, text="not found")])
    with pytest.raises(HttpError):
        ent.get("nope")


def test_bom_no_write_methods():
    ent, _ = _wire(BomEntity, [])
    for w in _WRITE_METHODS:
        assert not hasattr(ent, w)


# ====================== mm.currency (bare-array, no filter, query-param get) ======================

def test_currency_list_url_is_available_bare_array():
    ent, tr = _wire(CurrencyEntity, [FakeResponse(200, [{"currency_no": "156"}, {"currency_no": "840"}])])
    page = ent.list()
    assert isinstance(page, Page)
    assert [c["currency_no"] for c in page.items] == ["156", "840"]
    assert page.total == 2
    assert page.has_next is False
    # mm 专属端点（区别于 md.currency 的 /mdm/currencies/page）
    assert tr.calls[0]["url"] == _MM_BASE + "/mdm/currency/all/available"


def test_currency_list_takes_no_filter_args():
    # list 无 filter 参数（无 filter_keys）——签名不暴露 filter
    ent, tr = _wire(CurrencyEntity, [FakeResponse(200, [])])
    page = ent.list()
    assert page.items == []
    # 不接受 filter kwarg
    import inspect
    sig = inspect.signature(ent.list)
    assert "filter" not in sig.parameters


def test_currency_get_url_is_detail_query_param():
    ent, tr = _wire(CurrencyEntity, [FakeResponse(200, {"currency_no": "156", "currency_code": "CNY"})])
    rec = ent.get("156")
    assert rec["currency_code"] == "CNY"
    # get 走 query-param /mdm/currency/detail?currency_no=156（不是 path 段）
    assert tr.calls[0]["url"] == _MM_BASE + "/mdm/currency/detail"
    assert tr.calls[0]["params"]["currency_no"] == "156"


def test_currency_is_not_md_currency_entity():
    from in3_client.entities.md import CurrencyEntity as MdCurrency
    assert CurrencyEntity is not MdCurrency


def test_currency_get_404_raises():
    # currency_no 不存在 → 按 M0 404 语义 raise HttpError（不静默返 {}）。get 收 currency_no。
    ent, _ = _wire(CurrencyEntity, [FakeResponse(404, text="not found")])
    with pytest.raises(HttpError):
        ent.get("999")


def test_currency_no_write_methods():
    ent, _ = _wire(CurrencyEntity, [])
    for w in _WRITE_METHODS:
        assert not hasattr(ent, w)
