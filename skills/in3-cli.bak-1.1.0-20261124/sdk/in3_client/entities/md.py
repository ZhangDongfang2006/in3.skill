"""md 模块 entity：currency（无 get）+ material（list/get）+ M1/M2 主数据扩张。

端点（与 in-mom-md/cli src/commands/*.ts 一致，base = api_host + /mom/md）：
  currency.list  GET /v2/api/tenants/<tid>/mdm/currencies/page?page=&size=[&keyword=&enabled=]
  material.list  GET /v2/api/tenants/<tid>/mdm/materials/page?page=&size=[&material_no=&...]
  material.get   GET /v2/api/tenants/<tid>/mdm/materials/<id>

md.material 过滤键 = material_no/material_name/brand/material_group（**无 material_ids 多值
过滤** → 按 issue #3 约定不挂 _matched_filter_values）。币种归一不在 md（在 sd / #7）。

#12 M1（标准 Spring 分页 simple list/get）：plant / measure_unit / account /
account_contact / sales_organization。
#13 M2（裸数组 bare-array）：company_code（裸 List 有 get）/ material_category（裸 List
无 get、takes no params）/ exchange_rate（裸 List、三参必填 fail-loud）/ product_level
（/tree 返单 dict → [dict] coerce）。bare-array 一律走 PagedEntity._list_bare（绕 normalize
吞数据坑）。
"""
from __future__ import annotations

import re
from typing import Optional

from ..envelope import Page
from ..filters import check_filter_keys
from .base import PagedEntity

# md.material 后端 exhaustive filter_keys（in-mom-md-cli __schema .commands.material.list.filter_keys）。
_MATERIAL_FILTER_KEYS = frozenset({
    "material_query", "material_no", "material_name", "material_desc", "q_text",
    "query_default_supplier", "brand", "customer_no", "material_group", "material_category",
    "valid_status", "material", "old_material_no", "mfr_material_no", "procurement_type",
    "sp_procurement_type", "mrp_type", "created_by_id", "last_modified_by_id", "bom",
    "enable_material_no_length_sort", "exclude_cp_and_xx", "from_last_modified_date",
    "to_last_modified_date", "only_show_valid",
})
# 48 扩展字段 field_a..field_av（--filter field_x=value 透传）—— 按 pattern 放行，不写死。
_MATERIAL_FILTER_PATTERNS = (re.compile(r"^field_[a-z]{1,2}$"),)


class CurrencyEntity(PagedEntity):
    MOD = "md"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/mdm/currencies/page"

    def list(
        self,
        *,
        size: int = 20,
        all: bool = True,
        keyword: Optional[str] = None,
        enabled: Optional[str] = None,
    ) -> Page:
        params: dict = {}
        if keyword is not None:
            params["keyword"] = keyword
        if enabled is not None:
            params["enabled"] = enabled
        return self._list(params, size, all)


class MaterialEntity(PagedEntity):
    MOD = "md"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/mdm/materials/page"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/mdm/materials/{entity_id}"

    def list(self, *, filter: Optional[dict] = None, size: int = 20, all: bool = True) -> Page:
        filter = dict(filter or {})
        check_filter_keys("md.material", filter, _MATERIAL_FILTER_KEYS, patterns=_MATERIAL_FILTER_PATTERNS)
        return self._list(filter, size, all)

    def get(self, entity_id: str) -> dict:
        return self._get(entity_id)


# ============================================================
# #12 M1 · 标准 Spring 分页 simple list / get
# ============================================================

# §6 filter_keys（照文档；live 阶段以 __schema 钉死，见各类 docstring TODO）。
_PLANT_FILTER_KEYS = frozenset({"plant_no", "plant_name", "company_id", "key_word"})
_MEASURE_UNIT_FILTER_KEYS = frozenset({
    "unit_no", "unit_name", "dimension_id", "unit_group_no", "enable", "exclude_unit_group_id",
})
_ACCOUNT_FILTER_KEYS = frozenset({
    "company_id", "account_name", "account_no", "account_type", "payment_type", "keywords",
})
_ACCOUNT_CONTACT_FILTER_KEYS = frozenset({"account_id", "account_name", "fullname"})
_SALES_ORG_FILTER_KEYS = frozenset({
    "sales_organization_code", "sales_organization_name", "key_word", "company_id",
})


class PlantEntity(PagedEntity):
    """md.plant — 工厂主数据，标准 Spring 分页 /plants/page，list-only（后端无 /{id} get）。

    TODO: live md __schema 复核端点单复数/filter_keys（parity 阶段校正）。
    """

    MOD = "md"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/plants/page"

    def list(self, *, filter: Optional[dict] = None, size: int = 20, all: bool = True) -> Page:
        filter = dict(filter or {})
        check_filter_keys("md.plant", filter, _PLANT_FILTER_KEYS)
        return self._list(filter, size, all)


class MeasureUnitEntity(PagedEntity):
    """md.measure_unit — 计量单位，list+get，路径带 /mdm/ 段（与 material 同构）。

    typed flag 真实后端 key 是 `enable`（无 d）—— filter dict 透传时直接用 `enable`，
    传 `enabled` 会被白名单拒（fail-loud）。
    TODO: live md __schema 复核端点单复数/filter_keys（parity 阶段校正）。
    """

    MOD = "md"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/mdm/measure-units/page"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/mdm/measure-units/{entity_id}"

    def list(self, *, filter: Optional[dict] = None, size: int = 20, all: bool = True) -> Page:
        filter = dict(filter or {})
        check_filter_keys("md.measure_unit", filter, _MEASURE_UNIT_FILTER_KEYS)
        return self._list(filter, size, all)

    def get(self, entity_id: str) -> dict:
        return self._get(entity_id)


class AccountEntity(PagedEntity):
    """md.account — 客商账户，list+get，路径 /accounts/page（**无** /mdm/ 段）。

    payment_type 是 multi filter，但 md 无 material_ids 式 fan-out/413 风险 → 普通透传，
    **不挂** _matched_filter_values（照 md.material 约定）。
    TODO: live md __schema 复核端点单复数/filter_keys（parity 阶段校正）。
    """

    MOD = "md"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/accounts/page"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/accounts/{entity_id}"

    def list(self, *, filter: Optional[dict] = None, size: int = 20, all: bool = True) -> Page:
        filter = dict(filter or {})
        check_filter_keys("md.account", filter, _ACCOUNT_FILTER_KEYS)
        return self._list(filter, size, all)

    def get(self, entity_id: str) -> dict:
        return self._get(entity_id)


class AccountContactEntity(PagedEntity):
    """md.account_contact — 客商联系人，标准分页 /account-contacts/page，list-only（无 /{id} get）。

    TODO: live md __schema 复核端点单复数/filter_keys（parity 阶段校正）。
    """

    MOD = "md"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/account-contacts/page"

    def list(self, *, filter: Optional[dict] = None, size: int = 20, all: bool = True) -> Page:
        filter = dict(filter or {})
        check_filter_keys("md.account_contact", filter, _ACCOUNT_CONTACT_FILTER_KEYS)
        return self._list(filter, size, all)


class SalesOrganizationEntity(PagedEntity):
    """md.sales_organization — 销售组织，标准分页 /sales-organizations/page（无 /mdm/ 段），list-only。

    搜索 key 是 `key_word`（带下划线），不是 `keyword`。
    TODO: live md __schema 复核端点单复数/filter_keys（parity 阶段校正）。
    """

    MOD = "md"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/sales-organizations/page"

    def list(self, *, filter: Optional[dict] = None, size: int = 20, all: bool = True) -> Page:
        filter = dict(filter or {})
        check_filter_keys("md.sales_organization", filter, _SALES_ORG_FILTER_KEYS)
        return self._list(filter, size, all)


# ============================================================
# #13 M2 · 裸数组 bare-array（走 _list_bare → coerce_to_page，绕 normalize 吞数据坑）
# ============================================================

_COMPANY_CODE_FILTER_KEYS = frozenset({"company_query"})


class CompanyCodeEntity(PagedEntity):
    """md.company_code — 公司代码，后端 /company-codes/list 返**裸 JSON 数组**（非 Spring Page），但有 get。

    裸数组走 _list_bare（http._request 拿原值 → coerce_to_page 包 Page），不经 normalize
    （裸 list 喂 normalize 会抛 AttributeError / 空数组被 get_json 的 `or {}` 吞成 {}）。
    一次全量、无分页 → list() 不带 size/all（带了也无意义）。
    TODO: live md __schema 复核端点单复数/filter_keys（parity 阶段校正）。
    """

    MOD = "md"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/company-codes/list"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/company-codes/{entity_id}"

    def list(self, *, filter: Optional[dict] = None) -> Page:
        filter = dict(filter or {})
        check_filter_keys("md.company_code", filter, _COMPANY_CODE_FILTER_KEYS)
        return self._list_bare(filter, size=0, all_pages=False)

    def get(self, entity_id: str) -> dict:
        return self._get(entity_id)


class MaterialCategoryEntity(PagedEntity):
    """md.material_category — 物料类目，/material-categories/（**结尾真实斜杠**）返裸 List，无 get。

    后端 takes no params（schema filter_keys 为空）→ list() **不暴露任何过滤参数**，避免假装可过滤。
    走 _list_bare 包 Page；list-only 诚实不假装 get。
    TODO: live md __schema 复核端点单复数/trailing-slash（parity 阶段校正）。
    """

    MOD = "md"

    def _list_path(self, tenant_id: str) -> str:
        # 结尾斜杠是真实的（§6）—— 别去掉。
        return f"/v2/api/tenants/{tenant_id}/material-categories/"

    def list(self) -> Page:
        return self._list_bare(None, size=0, all_pages=False)


class ExchangeRateEntity(PagedEntity):
    """md.exchange_rate — 币对汇率，/mdm/curr-pair-exchange-rates/info 返裸 List；**三参必填**。

    exchange_rate_type / from_currency_code / to_currency_code 缺任一 → 前置 raise ValueError
    （fail-loud，**不打网络**，别让后端回 500/空）。三参用具名必填参数（非 filter dict）。
    effective_at_from/to 是 date（YYYY-MM-DD），可选；走 _list_bare 包 Page。
    TODO: live md __schema 复核端点单复数/filter_keys（parity 阶段校正）。
    """

    MOD = "md"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/mdm/curr-pair-exchange-rates/info"

    def list(
        self,
        *,
        exchange_rate_type: str,
        from_currency_code: str,
        to_currency_code: str,
        effective_at_from: Optional[str] = None,
        effective_at_to: Optional[str] = None,
    ) -> Page:
        # fail-loud：三参非空才打网络（CLI 在发 HTTP 前就 VALIDATION 拒缺参）。
        missing = [
            name
            for name, val in (
                ("exchange_rate_type", exchange_rate_type),
                ("from_currency_code", from_currency_code),
                ("to_currency_code", to_currency_code),
            )
            if not val
        ]
        if missing:
            raise ValueError(
                f"md.exchange_rate.list() 缺必填参数 {missing} —— "
                "exchange_rate_type/from_currency_code/to_currency_code 三参均必填（不发空查询）。"
            )
        params: dict = {
            "exchange_rate_type": exchange_rate_type,
            "from_currency_code": from_currency_code,
            "to_currency_code": to_currency_code,
        }
        if effective_at_from is not None:
            params["effective_at_from"] = effective_at_from
        if effective_at_to is not None:
            params["effective_at_to"] = effective_at_to
        return self._list_bare(params, size=0, all_pages=False)


class ProductLevelEntity(PagedEntity):
    """md.product_level — 产品层级，/product-levels/tree 返**单个 tree root dict**（非数组）。

    coerce_to_page 吃 list|dict 两形：拿到 dict 包 [tree]（total=1）、拿到 list 原样。
    valid=True 切 /product-levels/valid-tree（过滤无效节点）；q 文本过滤透传（不强校验）。
    list-only（无 get）。
    TODO: live md __schema 复核端点单复数/filter_keys（parity 阶段校正）。
    """

    MOD = "md"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._valid = False  # list(valid=True) 时切 /valid-tree（_list_path 据此选段）。

    def _list_path(self, tenant_id: str) -> str:
        leaf = "valid-tree" if self._valid else "tree"
        return f"/v2/api/tenants/{tenant_id}/product-levels/{leaf}"

    def list(self, *, q: Optional[str] = None, valid: bool = False) -> Page:
        # valid 切 /valid-tree；复用 _list_bare 的 dict→[dict] coerce 包形。
        self._valid = valid
        try:
            params: dict = {}
            if q is not None:
                params["q"] = q
            return self._list_bare(params, size=0, all_pages=False)
        finally:
            self._valid = False
