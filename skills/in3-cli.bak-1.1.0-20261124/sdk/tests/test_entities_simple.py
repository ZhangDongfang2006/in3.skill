"""#3 三个简单 entity 单测：md.material / mm.supplier / sd.sales_order_item。

近乎同构：list 走 http.get_page（普通 GET）+ pagination；md.material/mm.supplier 有 get。
sd.sales_order_item 仅 list（后端无 /{id}，忠实不假装），币种字段经 normalize_currency 归一。
覆盖：envelope 多形 unwrap、total<len 置 None、all=True 终止、.get 404 抛错、币种归一。
"""
from dataclasses import dataclass, field

import pytest

from in3_client.auth import Session
from in3_client.config import Credentials
from in3_client.envelope import Page
from in3_client.http import HttpClient, HttpError
from in3_client.entities.md import MaterialEntity
from in3_client.entities.mm import SupplierEntity
from in3_client.entities.sd import SalesOrderItemEntity


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
        self.calls.append({"method": method, "url": url, "params": params})
        return self.responses.pop(0)


_CRED = Credentials(
    api_host="https://apiv3.industics.com/service",
    tenant_domain="indx",
    username="corp:zhuzheng@indx",
    encrypted_password="AESCIPHER==",
    alias="zhuzheng",
)
_TOKEN = {"access_token": "jwt", "tenant_id": "10030", "tenant_domain": "indx", "user_id": "u-42"}


def _wire(entity_cls, data_responses, **kw):
    sess = Session(_CRED, transport=FakeTransport([FakeResponse(200, _TOKEN)]))
    data_tr = FakeTransport(data_responses)
    http = HttpClient(sess, transport=data_tr)
    return entity_cls(_CRED, sess, http, **kw), data_tr


# ---------- md.material ----------

def test_material_list_url_and_records_envelope():
    ent, tr = _wire(MaterialEntity, [FakeResponse(200, {"records": [{"id": "m1"}], "last": True})])
    page = ent.list()
    assert isinstance(page, Page)
    assert page.items == [{"id": "m1"}]  # records 形也能 unwrap
    assert tr.calls[0]["url"] == (
        "https://apiv3.industics.com/service/mom/md/v2/api/tenants/10030/mdm/materials/page"
    )


def test_material_total_below_len_is_none():
    ent, tr = _wire(MaterialEntity, [FakeResponse(200, {"content": [{"id": "a"}, {"id": "b"}], "total": 0})])
    page = ent.list(all=False)
    assert page.total is None


def test_material_get_single_record():
    ent, tr = _wire(MaterialEntity, [FakeResponse(200, {"id": "m1", "material_name": "螺栓"})])
    rec = ent.get("m1")
    assert rec["material_name"] == "螺栓"
    assert tr.calls[0]["url"].endswith("/mdm/materials/m1")


def test_material_get_404_raises_not_empty_dict():
    ent, tr = _wire(MaterialEntity, [FakeResponse(404, text="not found")])
    with pytest.raises(HttpError):
        ent.get("nope")


def test_material_list_passes_filter():
    ent, tr = _wire(MaterialEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(filter={"material_no": "B-100"})
    assert tr.calls[0]["params"]["material_no"] == "B-100"


# ---------- mm.supplier ----------

def test_supplier_list_url_no_page_suffix():
    ent, tr = _wire(SupplierEntity, [FakeResponse(200, {"content": [{"id": "s1"}], "last": True})])
    ent.list()
    # /srm/suppliers 无 /page 后缀
    assert tr.calls[0]["url"] == (
        "https://apiv3.industics.com/service/mom/mm/v2/api/tenants/10030/srm/suppliers"
    )


def test_supplier_get_url():
    ent, tr = _wire(SupplierEntity, [FakeResponse(200, {"id": "s1", "name": "供应商A"})])
    rec = ent.get("s1")
    assert rec["name"] == "供应商A"
    assert tr.calls[0]["url"].endswith("/srm/suppliers/s1")


def test_supplier_all_true_paginates_until_last():
    ent, tr = _wire(SupplierEntity, [
        FakeResponse(200, {"content": [{"id": "s1"}], "last": False}),
        FakeResponse(200, {"content": [{"id": "s2"}], "last": True}),
    ])
    page = ent.list(size=1)
    assert [it["id"] for it in page.items] == ["s1", "s2"]


# ---------- sd.sales_order_item ----------

def test_soi_list_url():
    ent, tr = _wire(SalesOrderItemEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list()
    assert tr.calls[0]["url"] == (
        "https://apiv3.industics.com/service/mom/sd/v2/api/tenants/10030/sales-orders/items/page"
    )


def test_soi_has_no_get_method():
    # 后端无 /{id}——忠实不暴露 .get（不假装）
    ent, _ = _wire(SalesOrderItemEntity, [])
    assert not hasattr(ent, "get")


def test_soi_normalizes_currency_field_when_dict_given():
    # 真实字段 local_currency_no/original_currency_no = 数值 ISO "156"。
    # 非破坏性：原 *_no 字段不动，旁挂去掉 _no 的 alpha companion。
    ccy_index = {"156": "CNY", "CNY": "CNY", "840": "USD"}
    ent, tr = _wire(
        SalesOrderItemEntity,
        [FakeResponse(200, {"content": [
            {"id": "soi1", "local_currency_no": "156", "original_currency_no": "840", "amount": 100},
        ], "last": True})],
        currency_index=ccy_index,
    )
    page = ent.list()
    it = page.items[0]
    assert it["local_currency_no"] == "156"        # 原字段不动
    assert it["local_currency"] == "CNY"           # 旁挂 alpha companion
    assert it["original_currency_no"] == "840"
    assert it["original_currency"] == "USD"
    assert it["amount"] == 100                     # 金额不动


def test_soi_without_currency_index_passes_through():
    ent, tr = _wire(
        SalesOrderItemEntity,
        [FakeResponse(200, {"content": [{"id": "soi1", "local_currency_no": "156"}], "last": True})],
    )
    page = ent.list()
    # 无字典则原样（不炸），不旁挂 companion
    assert page.items[0]["local_currency_no"] == "156"
    assert "local_currency" not in page.items[0]
