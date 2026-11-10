"""sd 模块 M1/M2 entity 单测（issue #12 / #13）。

直接实例化 entity 类（FakeTransport，**不经 facade**——facade 装配是收口阶段的事）。

M1（#12 §6 行 642-696）simple-list-get：
  sales_dept(单数裸 /sales-dept, 无 typed filter; parity 实测 /page 405 → 裸数组)
  contract_category(裸 /contract-categories, status=int; parity 实测 /page 405 → 裸数组)
  so_item_category(单数裸 /so-item-category, status=int; parity 实测 /page 405 → 裸数组)
  delivery_group_no(/delivery-group-nos/page, list+get, 4 个 snake filter)
  sd_info_record(/info-records/page 丢 sd- 前缀, customer→account_id, plant 透传不承诺)
  delivery_receipt_type(/delivery-receipt-types/page, filter key camelCase queryText, status=int)
M2（#13 §6 行 697-705）list-only：
  contract_item(/contracts/items/page, **无 get**, signed_date_* 是 datetime ISO)

覆盖：_list_path / _get_path 覆写后 URL 正确、filter key/类型映射、list-only 无 get、
只读边界 no-write、status int 透传、customer→account_id 映射、queryText camelCase 字面量。
"""
from dataclasses import dataclass, field

import pytest

from in3_client.auth import Session
from in3_client.config import Credentials
from in3_client.envelope import Page
from in3_client.filters import FilterKeyError
from in3_client.http import HttpClient, HttpError
from in3_client.entities.sd import (
    SalesDeptEntity,
    ContractCategoryEntity,
    SoItemCategoryEntity,
    DeliveryGroupNoEntity,
    SdInfoRecordEntity,
    DeliveryReceiptTypeEntity,
    ContractItemEntity,
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

_BASE = "https://apiv3.industics.com/service/mom/sd/v2/api/tenants/10030"


def _wire(entity_cls, data_responses, **kw):
    sess = Session(_CRED, transport=FakeTransport([FakeResponse(200, _TOKEN)]))
    data_tr = FakeTransport(data_responses)
    http = HttpClient(sess, transport=data_tr)
    return entity_cls(_CRED, sess, http, **kw), data_tr


_WRITE_METHODS = ("create", "update", "delete", "post", "put", "patch", "remove", "save")


def _assert_read_only(ent):
    for m in _WRITE_METHODS:
        assert not hasattr(ent, m), f"只读边界破：不应有 {m}"


# ---------- sd.sales_dept（单数 path, 无 typed filter, list+get） ----------

def test_sales_dept_list_url_singular():
    # 裸 collection（无 /page）：后端返裸数组，coerce_to_page 包形。parity 实测 /page 405。
    ent, tr = _wire(SalesDeptEntity, [FakeResponse(200, [{"id": "d1"}])])
    page = ent.list()
    assert isinstance(page, Page)
    assert page.items == [{"id": "d1"}]
    # 单数 /sales-dept 裸 collection（无 /page、无复数 s）
    assert tr.calls[0]["url"] == f"{_BASE}/sales-dept"


def test_sales_dept_get_url_singular():
    ent, tr = _wire(SalesDeptEntity, [FakeResponse(200, {"id": "d1", "name": "华东销售部"})])
    rec = ent.get("d1")
    assert rec["name"] == "华东销售部"
    assert tr.calls[0]["url"] == f"{_BASE}/sales-dept/d1"


def test_sales_dept_get_404_raises():
    ent, tr = _wire(SalesDeptEntity, [FakeResponse(404, text="not found")])
    with pytest.raises(HttpError):
        ent.get("nope")


def test_sales_dept_no_typed_filter_bare_no_params():
    # 后端无 @RequestParam filter，裸 collection 也不分页——list 不发任何 query param。
    ent, tr = _wire(SalesDeptEntity, [FakeResponse(200, [])])
    ent.list(all=False)
    params = tr.calls[0]["params"]
    assert params == {}


def test_sales_dept_read_only():
    ent, _ = _wire(SalesDeptEntity, [])
    _assert_read_only(ent)


# ---------- sd.contract_category（status int, plural path, list+get） ----------

def test_contract_category_list_url_plural():
    # 裸 collection（无 /page）：parity 实测 /page 405，真端点是裸数组 GET。
    ent, tr = _wire(ContractCategoryEntity, [FakeResponse(200, [])])
    ent.list()
    assert tr.calls[0]["url"] == f"{_BASE}/contract-categories"


def test_contract_category_status_is_int():
    ent, tr = _wire(ContractCategoryEntity, [FakeResponse(200, [])])
    ent.list(status=1)
    # status 透传为 int（不是 str）
    assert tr.calls[0]["params"]["status"] == 1
    assert isinstance(tr.calls[0]["params"]["status"], int)


def test_contract_category_get_url():
    ent, tr = _wire(ContractCategoryEntity, [FakeResponse(200, {"id": "cc1"})])
    ent.get("cc1")
    assert tr.calls[0]["url"] == f"{_BASE}/contract-categories/cc1"


def test_contract_category_read_only():
    ent, _ = _wire(ContractCategoryEntity, [])
    _assert_read_only(ent)


# ---------- sd.so_item_category（单数 path, status int, list+get） ----------

def test_so_item_category_list_url_singular():
    # 裸 collection（无 /page）：parity 实测 /page 405，真端点是裸数组 GET（单数）。
    ent, tr = _wire(SoItemCategoryEntity, [FakeResponse(200, [])])
    ent.list()
    assert tr.calls[0]["url"] == f"{_BASE}/so-item-category"


def test_so_item_category_status_is_int():
    ent, tr = _wire(SoItemCategoryEntity, [FakeResponse(200, [])])
    ent.list(status=2)
    assert tr.calls[0]["params"]["status"] == 2
    assert isinstance(tr.calls[0]["params"]["status"], int)


def test_so_item_category_get_url_singular():
    ent, tr = _wire(SoItemCategoryEntity, [FakeResponse(200, {"id": "sic1"})])
    ent.get("sic1")
    assert tr.calls[0]["url"] == f"{_BASE}/so-item-category/sic1"


def test_so_item_category_read_only():
    ent, _ = _wire(SoItemCategoryEntity, [])
    _assert_read_only(ent)


# ---------- sd.delivery_group_no（plural -nos, 4 snake filter, list+get） ----------

def test_delivery_group_no_list_url_plural_nos():
    ent, tr = _wire(DeliveryGroupNoEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list()
    assert tr.calls[0]["url"] == f"{_BASE}/delivery-group-nos/page"


def test_delivery_group_no_passes_all_four_filters():
    ent, tr = _wire(DeliveryGroupNoEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(so_id="so9", group_no="G-1", group_name="批次1", query="x")
    p = tr.calls[0]["params"]
    assert p["so_id"] == "so9"
    assert p["group_no"] == "G-1"
    assert p["group_name"] == "批次1"
    assert p["query"] == "x"


def test_delivery_group_no_get_url():
    ent, tr = _wire(DeliveryGroupNoEntity, [FakeResponse(200, {"id": "g1"})])
    ent.get("g1")
    assert tr.calls[0]["url"] == f"{_BASE}/delivery-group-nos/g1"


def test_delivery_group_no_read_only():
    ent, _ = _wire(DeliveryGroupNoEntity, [])
    _assert_read_only(ent)


# ---------- sd.sd_info_record（/info-records 丢 sd- 前缀, customer→account_id, list+get） ----------

def test_sd_info_record_list_url_drops_sd_prefix():
    ent, tr = _wire(SdInfoRecordEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list()
    # 后端 path 丢 sd- 前缀 → /info-records/page（与命令名 sd-info-record 不符）
    assert tr.calls[0]["url"] == f"{_BASE}/info-records/page"


def test_sd_info_record_customer_maps_to_account_id():
    ent, tr = _wire(SdInfoRecordEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(customer="acc-7")
    p = tr.calls[0]["params"]
    assert p["account_id"] == "acc-7"      # --customer 映射到后端 account_id
    assert "customer" not in p


def test_sd_info_record_plant_passthrough_not_promised():
    # --plant 透传但后端可能静默忽略（不承诺生效）——SDK 仅透传，不报错
    ent, tr = _wire(SdInfoRecordEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(plant="P-1")
    assert tr.calls[0]["params"].get("plant_id") == "P-1"


def test_sd_info_record_material_maps_to_material_id():
    ent, tr = _wire(SdInfoRecordEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(material="m-3")
    assert tr.calls[0]["params"]["material_id"] == "m-3"


def test_sd_info_record_filter_dict_whitelist():
    ent, tr = _wire(SdInfoRecordEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(filter={"status": "A", "account_material_no": "X-9"})
    p = tr.calls[0]["params"]
    assert p["status"] == "A"
    assert p["account_material_no"] == "X-9"


def test_sd_info_record_unknown_filter_key_raises():
    ent, tr = _wire(SdInfoRecordEntity, [FakeResponse(200, {"content": [], "last": True})])
    with pytest.raises(FilterKeyError):
        ent.list(filter={"bogus_key": "x"})


def test_sd_info_record_get_url():
    ent, tr = _wire(SdInfoRecordEntity, [FakeResponse(200, {"id": "ir1"})])
    ent.get("ir1")
    assert tr.calls[0]["url"] == f"{_BASE}/info-records/ir1"


def test_sd_info_record_read_only():
    ent, _ = _wire(SdInfoRecordEntity, [])
    _assert_read_only(ent)


# ---------- sd.delivery_receipt_type（queryText camelCase, status int, list+get） ----------

def test_delivery_receipt_type_list_url_plural():
    ent, tr = _wire(DeliveryReceiptTypeEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list()
    assert tr.calls[0]["url"] == f"{_BASE}/delivery-receipt-types/page"


def test_delivery_receipt_type_query_text_is_camelcase_key():
    ent, tr = _wire(DeliveryReceiptTypeEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(query_text="出库")
    p = tr.calls[0]["params"]
    # 后端 key 是 camelCase queryText（不是 query_text）
    assert p["queryText"] == "出库"
    assert "query_text" not in p


def test_delivery_receipt_type_status_is_int():
    ent, tr = _wire(DeliveryReceiptTypeEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(status=3)
    assert tr.calls[0]["params"]["status"] == 3
    assert isinstance(tr.calls[0]["params"]["status"], int)


def test_delivery_receipt_type_get_url():
    ent, tr = _wire(DeliveryReceiptTypeEntity, [FakeResponse(200, {"id": "rt1"})])
    ent.get("rt1")
    assert tr.calls[0]["url"] == f"{_BASE}/delivery-receipt-types/rt1"


def test_delivery_receipt_type_read_only():
    ent, _ = _wire(DeliveryReceiptTypeEntity, [])
    _assert_read_only(ent)


# ---------- sd.contract_item（M2 list-only, 无 get, customer→account_id） ----------

def test_contract_item_list_url():
    ent, tr = _wire(ContractItemEntity, [FakeResponse(200, {"content": [{"id": "ci1"}], "last": True})])
    page = ent.list()
    assert page.items == [{"id": "ci1"}]
    assert tr.calls[0]["url"] == f"{_BASE}/contracts/items/page"


def test_contract_item_has_no_get():
    # 后端 /contracts/items/page 无 /{id}——忠实不假装 get（照 sales_order_item）
    ent, _ = _wire(ContractItemEntity, [])
    assert not hasattr(ent, "get")


def test_contract_item_customer_maps_to_account_id():
    ent, tr = _wire(ContractItemEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(customer="acc-3")
    p = tr.calls[0]["params"]
    assert p["account_id"] == "acc-3"
    assert "customer" not in p


def test_contract_item_contract_no_passthrough():
    ent, tr = _wire(ContractItemEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(contract_no="CT-9")
    assert tr.calls[0]["params"]["contract_no"] == "CT-9"


def test_contract_item_filter_dict_whitelist_signed_date():
    ent, tr = _wire(ContractItemEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(filter={"signed_date_start": "2026-01-01T00:00:00", "status": "A"})
    p = tr.calls[0]["params"]
    assert p["signed_date_start"] == "2026-01-01T00:00:00"
    assert p["status"] == "A"


def test_contract_item_unknown_filter_key_raises():
    ent, tr = _wire(ContractItemEntity, [FakeResponse(200, {"content": [], "last": True})])
    with pytest.raises(FilterKeyError):
        ent.list(filter={"not_a_key": 1})


def test_contract_item_currency_companion_when_present_and_index():
    # §6 line 704: 若 live 数据带 local_currency_no 且注入 index 则旁挂 alpha companion；
    # 缺则不臆造。这里给 index + 字段在场 → 旁挂；原 *_no 不动。
    ccy_index = {"156": "CNY", "840": "USD"}
    ent, tr = _wire(
        ContractItemEntity,
        [FakeResponse(200, {"content": [
            {"id": "ci1", "local_currency_no": "156", "original_currency_no": "840"},
        ], "last": True})],
        currency_index=ccy_index,
    )
    it = ent.list().items[0]
    assert it["local_currency_no"] == "156"     # 原字段不动
    assert it["local_currency"] == "CNY"         # 旁挂 companion
    assert it["original_currency"] == "USD"


def test_contract_item_no_currency_companion_when_field_absent():
    # 字段不在场 → 不臆造 companion（即便给了 index）
    ccy_index = {"156": "CNY"}
    ent, tr = _wire(
        ContractItemEntity,
        [FakeResponse(200, {"content": [{"id": "ci1", "amount": 10}], "last": True})],
        currency_index=ccy_index,
    )
    it = ent.list().items[0]
    assert "local_currency" not in it
    assert it["amount"] == 10


def test_contract_item_read_only():
    ent, _ = _wire(ContractItemEntity, [])
    _assert_read_only(ent)
