"""sd.delivery_receipt（收货单 header）单测（plan §6 行 631-640，simple-list-get 2pt）。

直接实例化 entity（FakeTransport 桩，不经 facade）。覆盖：
  - list/get URL（/delivery-receipts/page 与 /{id}）
  - company_id 必填：缺 company → raise DeliveryReceiptValidationError（绝不打网络，mirror CLI VALIDATION exit）
  - get 不需要 company
  - account→account_id 映射、so_id/receipt_no 透传、receipt_status 多值透传
  - receipt_date_from/to（DATE）透传
  - filter dict 白名单 + 未知 key fail-loud
  - 只读边界
"""
from dataclasses import dataclass, field

import pytest

from in3_client.auth import Session
from in3_client.config import Credentials
from in3_client.envelope import Page
from in3_client.filters import FilterKeyError
from in3_client.http import HttpClient, HttpError
from in3_client.entities.sd import DeliveryReceiptEntity, DeliveryReceiptValidationError


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
        self.calls.append({"method": method, "url": url, "params": params, "headers": headers})
        return self.responses.pop(0)


_CRED = Credentials(
    api_host="https://apiv3.industics.com/service",
    tenant_domain="indx",
    username="corp:zhuzheng@indx",
    encrypted_password="AESCIPHER==",
    alias="zhuzheng",
)
_TOKEN = {"access_token": "jwt", "tenant_id": "10030", "tenant_domain": "indx", "user_id": "u-42"}
_BASE = "https://apiv3.industics.com/service/mom/sd/v2/api/tenants/10030"

_WRITE_METHODS = ("create", "update", "delete", "post", "put", "patch", "remove", "save")


def _wire(data_responses):
    sess = Session(_CRED, transport=FakeTransport([FakeResponse(200, _TOKEN)]))
    data_tr = FakeTransport(data_responses)
    http = HttpClient(sess, transport=data_tr)
    return DeliveryReceiptEntity(_CRED, sess, http), data_tr


def test_list_url_plural():
    ent, tr = _wire([FakeResponse(200, {"content": [{"id": "dr1"}], "last": True})])
    page = ent.list(company="C-1", all=False)
    assert isinstance(page, Page)
    assert page.items == [{"id": "dr1"}]
    assert tr.calls[0]["url"] == f"{_BASE}/delivery-receipts/page"


def test_list_requires_company_raises_before_network():
    # 缺 company → 校验失败先抛（绝不打网络）：无响应可弹，若打网络会 IndexError
    ent, tr = _wire([])
    with pytest.raises(DeliveryReceiptValidationError):
        ent.list()
    assert tr.calls == []


def test_list_company_maps_to_company_id():
    ent, tr = _wire([FakeResponse(200, {"content": [], "last": True})])
    ent.list(company="C-9", all=False)
    assert tr.calls[0]["params"]["company_id"] == "C-9"


def test_list_account_maps_to_account_id():
    ent, tr = _wire([FakeResponse(200, {"content": [], "last": True})])
    ent.list(company="C-1", account="acc-7", all=False)
    p = tr.calls[0]["params"]
    assert p["account_id"] == "acc-7"
    assert "account" not in p


def test_list_so_id_and_receipt_no_passthrough():
    ent, tr = _wire([FakeResponse(200, {"content": [], "last": True})])
    ent.list(company="C-1", so_id="so9", receipt_no="DR-001", all=False)
    p = tr.calls[0]["params"]
    assert p["so_id"] == "so9"
    assert p["receipt_no"] == "DR-001"


def test_list_receipt_status_multi_passthrough():
    ent, tr = _wire([FakeResponse(200, {"content": [], "last": True})])
    ent.list(company="C-1", receipt_status=["A", "F"], all=False)
    assert tr.calls[0]["params"]["receipt_status"] == ["A", "F"]


def test_list_receipt_date_filter_passthrough():
    ent, tr = _wire([FakeResponse(200, {"content": [], "last": True})])
    ent.list(
        company="C-1",
        filter={"receipt_date_from": "2026-05-01", "receipt_date_to": "2026-05-31"},
        all=False,
    )
    p = tr.calls[0]["params"]
    assert p["receipt_date_from"] == "2026-05-01"
    assert p["receipt_date_to"] == "2026-05-31"


def test_list_unknown_filter_key_raises():
    ent, tr = _wire([FakeResponse(200, {"content": [], "last": True})])
    with pytest.raises(FilterKeyError):
        ent.list(company="C-1", filter={"bogus": "x"})


def test_get_url_no_company_needed():
    ent, tr = _wire([FakeResponse(200, {"id": "dr1", "receipt_no": "DR-001"})])
    rec = ent.get("dr1")
    assert rec["receipt_no"] == "DR-001"
    assert tr.calls[0]["url"] == f"{_BASE}/delivery-receipts/dr1"


def test_get_404_raises():
    ent, tr = _wire([FakeResponse(404, text="not found")])
    with pytest.raises(HttpError):
        ent.get("nope")


def test_read_only():
    ent, _ = _wire([])
    for m in _WRITE_METHODS:
        assert not hasattr(ent, m), f"只读边界破：不应有 {m}"
