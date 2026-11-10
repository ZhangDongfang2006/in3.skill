"""filter_key 校验（PRD §A / :50）：实体只接受 __schema 声明的 filter key，未声明 key fail-loud。

后端对未声明的 query key 静默忽略（返全量）→ agent 以为筛过其实没筛。SDK 在 list() 入口对
有 exhaustive filter_keys 的 4 实体（md.material / mm.supplier / mm.purchase_order /
sd.sales_order_item）做白名单校验：未声明 key → raise FilterKeyError，且校验先于任何网络调用。
md.material 的 field_a..field_av / sd 的 column_a..column_u 扩展字段按 pattern 放行。
"""
from dataclasses import dataclass, field

import pytest

from in3_client.auth import Session
from in3_client.config import Credentials
from in3_client.filters import FilterKeyError
from in3_client.http import HttpClient
from in3_client.entities.md import MaterialEntity
from in3_client.entities.mm import SupplierEntity, PurchaseOrderEntity
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
_EMPTY_PAGE = {"content": [], "last": True}


def _wire(entity_cls, **kw):
    """data transport 用空列表 —— 校验若先 raise 则一条都不会 pop（断言不打网络）。"""
    sess = Session(_CRED, transport=FakeTransport([FakeResponse(200, _TOKEN)]))
    data_tr = FakeTransport([FakeResponse(200, _EMPTY_PAGE)])
    http = HttpClient(sess, transport=data_tr)
    return entity_cls(_CRED, sess, http, **kw), data_tr


# ---------- 未声明 key → fail-loud，且校验先于网络 ----------

def test_material_unknown_key_raises_before_network():
    ent, tr = _wire(MaterialEntity)
    with pytest.raises(FilterKeyError) as ei:
        ent.list(filter={"materail_no": "B-100"})  # typo: materail
    assert "materail_no" in ei.value.unknown
    assert tr.calls == []  # 校验先于任何 HTTP —— 没打网络


def test_supplier_unknown_key_raises():
    ent, tr = _wire(SupplierEntity)
    with pytest.raises(FilterKeyError):
        ent.list(filter={"vendor_name": "x"})  # 应为 name
    assert tr.calls == []


def test_po_unknown_key_raises():
    ent, tr = _wire(PurchaseOrderEntity)
    with pytest.raises(FilterKeyError):
        ent.list(filter={"material_id": "m1"})  # PO 用 material_ids（复数 multi），单数是未声明
    assert tr.calls == []


def test_soi_unknown_key_raises():
    ent, tr = _wire(SalesOrderItemEntity)
    with pytest.raises(FilterKeyError):
        ent.list(filter={"material_ids": ["m1"]})  # SOI 用单数 material_id
    assert tr.calls == []


# ---------- 合法 key 放行 ----------

def test_material_valid_key_passes():
    ent, tr = _wire(MaterialEntity)
    page = ent.list(filter={"material_no": "B-100"})
    assert page.items == []
    assert tr.calls and tr.calls[0]["params"]["material_no"] == "B-100"


def test_po_valid_material_ids_passes():
    ent, tr = _wire(PurchaseOrderEntity)
    ent.list(filter={"material_ids": ["m1"]}, all=False)
    assert tr.calls  # 打了网络（key 合法）


def test_soi_valid_key_passes():
    ent, tr = _wire(SalesOrderItemEntity)
    ent.list(filter={"material_id": "m1", "from_ordered_at": "2026-05-01T00:00:00"})
    assert tr.calls


# ---------- 扩展字段按 pattern 放行（不写死）----------

def test_material_extension_field_allowed():
    ent, tr = _wire(MaterialEntity)
    ent.list(filter={"field_a": "1", "field_av": "2"})  # field_a..field_av
    assert tr.calls


def test_soi_extension_column_allowed():
    ent, tr = _wire(SalesOrderItemEntity)
    ent.list(filter={"column_a": "x"})  # column_a..column_u
    assert tr.calls


# ---------- 错误信息可诊断 ----------

def test_error_message_names_unknown_key_and_entity():
    ent, _ = _wire(MaterialEntity)
    with pytest.raises(FilterKeyError) as ei:
        ent.list(filter={"bogus": 1, "material_no": "ok"})
    msg = str(ei.value)
    assert "bogus" in msg and "md.material" in msg
    assert "material_no" not in ei.value.unknown  # 合法 key 不进 unknown
