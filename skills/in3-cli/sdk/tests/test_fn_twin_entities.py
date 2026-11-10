"""#15 M4 fn 双轨实体单测（直接实例化，不经 facade）。

覆盖 payment_receipt / fapiao 的 module=ar|ap 端点分叉 + fncc header 注入 +
posting_period REQUIRED（payment_receipt）/ OPTIONAL（fapiao）校验 + 只读边界。

双轨误发守护（核心 AC）：fncc header 只在这两个实体注入；同 fn 模块的 company_code /
posting_period（M2 已落地）请求 **不含** fncc header。

端点和 `fncc` header 已于 2026-09-29 对 production frontend 与 live API 校正；测试钉死完整
路径、module 分叉、header 注入和参数校验，避免再次退回旧的 `/apar/company-codes/*` 路径。
"""
from dataclasses import dataclass, field

import pytest

from in3_client.auth import Session
from in3_client.config import Credentials
from in3_client.envelope import Page
from in3_client.entities.fn import (
    CompanyCodeEntity,
    FapiaoEntity,
    PaymentReceiptEntity,
    PaymentReceiptValidationError,
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
            {"method": method, "url": url, "headers": headers, "params": params, "json": kw.get("json")}
        )
        return self.responses.pop(0)


_CRED = Credentials(
    api_host="https://apiv3.industics.com/service",
    tenant_domain="indx",
    username="corp:zhuzheng@indx",
    encrypted_password="AESCIPHER==",
    alias="zhuzheng",
    default_company_code_id="CC-DEFAULT",
)
_CRED_NO_CC = Credentials(
    api_host="https://apiv3.industics.com/service",
    tenant_domain="indx",
    username="corp:zhuzheng@indx",
    encrypted_password="AESCIPHER==",
    alias="zhuzheng",
)
_TOKEN = {"access_token": "jwt", "tenant_id": "10030", "tenant_domain": "indx", "user_id": "u-42"}
_FN_BASE = "https://apiv3.industics.com/service/mom/fn"

# payment_receipt 的两个 REQUIRED posting_period filter（每次合法 list 都得带）。
_PP = {"from_posting_period_id": "pp1", "to_posting_period_id": "pp9"}

# Spring Page 响应壳（带 content/last 让 normalize 正常出 Page）。
def _page(items):
    return {"content": items, "totalElements": len(items), "last": True}


def _wire(entity_cls, data_responses, cred=_CRED, currency_index=None):
    sess = Session(cred, transport=FakeTransport([FakeResponse(200, _TOKEN)]))
    data_tr = FakeTransport(data_responses)
    from in3_client.http import HttpClient
    http = HttpClient(sess, transport=data_tr)
    if currency_index is not None:
        return entity_cls(cred, sess, http, currency_index=currency_index), data_tr
    return entity_cls(cred, sess, http), data_tr


# ---------- payment_receipt：module 分叉端点 ----------

def test_payment_receipt_list_ar_endpoint_segment():
    ent, tr = _wire(PaymentReceiptEntity, [FakeResponse(200, _page([{"id": "r1"}]))])
    page = ent.list(module="ar", filter=dict(_PP))
    assert isinstance(page, Page)
    url = tr.calls[0]["url"]
    assert url.endswith("/v2/api/tenants/10030/company-codes/payment-receipts/receipts/page")
    assert tr.calls[0]["method"] == "GET"


def test_payment_receipt_list_ap_endpoint_segment():
    ent, tr = _wire(PaymentReceiptEntity, [FakeResponse(200, _page([]))])
    ent.list(module="ap", filter=dict(_PP))
    url = tr.calls[0]["url"]
    assert url.endswith("/v2/api/tenants/10030/company-codes/payment-receipts/payments/page")


def test_payment_receipt_get_ar_path_id():
    ent, tr = _wire(PaymentReceiptEntity, [FakeResponse(200, {"id": "r1"})])
    rec = ent.get("r1", module="ar")
    assert rec["id"] == "r1"
    assert tr.calls[0]["url"].endswith("/v2/api/tenants/10030/company-codes/payment-receipts/receipts/r1")


def test_payment_receipt_get_ap_path_id():
    ent, tr = _wire(PaymentReceiptEntity, [FakeResponse(200, {"id": "p1"})])
    ent.get("p1", module="ap")
    assert tr.calls[0]["url"].endswith("/v2/api/tenants/10030/company-codes/payment-receipts/payments/p1")


def test_payment_receipt_module_missing_fail_loud_no_network():
    ent, tr = _wire(PaymentReceiptEntity, [])  # 无响应 → 一旦打网络就 IndexError
    with pytest.raises(PaymentReceiptValidationError):
        ent.list(filter=dict(_PP))  # module 缺失
    assert tr.calls == []  # client-side 抛错，不打网络


def test_payment_receipt_module_invalid_fail_loud_no_network():
    ent, tr = _wire(PaymentReceiptEntity, [])
    with pytest.raises(PaymentReceiptValidationError):
        ent.list(module="xx", filter=dict(_PP))
    assert tr.calls == []


def test_payment_receipt_get_module_invalid_fail_loud_no_network():
    ent, tr = _wire(PaymentReceiptEntity, [])
    with pytest.raises(PaymentReceiptValidationError):
        ent.get("r1", module="zz")
    assert tr.calls == []


# ---------- payment_receipt：fncc header 注入（profile vs flag） ----------

def test_payment_receipt_injects_company_code_header_from_profile():
    ent, tr = _wire(PaymentReceiptEntity, [FakeResponse(200, _page([]))])
    ent.list(module="ar", filter=dict(_PP))  # 不传 company_code → 取 cred 默认
    assert tr.calls[0]["headers"]["fncc"] == "CC-DEFAULT"


def test_payment_receipt_company_code_arg_overrides_profile():
    ent, tr = _wire(PaymentReceiptEntity, [FakeResponse(200, _page([]))])
    ent.list(module="ar", filter=dict(_PP), company_code="CC-OVERRIDE")
    assert tr.calls[0]["headers"]["fncc"] == "CC-OVERRIDE"


def test_payment_receipt_get_injects_company_code_header():
    ent, tr = _wire(PaymentReceiptEntity, [FakeResponse(200, {"id": "r1"})])
    ent.get("r1", module="ar", company_code="CC-X")
    assert tr.calls[0]["headers"]["fncc"] == "CC-X"


def test_payment_receipt_no_default_cc_and_no_arg_omits_header():
    # cred 无 default_company_code_id 且未传 company_code → 不注入 fncc（None 不发）。
    ent, tr = _wire(PaymentReceiptEntity, [FakeResponse(200, _page([]))], cred=_CRED_NO_CC)
    ent.list(module="ar", filter=dict(_PP))
    assert "fncc" not in tr.calls[0]["headers"]


# ---------- payment_receipt：REQUIRED posting_period 校验 ----------

def test_payment_receipt_missing_from_posting_period_fail_loud_no_network():
    ent, tr = _wire(PaymentReceiptEntity, [])
    with pytest.raises(PaymentReceiptValidationError):
        ent.list(module="ar", filter={"to_posting_period_id": "pp9"})
    assert tr.calls == []


def test_payment_receipt_missing_to_posting_period_fail_loud_no_network():
    ent, tr = _wire(PaymentReceiptEntity, [])
    with pytest.raises(PaymentReceiptValidationError):
        ent.list(module="ar", filter={"from_posting_period_id": "pp1"})
    assert tr.calls == []


def test_payment_receipt_missing_filter_entirely_fail_loud():
    ent, tr = _wire(PaymentReceiptEntity, [])
    with pytest.raises(PaymentReceiptValidationError):
        ent.list(module="ar")
    assert tr.calls == []


def test_payment_receipt_filter_passed_as_query():
    ent, tr = _wire(PaymentReceiptEntity, [FakeResponse(200, _page([]))])
    ent.list(module="ar", filter={**_PP, "status": "OPEN"})
    params = tr.calls[0]["params"]
    assert params["from_posting_period_id"] == "pp1"
    assert params["to_posting_period_id"] == "pp9"
    assert params["status"] == "OPEN"


# ---------- fapiao：module 分叉端点（/ar vs /ap） ----------

def test_fapiao_list_ar_endpoint_segment():
    ent, tr = _wire(FapiaoEntity, [FakeResponse(200, _page([{"id": "f1"}]))])
    page = ent.list(module="ar")
    assert isinstance(page, Page)
    url = tr.calls[0]["url"]
    assert url.endswith("/v2/api/tenants/10030/company-codes/fapiaos/ar/query-page")


def test_fapiao_list_ap_endpoint_segment():
    ent, tr = _wire(FapiaoEntity, [FakeResponse(200, _page([]))])
    ent.list(module="ap")
    url = tr.calls[0]["url"]
    assert url.endswith("/v2/api/tenants/10030/company-codes/fapiaos/ap/query-page")


def test_fapiao_get_ar_path_id():
    ent, tr = _wire(FapiaoEntity, [FakeResponse(200, {"id": "f1"})])
    ent.get("f1", module="ar")
    assert tr.calls[0]["url"].endswith("/v2/api/tenants/10030/company-codes/fapiaos/ar/f1")


def test_fapiao_get_ap_path_id():
    ent, tr = _wire(FapiaoEntity, [FakeResponse(200, {"id": "f2"})])
    ent.get("f2", module="ap")
    assert tr.calls[0]["url"].endswith("/v2/api/tenants/10030/company-codes/fapiaos/ap/f2")


def test_fapiao_module_invalid_fail_loud_no_network():
    ent, tr = _wire(FapiaoEntity, [])
    with pytest.raises(PaymentReceiptValidationError):
        ent.list(module="bad")
    assert tr.calls == []


def test_fapiao_module_missing_fail_loud_no_network():
    ent, tr = _wire(FapiaoEntity, [])
    with pytest.raises(PaymentReceiptValidationError):
        ent.get("f1")  # module 缺失
    assert tr.calls == []


# ---------- fapiao：posting_period OPTIONAL（不强制） ----------

def test_fapiao_list_without_posting_period_is_allowed():
    # payment_receipt 缺 posting_period 会 fail-loud；fapiao 同字段 OPTIONAL，不校验 → 正常打网络。
    ent, tr = _wire(FapiaoEntity, [FakeResponse(200, _page([]))])
    page = ent.list(module="ar")  # 无 filter
    assert isinstance(page, Page)
    assert len(tr.calls) == 1  # 确实打了网络


def test_fapiao_list_without_filter_arg_is_allowed():
    ent, tr = _wire(FapiaoEntity, [FakeResponse(200, _page([]))])
    ent.list(module="ap", filter=None)
    assert len(tr.calls) == 1


# ---------- fapiao：fncc header 注入 ----------

def test_fapiao_injects_company_code_header_from_profile():
    ent, tr = _wire(FapiaoEntity, [FakeResponse(200, _page([]))])
    ent.list(module="ar")
    assert tr.calls[0]["headers"]["fncc"] == "CC-DEFAULT"


def test_fapiao_company_code_arg_overrides_profile():
    ent, tr = _wire(FapiaoEntity, [FakeResponse(200, _page([]))])
    ent.list(module="ar", company_code="CC-FAPIAO")
    assert tr.calls[0]["headers"]["fncc"] == "CC-FAPIAO"


def test_fapiao_get_injects_company_code_header():
    ent, tr = _wire(FapiaoEntity, [FakeResponse(200, {"id": "f1"})])
    ent.get("f1", module="ap", company_code="CC-G")
    assert tr.calls[0]["headers"]["fncc"] == "CC-G"


def test_fapiao_ap_certificate_date_filter_passed_as_query():
    ent, tr = _wire(FapiaoEntity, [FakeResponse(200, _page([]))])
    ent.list(module="ap", filter={"from_certificate_date": "2026-01-01", "to_certificate_date": "2026-01-31"})
    params = tr.calls[0]["params"]
    assert params["from_certificate_date"] == "2026-01-01"
    assert params["to_certificate_date"] == "2026-01-31"


# ---------- 金额/币种 companion 归一（§6 行 781-809：fn 含金额字段，sd companion 模式旁挂） ----------
#
# §6 未枚举 fn 响应币种字段名（filter_keys 是过滤键非响应字段）→ 照 sd 约定用 `*_currency_no`→
# `*_currency` companion 机制验「注入 currency_index 后机制通」+「不注入只透传不炸」。
# 字段名 live 阶段复核（fn entity docstring 已挂 TODO），实际字段名不同则 companion 自然 no-op。

# 桩 currency_index：数值 ISO 156 → 字母 CNY（同 build_currency_index 产物形状）。
_CURRENCY_INDEX = {"156": "CNY", "CNY": "CNY", "840": "USD", "USD": "USD"}


def test_payment_receipt_attaches_currency_companion_when_index_injected():
    # 注入 currency_index 后，桩行项的 local_currency_no=156 → 旁挂 local_currency=CNY（原 _no 字段不动）。
    ent, tr = _wire(
        PaymentReceiptEntity,
        [FakeResponse(200, _page([{"id": "r1", "local_currency_no": "156", "amount": 100}]))],
        currency_index=_CURRENCY_INDEX,
    )
    page = ent.list(module="ar", filter=dict(_PP))
    it = page.items[0]
    assert it["local_currency_no"] == "156"  # 原数值 ISO 字段保留不动（非破坏性）
    assert it["local_currency"] == "CNY"  # 旁挂 alpha companion


def test_fapiao_attaches_currency_companion_when_index_injected():
    ent, tr = _wire(
        FapiaoEntity,
        [FakeResponse(200, _page([{"id": "f1", "original_currency_no": "840"}]))],
        currency_index=_CURRENCY_INDEX,
    )
    page = ent.list(module="ar")
    it = page.items[0]
    assert it["original_currency_no"] == "840"
    assert it["original_currency"] == "USD"  # 840 → USD companion


def test_payment_receipt_get_attaches_currency_companion():
    # get 单条同样旁挂 companion（_get_module 包成单元素 list 复用同一机制）。
    ent, tr = _wire(
        PaymentReceiptEntity,
        [FakeResponse(200, {"id": "r1", "local_currency_no": "156"})],
        currency_index=_CURRENCY_INDEX,
    )
    rec = ent.get("r1", module="ar")
    assert rec["local_currency_no"] == "156"
    assert rec["local_currency"] == "CNY"


def test_payment_receipt_passthrough_when_no_currency_index():
    # 不注入 currency_index（默认 None）→ companion no-op，行项原样透传、绝不炸。
    ent, tr = _wire(
        PaymentReceiptEntity,
        [FakeResponse(200, _page([{"id": "r1", "local_currency_no": "156"}]))],
    )
    page = ent.list(module="ar", filter=dict(_PP))
    it = page.items[0]
    assert it["local_currency_no"] == "156"
    assert "local_currency" not in it  # 无 index → 不旁挂 companion


def test_fapiao_passthrough_when_currency_field_absent():
    # 注入 index 但行项无 *_currency_no 字段 → companion 永不触发（与 sd.delivery_receipt_item 诚实降级一致）。
    ent, tr = _wire(
        FapiaoEntity,
        [FakeResponse(200, _page([{"id": "f1", "amount": 50}]))],
        currency_index=_CURRENCY_INDEX,
    )
    page = ent.list(module="ar")
    it = page.items[0]
    assert "local_currency" not in it
    assert "original_currency" not in it


# ---------- 双轨误发守护：company_code / posting_period（M2）不发 header ----------

def test_company_code_request_has_no_company_code_header():
    """M2 company_code（cc 定义源）请求绝不含 fncc header。"""
    sess = Session(_CRED, transport=FakeTransport([FakeResponse(200, _TOKEN)]))
    data_tr = FakeTransport([FakeResponse(200, [])])
    from in3_client.http import HttpClient
    http = HttpClient(sess, transport=data_tr)
    ent = CompanyCodeEntity(_CRED, sess, http)
    ent.list()
    h = data_tr.calls[0]["headers"]
    assert "fncc" not in h
    # 基线头集：三认证头 + Accept（Session.headers() 对齐 CLI；fncc 仍绝不出现）。
    assert set(h.keys()) == {"Authorization", "T-CODE", "X-Operator-ID", "Accept"}


# ---------- 只读边界守护 ----------

@pytest.mark.parametrize("cls", [PaymentReceiptEntity, FapiaoEntity])
def test_fn_twin_entities_no_write_methods(cls):
    ent, _ = _wire(cls, [])
    for w in ("create", "update", "delete", "post_write", "save", "remove"):
        assert not hasattr(ent, w)
