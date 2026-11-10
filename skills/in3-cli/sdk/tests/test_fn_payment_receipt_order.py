"""fn.payment_receipt_order（收付款单，simple-list-get 2pt，plan §6 行 770-779）。

顶层业务单据：NOT under company-codes/* → **不发 fncc header**（最接近 mm.supplier）。
Spring Page 响应（走标准 _list 分页，非裸 List）。金额/币种字段若在场按 sd companion 旁挂归一。

覆盖：list/get URL（/payment-receipt-orders/page 与 /{id}）、filter 白名单（account_id/ordered_by/
so_id/status）+ 未知 key fail-loud、status 多值透传、currency companion 在场旁挂/缺则不臆造、
不发 fncc header、只读边界。
"""
from dataclasses import dataclass, field

import pytest

from in3_client.auth import Session
from in3_client.config import Credentials
from in3_client.envelope import Page
from in3_client.filters import FilterKeyError
from in3_client.http import HttpClient, HttpError
from in3_client.entities.fn import PaymentReceiptOrderEntity


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
_BASE = "https://apiv3.industics.com/service/mom/fn/v2/api/tenants/10030"

_WRITE_METHODS = ("create", "update", "delete", "post", "put", "patch", "remove", "save")


def _wire(data_responses, **kw):
    sess = Session(_CRED, transport=FakeTransport([FakeResponse(200, _TOKEN)]))
    data_tr = FakeTransport(data_responses)
    http = HttpClient(sess, transport=data_tr)
    return PaymentReceiptOrderEntity(_CRED, sess, http, **kw), data_tr


def test_list_url_plural():
    ent, tr = _wire([FakeResponse(200, {"content": [{"id": "pro1"}], "last": True})])
    page = ent.list(all=False)
    assert isinstance(page, Page)
    assert page.items == [{"id": "pro1"}]
    assert tr.calls[0]["url"] == f"{_BASE}/payment-receipt-orders/page"


def test_list_filter_whitelist_passthrough():
    ent, tr = _wire([FakeResponse(200, {"content": [], "last": True})])
    ent.list(filter={"account_id": "acc-1", "ordered_by": "u-9", "so_id": "so-2"}, all=False)
    p = tr.calls[0]["params"]
    assert p["account_id"] == "acc-1"
    assert p["ordered_by"] == "u-9"
    assert p["so_id"] == "so-2"


def test_list_status_multi_passthrough():
    ent, tr = _wire([FakeResponse(200, {"content": [], "last": True})])
    ent.list(filter={"status": ["A", "B"]}, all=False)
    assert tr.calls[0]["params"]["status"] == ["A", "B"]


def test_list_unknown_filter_key_raises():
    ent, tr = _wire([FakeResponse(200, {"content": [], "last": True})])
    with pytest.raises(FilterKeyError):
        ent.list(filter={"bogus": "x"})


def test_does_not_send_company_code_header():
    # 顶层单据不在 company-codes/* 链路 → 任何请求都不该带 fncc header
    ent, tr = _wire([FakeResponse(200, {"content": [], "last": True})])
    ent.list(all=False)
    headers = tr.calls[0]["headers"] or {}
    assert "fncc" not in headers, f"不应注入 fncc header: {headers}"


def test_get_url():
    ent, tr = _wire([FakeResponse(200, {"id": "pro1", "document_no": "PRO-001"})])
    rec = ent.get("pro1")
    assert rec["document_no"] == "PRO-001"
    assert tr.calls[0]["url"] == f"{_BASE}/payment-receipt-orders/pro1"


def test_get_404_raises():
    ent, tr = _wire([FakeResponse(404, text="not found")])
    with pytest.raises(HttpError):
        ent.get("nope")


def test_currency_companion_when_present_and_index():
    # 金额/币种字段在场 + 注入 index → 旁挂 alpha companion（原 *_no 不动）
    ccy_index = {"156": "CNY", "840": "USD"}
    ent, tr = _wire(
        [FakeResponse(200, {"content": [
            {"id": "pro1", "local_currency_no": "156", "original_currency_no": "840"},
        ], "last": True})],
        currency_index=ccy_index,
    )
    it = ent.list(all=False).items[0]
    assert it["local_currency_no"] == "156"      # 原字段不动
    assert it["local_currency"] == "CNY"          # 旁挂 companion
    assert it["original_currency"] == "USD"


def test_no_currency_companion_when_field_absent():
    # 字段不在场 → 不臆造 companion（即便给了 index）
    ccy_index = {"156": "CNY"}
    ent, tr = _wire(
        [FakeResponse(200, {"content": [{"id": "pro1", "amount": 10}], "last": True})],
        currency_index=ccy_index,
    )
    it = ent.list(all=False).items[0]
    assert "local_currency" not in it
    assert it["amount"] == 10


def test_read_only():
    ent, _ = _wire([])
    for m in _WRITE_METHODS:
        assert not hasattr(ent, m), f"只读边界破：不应有 {m}"
