"""sd 模块 M3 entity 单测（issue #14 §6 行 605/619/707/719）—— 最重坑层。

直接实例化 entity 类（FakeTransport，**不经 facade**——facade 装配是收口阶段的事）。

#14 四实体：
  sales_order(§6 605, fanout-gotcha 5pt)：GET list /sales-orders/page + GET get /sales-orders/{id}；
    include_items 走 enrich_items_fanout（fail-isolated，per-header GET /sales-orders/items/page?so_id=）；
    get detail products[]→items[] alias（仅 items 缺时）；get(include_items=True) 用专用 items 端点
    REPLACE inline alias；header total_amount 不可信；含币种归一。
  contract(§6 619, fanout-gotcha 3pt)：GET list /contracts/page + GET get /contracts/{id}；
    --customer→account_id；include_items per-header GET /contracts/items/page?contract_id=；
    get detail 为 plain append items（**无** products alias）；signed_date_* 是 date；含币种归一。
  quotation(§6 707, fanout-gotcha 3pt)：**POST** list /quotations/page（filter 进 body、page/size 进 query）
    + **GET** get /quotations/{id}；quotation_item_details[]→items[] alias（仅 items 缺时）；
    --customer→acc_name（DTO 字段）；含币种归一。
  delivery_receipt_item(§6 719, list-only 3pt)：**三必填参** company_id/ps_flag/account_id（缺任一
    raise，不打网络）；source='so'|'material-doc' 参数化 path 段（dual-source）；后端裸 List → 自包
    成 wrapper {items, total, source}；无分页、无 .get。

覆盖：POST vs GET 路由分离、filter 进 body vs query、alias-if-absent（已存在不覆盖）、
enrich_items_fanout fail-isolated 接线、币种 companion、三必填参校验、dual-source path、
裸 List wrapper、只读边界 no-write、list-only 无 get。
"""
from dataclasses import dataclass, field

import pytest

from in3_client.auth import Session
from in3_client.config import Credentials
from in3_client.envelope import Page
from in3_client.http import HttpClient, HttpError
from in3_client.entities.sd import (
    SalesOrderEntity,
    ContractEntity,
    QuotationEntity,
    DeliveryReceiptItemEntity,
    DeliveryReceiptItemValidationError,
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


# =========================================================
# sd.sales_order（fanout-gotcha）：GET list/get + products alias + enrich fan-out + 币种
# =========================================================

def test_sales_order_list_url_and_method_get():
    ent, tr = _wire(SalesOrderEntity, [FakeResponse(200, {"content": [{"id": "so1"}], "last": True})])
    page = ent.list()
    assert isinstance(page, Page)
    assert page.items == [{"id": "so1"}]
    # GET list /sales-orders/page（不是 POST）
    assert tr.calls[0]["method"] == "GET"
    assert tr.calls[0]["url"] == f"{_BASE}/sales-orders/page"


def test_sales_order_list_filter_in_query_not_body():
    ent, tr = _wire(SalesOrderEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(filter={"so_query": "SO-9"})
    # GET 路径：filter 进 query，不进 body
    assert tr.calls[0]["params"]["so_query"] == "SO-9"
    assert tr.calls[0]["json"] is None


def test_sales_order_customer_maps_to_account_id():
    ent, tr = _wire(SalesOrderEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(customer="acc-7")
    p = tr.calls[0]["params"]
    assert p["account_id"] == "acc-7"
    assert "customer" not in p


def test_sales_order_plant_status_typed_flags():
    ent, tr = _wire(SalesOrderEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(plant="P-1", status="A")
    p = tr.calls[0]["params"]
    assert p["plant_id"] == "P-1"
    assert p["status"] == "A"


def test_sales_order_unknown_filter_key_raises():
    from in3_client.filters import FilterKeyError
    ent, tr = _wire(SalesOrderEntity, [FakeResponse(200, {"content": [], "last": True})])
    with pytest.raises(FilterKeyError):
        ent.list(filter={"bogus": "x"})


def test_sales_order_get_url():
    ent, tr = _wire(SalesOrderEntity, [FakeResponse(200, {"id": "so1", "so_no": "SO-001"})])
    rec = ent.get("so1")
    assert rec["so_no"] == "SO-001"
    assert tr.calls[0]["method"] == "GET"
    assert tr.calls[0]["url"] == f"{_BASE}/sales-orders/so1"


def test_sales_order_get_aliases_products_to_items_when_items_absent():
    # get detail products[] → items[] alias（仅 items 缺时），mirror CLI aliasProductsAsItems
    detail = {"id": "so1", "products": [{"line": "p1"}, {"line": "p2"}]}
    ent, tr = _wire(SalesOrderEntity, [FakeResponse(200, detail)])
    rec = ent.get("so1")
    assert rec["items"] == [{"line": "p1"}, {"line": "p2"}]
    assert rec["products"] == [{"line": "p1"}, {"line": "p2"}]  # 原 products 不动


def test_sales_order_get_does_not_override_existing_items():
    # items 已存在 → 不被 products 覆盖（alias-if-absent）
    detail = {"id": "so1", "items": [{"line": "real"}], "products": [{"line": "p1"}]}
    ent, tr = _wire(SalesOrderEntity, [FakeResponse(200, detail)])
    rec = ent.get("so1")
    assert rec["items"] == [{"line": "real"}]  # 不被覆盖


def test_sales_order_get_no_products_no_items_no_alias():
    # 既无 products 也无 items → 不臆造 items key
    detail = {"id": "so1", "so_no": "SO-1"}
    ent, tr = _wire(SalesOrderEntity, [FakeResponse(200, detail)])
    rec = ent.get("so1")
    assert "items" not in rec


def test_sales_order_get_include_items_replaces_alias_with_dedicated_fetch():
    # get(include_items=True)：用专用 /sales-orders/items/page?so_id= 端点 REPLACE inline products alias
    header = {"id": "so1", "products": [{"line": "stale-inline"}]}
    items_page = {"content": [{"line": "fresh-1"}, {"line": "fresh-2"}], "last": True}
    ent, tr = _wire(SalesOrderEntity, [FakeResponse(200, header), FakeResponse(200, items_page)])
    rec = ent.get("so1", include_items=True)
    # 第二次 call 打专用 items 端点带 so_id
    assert tr.calls[1]["url"] == f"{_BASE}/sales-orders/items/page"
    assert tr.calls[1]["params"]["so_id"] == "so1"
    # items 来自专用端点，不是 inline products alias
    assert rec["items"] == [{"line": "fresh-1"}, {"line": "fresh-2"}]


def test_sales_order_list_include_items_fanout_attaches_per_header():
    # include_items=True 走 enrich_items_fanout：list 一次 + 每 header 一次 items 端点
    list_resp = {"content": [{"id": "soA"}, {"id": "soB"}], "last": True}
    items_a = {"content": [{"line": "a1"}], "last": True}
    items_b = {"content": [{"line": "b1"}, {"line": "b2"}], "last": True}
    ent, tr = _wire(
        SalesOrderEntity,
        [FakeResponse(200, list_resp), FakeResponse(200, items_a), FakeResponse(200, items_b)],
    )
    page = ent.list(include_items=True)
    by_id = {h["id"]: h for h in page.items}
    assert by_id["soA"]["items"] == [{"line": "a1"}]
    assert by_id["soB"]["items"] == [{"line": "b1"}, {"line": "b2"}]
    # 每 header 的 items 端点带 so_id
    item_calls = [c for c in tr.calls if c["url"].endswith("/sales-orders/items/page")]
    so_ids = {c["params"]["so_id"] for c in item_calls}
    assert so_ids == {"soA", "soB"}


def test_sales_order_list_include_items_fail_isolated():
    # 单 header items 抓取失败（404）→ 该 header items=None + items_error，**不冒泡**，其余正常
    list_resp = {"content": [{"id": "soOK"}, {"id": "soBAD"}], "last": True}
    items_ok = {"content": [{"line": "ok1"}], "last": True}
    # soBAD 的 items 抓取返 500 → enrich_items_fanout 隔离
    ent, tr = _wire(
        SalesOrderEntity,
        [FakeResponse(200, list_resp), FakeResponse(200, items_ok), FakeResponse(500, text="boom")],
    )
    page = ent.list(include_items=True)  # 不抛
    by_id = {h["id"]: h for h in page.items}
    assert by_id["soOK"]["items"] == [{"line": "ok1"}]
    assert by_id["soBAD"]["items"] is None
    assert "items_error" in by_id["soBAD"]


def test_sales_order_currency_companion_attached():
    # 含币种：header 带 local_currency_no/original_currency_no → 旁挂 alpha companion，原 *_no 不动
    ccy = {"156": "CNY", "840": "USD"}
    list_resp = {"content": [
        {"id": "so1", "local_currency_no": "156", "original_currency_no": "840"},
    ], "last": True}
    ent, tr = _wire(SalesOrderEntity, [FakeResponse(200, list_resp)], currency_index=ccy)
    it = ent.list().items[0]
    assert it["local_currency_no"] == "156"  # 原字段不动
    assert it["local_currency"] == "CNY"
    assert it["original_currency"] == "USD"


def test_sales_order_read_only():
    ent, _ = _wire(SalesOrderEntity, [])
    _assert_read_only(ent)


# =========================================================
# sd.contract（fanout-gotcha）：GET list/get + plain-append items（无 products alias）
# =========================================================

def test_contract_list_url_and_method_get():
    ent, tr = _wire(ContractEntity, [FakeResponse(200, {"content": [{"id": "c1"}], "last": True})])
    page = ent.list()
    assert page.items == [{"id": "c1"}]
    assert tr.calls[0]["method"] == "GET"
    assert tr.calls[0]["url"] == f"{_BASE}/contracts/page"


def test_contract_customer_maps_to_account_id():
    ent, tr = _wire(ContractEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(customer="acc-3")
    p = tr.calls[0]["params"]
    assert p["account_id"] == "acc-3"  # --customer → account_id（NOT customer_id）
    assert "customer" not in p


def test_contract_status_category_typed_flags():
    ent, tr = _wire(ContractEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(status="A", category="cat1")
    p = tr.calls[0]["params"]
    assert p["status"] == "A"
    # category typed-flag 映射到后端 filter（contract-category 关联）
    assert "cat1" in p.values()


def test_contract_unknown_filter_key_raises():
    from in3_client.filters import FilterKeyError
    ent, tr = _wire(ContractEntity, [FakeResponse(200, {"content": [], "last": True})])
    with pytest.raises(FilterKeyError):
        ent.list(filter={"nope": 1})


def test_contract_signed_date_is_plain_date_passthrough():
    # contract HEADER 的 signed_date_start/end 是 plain date（区别于 contract-ITEM 的 datetime ISO）
    ent, tr = _wire(ContractEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(filter={"signed_date_start": "2026-01-01", "signed_date_end": "2026-12-31"})
    p = tr.calls[0]["params"]
    assert p["signed_date_start"] == "2026-01-01"
    assert p["signed_date_end"] == "2026-12-31"


def test_contract_get_url():
    ent, tr = _wire(ContractEntity, [FakeResponse(200, {"id": "c1", "contract_no": "CT-1"})])
    rec = ent.get("c1")
    assert rec["contract_no"] == "CT-1"
    assert tr.calls[0]["method"] == "GET"
    assert tr.calls[0]["url"] == f"{_BASE}/contracts/c1"


def test_contract_get_no_products_alias():
    # contract get detail **无** products alias —— 带 products 也不自动挂 items（plain append 语义）
    detail = {"id": "c1", "products": [{"line": "p1"}]}
    ent, tr = _wire(ContractEntity, [FakeResponse(200, detail)])
    rec = ent.get("c1")  # 不带 include_items
    assert "items" not in rec  # 无 native alias


def test_contract_get_include_items_appends():
    # get(include_items=True)：从 /contracts/items/page?contract_id= 抓 items 并 APPEND（plain）
    header = {"id": "c1", "contract_no": "CT-1"}
    items_page = {"content": [{"line": "i1"}, {"line": "i2"}], "last": True}
    ent, tr = _wire(ContractEntity, [FakeResponse(200, header), FakeResponse(200, items_page)])
    rec = ent.get("c1", include_items=True)
    assert tr.calls[1]["url"] == f"{_BASE}/contracts/items/page"
    assert tr.calls[1]["params"]["contract_id"] == "c1"
    assert rec["items"] == [{"line": "i1"}, {"line": "i2"}]


def test_contract_list_include_items_fanout_fail_isolated():
    list_resp = {"content": [{"id": "cOK"}, {"id": "cBAD"}], "last": True}
    items_ok = {"content": [{"line": "ok"}], "last": True}
    ent, tr = _wire(
        ContractEntity,
        [FakeResponse(200, list_resp), FakeResponse(200, items_ok), FakeResponse(500, text="boom")],
    )
    page = ent.list(include_items=True)  # 不抛
    by_id = {h["id"]: h for h in page.items}
    assert by_id["cOK"]["items"] == [{"line": "ok"}]
    assert by_id["cBAD"]["items"] is None
    assert "items_error" in by_id["cBAD"]
    # 每 header items 端点带 contract_id
    item_calls = [c for c in tr.calls if c["url"].endswith("/contracts/items/page")]
    assert {c["params"]["contract_id"] for c in item_calls} == {"cOK", "cBAD"}


def test_contract_currency_companion_attached():
    ccy = {"156": "CNY"}
    list_resp = {"content": [{"id": "c1", "local_currency_no": "156"}], "last": True}
    ent, tr = _wire(ContractEntity, [FakeResponse(200, list_resp)], currency_index=ccy)
    it = ent.list().items[0]
    assert it["local_currency_no"] == "156"
    assert it["local_currency"] == "CNY"


def test_contract_read_only():
    ent, _ = _wire(ContractEntity, [])
    _assert_read_only(ent)


# =========================================================
# sd.quotation（fanout-gotcha）：POST list + GET get + item_details alias + acc_name
# =========================================================

def test_quotation_list_is_post_filter_in_body():
    # LIST 是 POST /quotations/page —— filter 进 JSON body、page/size 进 query
    ent, tr = _wire(QuotationEntity, [FakeResponse(200, {"content": [{"id": "q1"}], "last": True})])
    page = ent.list(filter={"quotation_no": "Q-1"})
    assert page.items == [{"id": "q1"}]
    call = tr.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == f"{_BASE}/quotations/page"
    assert call["json"]["quotation_no"] == "Q-1"  # filter 进 body
    assert "quotation_no" not in call["params"]    # 不进 query
    assert call["params"] == {"page": "0", "size": "20"}


def test_quotation_customer_maps_to_acc_name():
    # quotation DTO 用 acc_name（不是 customer_id）—— --customer 映射 acc_name
    ent, tr = _wire(QuotationEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(customer="ACME")
    body = tr.calls[0]["json"]
    assert body["acc_name"] == "ACME"
    assert "customer" not in body


def test_quotation_status_quotation_no_typed_flags_in_body():
    ent, tr = _wire(QuotationEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(status="A", quotation_no="Q-9")
    body = tr.calls[0]["json"]
    assert body["status"] == "A"
    assert body["quotation_no"] == "Q-9"


def test_quotation_unknown_filter_key_raises():
    from in3_client.filters import FilterKeyError
    ent, tr = _wire(QuotationEntity, [FakeResponse(200, {"content": [], "last": True})])
    with pytest.raises(FilterKeyError):
        ent.list(filter={"bogus": 1})


def test_quotation_get_is_plain_get():
    # get 是 GET /quotations/{id}（与 POST list 分用不同 transport）
    ent, tr = _wire(QuotationEntity, [FakeResponse(200, {"id": "q1", "quotation_no": "Q-1"})])
    rec = ent.get("q1")
    assert rec["quotation_no"] == "Q-1"
    assert tr.calls[0]["method"] == "GET"
    assert tr.calls[0]["url"] == f"{_BASE}/quotations/q1"


def test_quotation_get_aliases_item_details_to_items_when_absent():
    # get detail quotation_item_details[] → items[] alias（仅 items 缺时）
    detail = {"id": "q1", "quotation_item_details": [{"line": "d1"}, {"line": "d2"}]}
    ent, tr = _wire(QuotationEntity, [FakeResponse(200, detail)])
    rec = ent.get("q1")
    assert rec["items"] == [{"line": "d1"}, {"line": "d2"}]
    assert rec["quotation_item_details"] == [{"line": "d1"}, {"line": "d2"}]  # 原字段不动


def test_quotation_get_does_not_override_existing_items():
    detail = {"id": "q1", "items": [{"line": "real"}], "quotation_item_details": [{"line": "d1"}]}
    ent, tr = _wire(QuotationEntity, [FakeResponse(200, detail)])
    rec = ent.get("q1")
    assert rec["items"] == [{"line": "real"}]


def test_quotation_currency_companion_attached():
    ccy = {"156": "CNY"}
    list_resp = {"content": [{"id": "q1", "local_currency_no": "156"}], "last": True}
    ent, tr = _wire(QuotationEntity, [FakeResponse(200, list_resp)], currency_index=ccy)
    it = ent.list().items[0]
    assert it["local_currency"] == "CNY"


def test_quotation_read_only():
    ent, _ = _wire(QuotationEntity, [])
    _assert_read_only(ent)


# =========================================================
# sd.delivery_receipt_item（list-only）：3 必填参 + dual-source + 裸 List wrapper
# =========================================================

def test_dri_missing_company_raises_no_network():
    # company 缺 → raise validation error，**不打网络**
    ent, tr = _wire(DeliveryReceiptItemEntity, [])  # 无响应——若打网络会 IndexError
    with pytest.raises(DeliveryReceiptItemValidationError):
        ent.list(ps_flag="P", account="a1")
    assert tr.calls == []  # 未发请求


def test_dri_missing_ps_flag_raises_no_network():
    ent, tr = _wire(DeliveryReceiptItemEntity, [])
    with pytest.raises(DeliveryReceiptItemValidationError):
        ent.list(company="c1", account="a1")
    assert tr.calls == []


def test_dri_missing_account_raises_no_network():
    ent, tr = _wire(DeliveryReceiptItemEntity, [])
    with pytest.raises(DeliveryReceiptItemValidationError):
        ent.list(company="c1", ps_flag="P")
    assert tr.calls == []


def test_dri_source_so_path():
    # source='so'（默认）→ GET /delivery-receipts/by-so-items/list
    ent, tr = _wire(DeliveryReceiptItemEntity, [FakeResponse(200, [{"id": "ri1"}])])
    page = ent.list(company="c1", ps_flag="P", account="a1")
    assert tr.calls[0]["method"] == "GET"
    assert tr.calls[0]["url"] == f"{_BASE}/delivery-receipts/by-so-items/list"


def test_dri_source_material_doc_path():
    # source='material-doc' → GET /delivery-receipts/by-material-doc-items/list（dual-source path 段）
    ent, tr = _wire(DeliveryReceiptItemEntity, [FakeResponse(200, [{"id": "ri1"}])])
    ent.list(source="material-doc", company="c1", ps_flag="P", account="a1")
    assert tr.calls[0]["url"] == f"{_BASE}/delivery-receipts/by-material-doc-items/list"


def test_dri_three_mandatory_params_in_query():
    ent, tr = _wire(DeliveryReceiptItemEntity, [FakeResponse(200, [])])
    ent.list(company="c1", ps_flag="P", account="a1")
    p = tr.calls[0]["params"]
    assert p["company_id"] == "c1"
    assert p["ps_flag"] == "P"
    assert p["account_id"] == "a1"


def test_dri_bare_list_wrapped_with_items_total_source():
    # 后端返裸 List<> → 自包成 wrapper {items, total, source}
    ent, tr = _wire(
        DeliveryReceiptItemEntity,
        [FakeResponse(200, [{"id": "ri1"}, {"id": "ri2"}, {"id": "ri3"}])],
    )
    page = ent.list(company="c1", ps_flag="P", account="a1")
    assert isinstance(page, Page)
    assert page.items == [{"id": "ri1"}, {"id": "ri2"}, {"id": "ri3"}]
    assert page.total == 3            # total = len(裸 list)
    assert page.has_next is False     # 无分页
    assert page.source == "so"        # source marker


def test_dri_source_marker_material_doc():
    ent, tr = _wire(DeliveryReceiptItemEntity, [FakeResponse(200, [{"id": "ri1"}])])
    page = ent.list(source="material-doc", company="c1", ps_flag="P", account="a1")
    assert page.source == "material-doc"


def test_dri_empty_bare_list_total_zero():
    ent, tr = _wire(DeliveryReceiptItemEntity, [FakeResponse(200, [])])
    page = ent.list(company="c1", ps_flag="P", account="a1")
    assert page.items == []
    assert page.total == 0


def test_dri_so_id_optional_passthrough():
    ent, tr = _wire(DeliveryReceiptItemEntity, [FakeResponse(200, [])])
    ent.list(company="c1", ps_flag="P", account="a1", so_id="so9")
    assert tr.calls[0]["params"]["so_id"] == "so9"


def test_dri_list_only_no_get():
    # list-only —— 无 .get（忠实不假装）
    ent, _ = _wire(DeliveryReceiptItemEntity, [])
    assert not hasattr(ent, "get")


def test_dri_read_only():
    ent, _ = _wire(DeliveryReceiptItemEntity, [])
    _assert_read_only(ent)
