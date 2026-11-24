"""#12 M1 simple list/get + #13 M2 bare-array：md 模块新增实体单测。

直接实例化实体（FakeTransport，不经 facade）。覆盖：
  M1: plant(list-only) / measure_unit(list+get, /mdm/ 段, enable key) /
      account(simple, 无 /mdm/, payment_type multi 不挂 _matched_filter_values) /
      account_contact(list-only) / sales_organization(list-only, key_word 带下划线)
  M2: company_code(裸 List 包 Page 有 get) / material_category(裸 List, takes no params, 无 get) /
      exchange_rate(裸 List, 三参必填 → ValueError 不打网络, effective_at_* date) /
      product_level(/product-levels/tree 返单 dict → [dict] coerce, valid 切 /valid-tree)

端点单复数/filter_keys 照 §6 文档写，live parity 阶段复核（见各实体 docstring TODO）。
只读边界：每实体断言 not hasattr create/update/delete。
"""
from dataclasses import dataclass, field

import pytest

from in3_client.auth import Session
from in3_client.config import Credentials
from in3_client.envelope import Page
from in3_client.http import HttpClient, HttpError
from in3_client.filters import FilterKeyError
from in3_client.entities.md import (
    PlantEntity,
    MeasureUnitEntity,
    AccountEntity,
    AccountContactEntity,
    SalesOrganizationEntity,
    CompanyCodeEntity,
    MaterialCategoryEntity,
    ExchangeRateEntity,
    ProductLevelEntity,
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
_BASE = "https://apiv3.industics.com/service/mom/md/v2/api/tenants/10030"


def _wire(entity_cls, data_responses, **kw):
    sess = Session(_CRED, transport=FakeTransport([FakeResponse(200, _TOKEN)]))
    data_tr = FakeTransport(data_responses)
    http = HttpClient(sess, transport=data_tr)
    return entity_cls(_CRED, sess, http, **kw), data_tr


_WRITE_METHODS = ("create", "update", "delete", "post", "put", "patch", "save", "remove")


def _assert_read_only(ent):
    for m in _WRITE_METHODS:
        assert not hasattr(ent, m), f"read-only violation: {type(ent).__name__} exposes {m}"


# ============================================================
# M1 · plant (list-only, 标准分页, 无 get)
# ============================================================

def test_plant_list_url_and_envelope():
    ent, tr = _wire(PlantEntity, [FakeResponse(200, {"content": [{"id": "p1"}], "last": True})])
    page = ent.list()
    assert isinstance(page, Page)
    assert page.items == [{"id": "p1"}]
    assert tr.calls[0]["url"] == _BASE + "/plants/page"


def test_plant_list_passes_filter():
    ent, tr = _wire(PlantEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(filter={"plant_no": "P-1", "key_word": "北京"})
    assert tr.calls[0]["params"]["plant_no"] == "P-1"
    assert tr.calls[0]["params"]["key_word"] == "北京"


def test_plant_rejects_unknown_filter_key():
    ent, _ = _wire(PlantEntity, [])
    with pytest.raises(FilterKeyError):
        ent.list(filter={"bogus": "x"})


def test_plant_has_no_get():
    ent, _ = _wire(PlantEntity, [])
    assert not hasattr(ent, "get")


def test_plant_read_only():
    ent, _ = _wire(PlantEntity, [])
    _assert_read_only(ent)


# ============================================================
# M1 · measure_unit (list+get, /mdm/ 段, enable typed key)
# ============================================================

def test_measure_unit_list_url_has_mdm():
    ent, tr = _wire(MeasureUnitEntity, [FakeResponse(200, {"content": [{"id": "u1"}], "last": True})])
    ent.list()
    assert tr.calls[0]["url"] == _BASE + "/mdm/measure-units/page"


def test_measure_unit_get_url_has_mdm():
    ent, tr = _wire(MeasureUnitEntity, [FakeResponse(200, {"id": "u1", "unit_name": "千克"})])
    rec = ent.get("u1")
    assert rec["unit_name"] == "千克"
    assert tr.calls[0]["url"] == _BASE + "/mdm/measure-units/u1"


def test_measure_unit_enable_key_passthrough():
    ent, tr = _wire(MeasureUnitEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(filter={"enable": "true"})
    assert tr.calls[0]["params"]["enable"] == "true"


def test_measure_unit_rejects_enabled_typo_key():
    # 后端真实 key 是 enable（无 d）；传 enabled 应 fail-loud（不在 filter_keys）。
    ent, _ = _wire(MeasureUnitEntity, [])
    with pytest.raises(FilterKeyError):
        ent.list(filter={"enabled": "true"})


def test_measure_unit_get_404_raises():
    ent, _ = _wire(MeasureUnitEntity, [FakeResponse(404, text="not found")])
    with pytest.raises(HttpError):
        ent.get("nope")


def test_measure_unit_read_only():
    ent, _ = _wire(MeasureUnitEntity, [])
    _assert_read_only(ent)


# ============================================================
# M1 · account (list+get, 无 /mdm/ 段, payment_type multi 不挂 _matched_filter_values)
# ============================================================

def test_account_list_url_no_mdm():
    ent, tr = _wire(AccountEntity, [FakeResponse(200, {"content": [{"id": "a1"}], "last": True})])
    ent.list()
    assert tr.calls[0]["url"] == _BASE + "/accounts/page"


def test_account_get_url():
    ent, tr = _wire(AccountEntity, [FakeResponse(200, {"id": "a1", "account_name": "客户甲"})])
    rec = ent.get("a1")
    assert rec["account_name"] == "客户甲"
    assert tr.calls[0]["url"] == _BASE + "/accounts/a1"


def test_account_payment_type_plain_passthrough_no_matched_values():
    # payment_type 是 multi filter，但按普通透传，不挂 _matched_filter_values（照 md.material 约定）。
    ent, tr = _wire(AccountEntity, [FakeResponse(200, {"content": [{"id": "a1"}], "last": True})])
    page = ent.list(filter={"payment_type": "CASH"})
    assert tr.calls[0]["params"]["payment_type"] == "CASH"
    assert "_matched_filter_values" not in page.items[0]


def test_account_rejects_unknown_filter_key():
    ent, _ = _wire(AccountEntity, [])
    with pytest.raises(FilterKeyError):
        ent.list(filter={"nope": "x"})


def test_account_read_only():
    ent, _ = _wire(AccountEntity, [])
    _assert_read_only(ent)


# ============================================================
# M1 · account_contact (list-only, 无 get)
# ============================================================

def test_account_contact_list_url():
    ent, tr = _wire(AccountContactEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(filter={"account_id": "a1"})
    assert tr.calls[0]["url"] == _BASE + "/account-contacts/page"
    assert tr.calls[0]["params"]["account_id"] == "a1"


def test_account_contact_has_no_get():
    ent, _ = _wire(AccountContactEntity, [])
    assert not hasattr(ent, "get")


def test_account_contact_read_only():
    ent, _ = _wire(AccountContactEntity, [])
    _assert_read_only(ent)


# ============================================================
# M1 · sales_organization (list-only, key_word 带下划线)
# ============================================================

def test_sales_organization_list_url():
    ent, tr = _wire(SalesOrganizationEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list()
    assert tr.calls[0]["url"] == _BASE + "/sales-organizations/page"


def test_sales_organization_key_word_with_underscore():
    ent, tr = _wire(SalesOrganizationEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(filter={"key_word": "华东"})
    assert tr.calls[0]["params"]["key_word"] == "华东"


def test_sales_organization_rejects_keyword_no_underscore():
    # 搜索 key 是 key_word（下划线），keyword 不在白名单。
    ent, _ = _wire(SalesOrganizationEntity, [])
    with pytest.raises(FilterKeyError):
        ent.list(filter={"keyword": "华东"})


def test_sales_organization_has_no_get():
    ent, _ = _wire(SalesOrganizationEntity, [])
    assert not hasattr(ent, "get")


def test_sales_organization_read_only():
    ent, _ = _wire(SalesOrganizationEntity, [])
    _assert_read_only(ent)


# ============================================================
# M2 · company_code (裸 List 包 Page, 有 get, 非分页)
# ============================================================

def test_company_code_list_bare_array_wrapped():
    # 裸 JSON 数组 → Page(items=arr, page=0, total=len, has_next=False)，不被 normalize 吞空。
    ent, tr = _wire(CompanyCodeEntity, [FakeResponse(200, [{"id": "c1"}, {"id": "c2"}])])
    page = ent.list()
    assert isinstance(page, Page)
    assert [it["id"] for it in page.items] == ["c1", "c2"]
    assert page.total == 2
    assert page.has_next is False
    assert tr.calls[0]["url"] == _BASE + "/company-codes/list"


def test_company_code_empty_bare_array_not_swallowed():
    # 空裸数组绝不被 get_json 的 `or {}` 吞成 {} → 仍是空 Page（total=0），不抛。
    ent, _ = _wire(CompanyCodeEntity, [FakeResponse(200, [])])
    page = ent.list()
    assert page.items == []
    assert page.total == 0


def test_company_code_get():
    ent, tr = _wire(CompanyCodeEntity, [FakeResponse(200, {"id": "c1", "company_name": "甲公司"})])
    rec = ent.get("c1")
    assert rec["company_name"] == "甲公司"
    assert tr.calls[0]["url"] == _BASE + "/company-codes/c1"


def test_company_code_list_passes_company_query():
    ent, tr = _wire(CompanyCodeEntity, [FakeResponse(200, [])])
    ent.list(filter={"company_query": "甲"})
    assert tr.calls[0]["params"]["company_query"] == "甲"


def test_company_code_rejects_unknown_filter_key():
    ent, _ = _wire(CompanyCodeEntity, [])
    with pytest.raises(FilterKeyError):
        ent.list(filter={"bogus": "x"})


def test_company_code_read_only():
    ent, _ = _wire(CompanyCodeEntity, [])
    _assert_read_only(ent)


# ============================================================
# M2 · material_category (裸 List, takes no params, 无 get, trailing slash path)
# ============================================================

def test_material_category_list_bare_array():
    ent, tr = _wire(MaterialCategoryEntity, [FakeResponse(200, [{"id": "mc1"}])])
    page = ent.list()
    assert page.items == [{"id": "mc1"}]
    assert page.total == 1
    # 结尾真实斜杠（§6：/material-categories/）。
    assert tr.calls[0]["url"] == _BASE + "/material-categories/"


def test_material_category_takes_no_params():
    # 后端不收任何参数 —— list() 不暴露 filter；调用无 query。
    ent, tr = _wire(MaterialCategoryEntity, [FakeResponse(200, [])])
    ent.list()
    assert tr.calls[0]["params"] in ({}, None)


def test_material_category_list_signature_has_no_filter():
    import inspect
    sig = inspect.signature(MaterialCategoryEntity.list)
    assert "filter" not in sig.parameters
    assert "size" not in sig.parameters


def test_material_category_has_no_get():
    ent, _ = _wire(MaterialCategoryEntity, [])
    assert not hasattr(ent, "get")


def test_material_category_read_only():
    ent, _ = _wire(MaterialCategoryEntity, [])
    _assert_read_only(ent)


# ============================================================
# M2 · exchange_rate (裸 List, 三参必填 → ValueError 不打网络)
# ============================================================

def test_exchange_rate_list_url_and_params():
    ent, tr = _wire(ExchangeRateEntity, [FakeResponse(200, [{"rate": "7.1"}])])
    page = ent.list(
        exchange_rate_type="STANDARD",
        from_currency_code="USD",
        to_currency_code="CNY",
        effective_at_from="2026-01-01",
        effective_at_to="2026-06-01",
    )
    assert page.items == [{"rate": "7.1"}]
    assert page.total == 1
    assert tr.calls[0]["url"] == _BASE + "/mdm/curr-pair-exchange-rates/info"
    p = tr.calls[0]["params"]
    assert p["exchange_rate_type"] == "STANDARD"
    assert p["from_currency_code"] == "USD"
    assert p["to_currency_code"] == "CNY"
    assert p["effective_at_from"] == "2026-01-01"
    assert p["effective_at_to"] == "2026-06-01"


def test_exchange_rate_missing_type_raises_no_network():
    ent, tr = _wire(ExchangeRateEntity, [])  # 无响应：若打网络则 IndexError pop
    with pytest.raises(ValueError):
        ent.list(exchange_rate_type="", from_currency_code="USD", to_currency_code="CNY")
    assert tr.calls == []  # 不打网络


def test_exchange_rate_missing_from_raises():
    ent, tr = _wire(ExchangeRateEntity, [])
    with pytest.raises(ValueError):
        ent.list(exchange_rate_type="STANDARD", from_currency_code=None, to_currency_code="CNY")
    assert tr.calls == []


def test_exchange_rate_missing_to_raises():
    ent, tr = _wire(ExchangeRateEntity, [])
    with pytest.raises(ValueError):
        ent.list(exchange_rate_type="STANDARD", from_currency_code="USD", to_currency_code="")
    assert tr.calls == []


def test_exchange_rate_optional_effective_dates_omitted():
    ent, tr = _wire(ExchangeRateEntity, [FakeResponse(200, [])])
    ent.list(exchange_rate_type="STANDARD", from_currency_code="USD", to_currency_code="CNY")
    p = tr.calls[0]["params"]
    assert "effective_at_from" not in p
    assert "effective_at_to" not in p


def test_exchange_rate_has_no_get():
    ent, _ = _wire(ExchangeRateEntity, [])
    assert not hasattr(ent, "get")


def test_exchange_rate_read_only():
    ent, _ = _wire(ExchangeRateEntity, [])
    _assert_read_only(ent)


# ============================================================
# M2 · product_level (/product-levels/tree 返单 dict → [dict] coerce, valid 切 /valid-tree)
# ============================================================

def test_product_level_tree_single_dict_coerced_to_list():
    # 单 tree root dict（非数组）→ coerce_to_page 包成 [dict], total=1。
    tree = {"id": "root", "name": "产品层级根", "children": [{"id": "c1"}]}
    ent, tr = _wire(ProductLevelEntity, [FakeResponse(200, tree)])
    page = ent.list()
    assert isinstance(page, Page)
    assert page.items == [tree]
    assert page.total == 1
    assert tr.calls[0]["url"] == _BASE + "/product-levels/tree"


def test_product_level_list_array_passthrough():
    # 若后端返 list 则原样（coerce 吃两形）。
    arr = [{"id": "r1"}, {"id": "r2"}]
    ent, _ = _wire(ProductLevelEntity, [FakeResponse(200, arr)])
    page = ent.list()
    assert page.items == arr
    assert page.total == 2


def test_product_level_valid_switches_path():
    tree = {"id": "root"}
    ent, tr = _wire(ProductLevelEntity, [FakeResponse(200, tree)])
    ent.list(valid=True)
    assert tr.calls[0]["url"] == _BASE + "/product-levels/valid-tree"


def test_product_level_q_passthrough():
    ent, tr = _wire(ProductLevelEntity, [FakeResponse(200, {"id": "root"})])
    ent.list(q="电子", valid=True)
    assert tr.calls[0]["params"]["q"] == "电子"


def test_product_level_has_no_get():
    ent, _ = _wire(ProductLevelEntity, [])
    assert not hasattr(ent, "get")


def test_product_level_read_only():
    ent, _ = _wire(ProductLevelEntity, [])
    _assert_read_only(ent)
