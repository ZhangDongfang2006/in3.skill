"""sd 模块 entity。v1 #3 落 sales_order_item（**仅 list**——后端无 /{id}，忠实不假装）。

端点（ibrain-sd/cli src/commands/sales-order-item.ts，base = api_host + /mom/sd）：
  list  GET /v2/api/tenants/<tid>/sales-orders/items/page?page=&size=[&so_no=&so_id=&material_id=&plant_id=]

币种归一（story 17，156↔CNY 表示归一，不换汇）：真实 SOI 币种字段是数值 ISO 形
`local_currency_no` / `original_currency_no`（值如 "156"）。**非破坏性**——保留原 `*_no`
字段不动（字段名断言它装数字，就地覆盖成 "CNY" 会损坏语义 + 与 CLI parity 假性不一致），
旁挂归一后的字母 companion（去掉尾 `_no`）：`local_currency_no` → `local_currency`="CNY"，
供 #7 跨模块 join/对账用。需注入 currency_index（来自 md.currency，由 IN3 门面装配）；
无字典则原样穿过，不炸。
"""
from __future__ import annotations

import re
from typing import Optional

from ..auth import Session
from ..config import Credentials
from ..envelope import Page, coerce_to_page
from ..filters import check_filter_keys
from ..gotchas import enrich_items_fanout, normalize_currency
from ..http import HttpClient
from .base import PagedEntity, PostPagedEntity

# 真实 SOI 上的数值-ISO 币种字段（值如 "156"）。companion = 去掉尾 "_no"。
_CURRENCY_NO_FIELDS = ("local_currency_no", "original_currency_no")

# sd.sales-order-item 后端 exhaustive filter_keys（ibrain-sd-cli __schema .commands."sales-order-item".list.filter_keys）。
_SOI_FILTER_KEYS = frozenset({
    "company_id", "sales_organization_id", "distribution_channel_id", "division_id",
    "plant_id", "ct_query", "so_query", "type", "material_id", "status", "account_id",
    "sales_dept_id", "ordered_by", "created_by", "start_transfer_date", "end_transfer_date",
    "from_ordered_at", "to_ordered_at", "from_required_delivery_date", "to_required_delivery_date",
    "from_committed_delivery_date", "to_committed_delivery_date", "so_type", "only_has_draft",
    "with_data_role", "shipped_status", "from_fst_issue_at", "to_fst_issue_at",
    "from_last_issue_at", "to_last_issue_at", "delivery_group_no", "invoice_order_ref",
    "return_flag",
})
# 租户特定扩展列 column_a..column_u —— 按 pattern 放行。
_SOI_FILTER_PATTERNS = (re.compile(r"^column_[a-z]$"),)


def _attach_currency_companions(items: list, currency_index: Optional[dict]) -> list:
    """非破坏性币种归一：原 `*_no` 字段不动，旁挂去 `_no` 的 alpha companion。

    无 index 或字段不在场 → 原样穿过（不臆造 companion）。SOI 与 contract-item 复用同一逻辑。
    """
    if not currency_index:
        return items
    for it in items:
        for f in _CURRENCY_NO_FIELDS:
            if it.get(f) is not None:
                it[f[:-3]] = normalize_currency(it[f], currency_index)  # 旁挂，不动原字段
    return items


class SalesOrderItemEntity(PagedEntity):
    MOD = "sd"

    def __init__(
        self,
        cred: Credentials,
        session: Session,
        http: HttpClient,
        currency_index: Optional[dict] = None,
    ):
        super().__init__(cred, session, http)
        self._currency_index = currency_index

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/sales-orders/items/page"

    def _normalize_currency_fields(self, items: list) -> list:
        return _attach_currency_companions(items, self._currency_index)

    def list(self, *, filter: Optional[dict] = None, size: int = 20, all: bool = True) -> Page:
        filter = dict(filter or {})
        check_filter_keys("sd.sales_order_item", filter, _SOI_FILTER_KEYS, patterns=_SOI_FILTER_PATTERNS)
        return self._list(filter, size, all, transform=self._normalize_currency_fields)


# ===========================================================================
# M1（issue #12 §6 行 642-696）：simple-list-get 实体
# 端点单复数/path 段/filter_keys 照 §6 文档写，live __schema 校正阶段复核（见各 docstring TODO）。
# ===========================================================================


class SalesDeptEntity(PagedEntity):
    """sd.sales_dept：销售部门。单数 path /sales-dept（**裸 collection**，无 /page）。

    parity 实测（zhuzheng/99979）：`/sales-dept/page` 与 `/sales-dept/list` 两种方法均 405；
    真实端点是 **GET /v2/api/tenants/<tid>/sales-dept**（裸数组，无分页信封）。CLI 用 /page 故
    自身也 405——旧 shipped CLI 端点同样错（**已于 ibrain-sd-cli v0.2.8 同步修对裸端点**，2026-06-04 aquaman live parity 通过）。改走 _list_bare（http._request 拿原始 list → coerce_to_page）。
    后端无 @RequestParam filter——只发裸 GET，不挂任何 typed filter。
    """

    MOD = "sd"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/sales-dept"  # SINGULAR bare collection（无 /page）

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/sales-dept/{entity_id}"

    def list(self, *, size: int = 20, all: bool = True) -> Page:
        return self._list_bare({}, size, all)

    def get(self, entity_id: str) -> dict:
        return self._get(entity_id)


class ContractCategoryEntity(PagedEntity):
    """sd.contract_category：合同类目。plural path /contract-categories（**裸 collection**，无 /page）。

    parity 实测（zhuzheng/99979）：`/contract-categories/page` GET/POST 均 405；真实端点是
    **GET /v2/api/tenants/<tid>/contract-categories**（裸数组，无分页信封）。CLI 用 /page 故自身
    也 405——旧 shipped CLI 端点同样错（**已于 ibrain-sd-cli v0.2.8 同步修对裸端点**，2026-06-04 aquaman live parity 通过）。改走 _list_bare。唯一 filter `status` 是 **integer**（作 query 透传）。
    """

    MOD = "sd"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/contract-categories"  # 裸 collection（无 /page）

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/contract-categories/{entity_id}"

    def list(self, *, status: Optional[int] = None, size: int = 20, all: bool = True) -> Page:
        params: dict = {}
        if status is not None:
            params["status"] = status  # int 透传，不 str 化
        return self._list_bare(params, size, all)

    def get(self, entity_id: str) -> dict:
        return self._get(entity_id)


class SoItemCategoryEntity(PagedEntity):
    """sd.so_item_category：销售订单行类目。单数 path /so-item-category（**裸 collection**，无 /page）。

    parity 实测（zhuzheng/99979）：`/so-item-category/page` 与 `/so-item-category/list` 均 405；
    真实端点是 **GET /v2/api/tenants/<tid>/so-item-category**（裸数组，无分页信封，zhuzheng 现有
    1 条 ZTA 默认订单行类别）。CLI 用 /page 故自身也 405——旧 shipped CLI 端点同样错（**已于 ibrain-sd-cli v0.2.8 同步修对裸端点**，2026-06-04 aquaman live parity 通过）。改走 _list_bare。
    唯一 filter `status` 是 **integer**（作 query 透传）。
    """

    MOD = "sd"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/so-item-category"  # SINGULAR bare collection（无 /page）

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/so-item-category/{entity_id}"

    def list(self, *, status: Optional[int] = None, size: int = 20, all: bool = True) -> Page:
        params: dict = {}
        if status is not None:
            params["status"] = status  # int 透传
        return self._list_bare(params, size, all)

    def get(self, entity_id: str) -> dict:
        return self._get(entity_id)


class DeliveryGroupNoEntity(PagedEntity):
    """sd.delivery_group_no：发货组号段。plural path /delivery-group-nos/page（-nos 复数）。

    4 个 filter 全是 plain snake_case 字符串（so_id/group_no/group_name/query），无 multi/date。
    §6 标其有 list+get（虽是「号段」概念），按 §6 实现 get，不臆断为 list-only。
    TODO: live sd __schema 复核端点单复数/filter_keys（parity 阶段校正）。
    """

    MOD = "sd"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/delivery-group-nos/page"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/delivery-group-nos/{entity_id}"

    def list(
        self,
        *,
        so_id: Optional[str] = None,
        group_no: Optional[str] = None,
        group_name: Optional[str] = None,
        query: Optional[str] = None,
        size: int = 20,
        all: bool = True,
    ) -> Page:
        params: dict = {}
        if so_id is not None:
            params["so_id"] = so_id
        if group_no is not None:
            params["group_no"] = group_no
        if group_name is not None:
            params["group_name"] = group_name
        if query is not None:
            params["query"] = query
        return self._list(params, size, all)

    def get(self, entity_id: str) -> dict:
        return self._get(entity_id)


# sd.sd_info_record 后端 filter_keys（§6 行 645）。--customer 映射到 account_id；
# --plant 透传 plant_id 但后端可能静默忽略（不承诺生效）。
_SD_INFO_RECORD_FILTER_KEYS = frozenset({
    "account_id", "material_id", "account_material_no", "account_material_name", "status", "plant_id",
})


class SdInfoRecordEntity(PagedEntity):
    """sd.sd_info_record：销售信息记录。

    坑（§6 行 642-650）：
      - 后端 path **丢 sd- 前缀** → /info-records/page 与 /info-records/{id}（与命令名 sd-info-record 不符）。
      - `--customer` 映射到后端 `account_id`。
      - `--plant` 透传 plant_id 但后端可能静默忽略——透传不承诺生效。
    TODO: live sd __schema 复核端点单复数/filter_keys（parity 阶段校正）。
    """

    MOD = "sd"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/info-records/page"  # 丢 sd- 前缀

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/info-records/{entity_id}"

    def list(
        self,
        *,
        filter: Optional[dict] = None,
        customer: Optional[str] = None,
        material: Optional[str] = None,
        plant: Optional[str] = None,
        size: int = 20,
        all: bool = True,
    ) -> Page:
        params: dict = dict(filter or {})
        if customer is not None:
            params["account_id"] = customer  # --customer → account_id
        if material is not None:
            params["material_id"] = material
        if plant is not None:
            params["plant_id"] = plant  # 透传，后端可能静默忽略（不承诺）
        check_filter_keys("sd.sd_info_record", params, _SD_INFO_RECORD_FILTER_KEYS)
        return self._list(params, size, all)

    def get(self, entity_id: str) -> dict:
        return self._get(entity_id)


class DeliveryReceiptTypeEntity(PagedEntity):
    """sd.delivery_receipt_type：发货回执类型。plural path /delivery-receipt-types/page。

    坑（§6 行 678-685）：
      - filter key 是 camelCase 字面量 `queryText`（**不是** query_text，与 pp 的 materialIds 同类陷阱）。
      - `status` 是 **integer**。
    TODO: live sd __schema 复核端点单复数/filter_keys（parity 阶段校正）。
    """

    MOD = "sd"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/delivery-receipt-types/page"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/delivery-receipt-types/{entity_id}"

    def list(
        self,
        *,
        query_text: Optional[str] = None,
        status: Optional[int] = None,
        size: int = 20,
        all: bool = True,
    ) -> Page:
        params: dict = {}
        if query_text is not None:
            params["queryText"] = query_text  # camelCase 字面量
        if status is not None:
            params["status"] = status  # int 透传
        return self._list(params, size, all)

    def get(self, entity_id: str) -> dict:
        return self._get(entity_id)


class DeliveryReceiptValidationError(Exception):
    """delivery_receipt 入参校验失败（list 的 company_id 必填，后端 @RequestParam）。

    在任何网络调用之前抛（mirror CLI VALIDATION exit）——坏参不打到后端。
    """


# delivery_receipt（header）后端 filter_keys（§6 行 634）。company_id 在 list 必填（list 层强制）；
# receipt_date_from/to 是 plain DATE（区别于业务单据的 datetime ISO）；
# receipt_status/receipt_type_id/receipt_category 多值（list 透传成 repeated query）。
_DELIVERY_RECEIPT_FILTER_KEYS = frozenset({
    "company_id", "account_id", "so_id", "receipt_status", "receipt_type_id",
    "receipt_category", "receipt_no", "receipt_date_from", "receipt_date_to",
})


class DeliveryReceiptEntity(PagedEntity):
    """sd.delivery_receipt：收货单 header。simple-list-get（§6 行 631-640，2pt）。

    坑：
      - **company_id 在 list 必填**（后端 @RequestParam）——`company` 缺失 → raise
        DeliveryReceiptValidationError（**不打网络**，mirror CLI VALIDATION exit）。get 不需要 company。
      - receipt_date_from/to 是 **plain DATE**（YYYY-MM-DD），不是 datetime ISO（区别于 sales_order/
        contract-item 面——别照搬日期类型）。
      - receipt_status / receipt_type_id / receipt_category **多值**（list 透传成 repeated query，量小
        不触发 chunk）。
      - path：list /delivery-receipts/page、get /delivery-receipts/{dr_id}（plural）。
    TODO: live sd __schema 复核端点单复数/filter_keys + company_id 必填行为（parity 阶段校正）。
    """

    MOD = "sd"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/delivery-receipts/page"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/delivery-receipts/{entity_id}"

    def list(
        self,
        *,
        company: Optional[str] = None,
        filter: Optional[dict] = None,
        account: Optional[str] = None,
        so_id: Optional[str] = None,
        receipt_no: Optional[str] = None,
        receipt_status=None,
        size: int = 20,
        all: bool = True,
    ) -> Page:
        # company_id 必填——缺失先 raise（绝不打网络）。
        if company is None:
            raise DeliveryReceiptValidationError(
                "delivery_receipt.list 必须传 company（后端 company_id 为必填 @RequestParam）"
            )
        params: dict = dict(filter or {})
        params["company_id"] = company
        if account is not None:
            params["account_id"] = account  # --account → account_id
        if so_id is not None:
            params["so_id"] = so_id
        if receipt_no is not None:
            params["receipt_no"] = receipt_no
        if receipt_status is not None:
            params["receipt_status"] = receipt_status  # 多值 list 透传
        check_filter_keys("sd.delivery_receipt", params, _DELIVERY_RECEIPT_FILTER_KEYS)
        return self._list(params, size, all)

    def get(self, entity_id: str) -> dict:
        return self._get(entity_id)


# ===========================================================================
# M2（issue #13 §6 行 697-705）：bare/list-only 实体
# contract_item 是 list-only paged（/contracts/items/page 有 /page，走 _list 非 _list_bare），
# 后端无 /{id}——忠实不假装 get（照 sales_order_item 诚实）。
# ===========================================================================

# sd.contract_item 后端 filter_keys（§6 行 699）。--customer 映射 account_id。
# signed_date_start/end 是 datetime ISO（区别于 contract-header 的 plain date）。
_CONTRACT_ITEM_FILTER_KEYS = frozenset({
    "account_id", "contract_no", "status", "execute_status", "type", "project_name",
    "signed_date_start", "signed_date_end",
})


class ContractItemEntity(PagedEntity):
    """sd.contract_item：合同行项。**list-only**（后端 /contracts/items/page 无 /{id}）。

    坑（§6 行 697-705）：
      - LIST-ONLY——**不**加 get()，照 sales_order_item 诚实。
      - 共享 contract list filter 面（contract_no/account 跨表头筛选）；`--customer` → `account_id`。
      - signed_date_start/end 是 **datetime ISO**（区别于 contract-HEADER 的 plain date——不照搬日期类型）。
      - currency companion：行项**可能**带 local_currency_no/original_currency_no；若注入 index 且字段
        在场则旁挂 alpha companion（与 sales_order_item 同），缺则跳过不臆造（§6 line 704）。
    TODO: live sd __schema 复核端点单复数/filter_keys（parity 阶段校正）+ live 数据复核
          local_currency_no 字段是否真在场（缺则该 companion 永不触发，符合预期）。
    """

    MOD = "sd"

    def __init__(
        self,
        cred: Credentials,
        session: Session,
        http: HttpClient,
        currency_index: Optional[dict] = None,
    ):
        super().__init__(cred, session, http)
        self._currency_index = currency_index

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/contracts/items/page"

    def _normalize_currency_fields(self, items: list) -> list:
        return _attach_currency_companions(items, self._currency_index)

    def list(
        self,
        *,
        filter: Optional[dict] = None,
        contract_no: Optional[str] = None,
        customer: Optional[str] = None,
        size: int = 20,
        all: bool = True,
    ) -> Page:
        params: dict = dict(filter or {})
        if contract_no is not None:
            params["contract_no"] = contract_no
        if customer is not None:
            params["account_id"] = customer  # --customer → account_id
        check_filter_keys("sd.contract_item", params, _CONTRACT_ITEM_FILTER_KEYS)
        return self._list(params, size, all, transform=self._normalize_currency_fields)


# ===========================================================================
# M3（issue #14 §6 行 605/619/707/719）：业务单据最重坑层。
# fanout-gotcha（sales_order/contract/quotation）+ dual-source list-only（delivery_receipt_item）。
# 端点单复数/path 段/filter_keys 照 §6 文档写，live <cli> __schema 校正阶段复核（各 docstring TODO）。
# ===========================================================================

# per-header include_items fan-out 并发上限（与 CLI / gotchas.enrich_items_fanout 默认一致）。
_INCLUDE_ITEMS_CONCURRENCY = 5
# 逐 header 取行项时拉一大页（CLI 约定 size=1000，避免行项被默认页大小截断）。
_ITEMS_FETCH_SIZE = 1000


# sd.sales_order 后端 filter_keys（§6 行 605）。--customer→account_id；时间是 datetime ISO。
# status/shipped_status/so_type/type 是 multi-valued（repeated query param，SDK 透传单/多值字符串）。
_SALES_ORDER_FILTER_KEYS = frozenset({
    "status", "account_id", "so_query", "so_id", "company_id", "sales_organization_id",
    "material_id", "from_ordered_at", "to_ordered_at", "start_transfer_date", "shipped_status",
    "delivery_group_no", "contract_no", "plant_id",
})


class SalesOrderEntity(PagedEntity):
    """sd.sales_order：销售订单表头。**fanout-gotcha**（§6 行 605，5pt 最重）。

    路由（GET 分页，**不是** POST——区别于 sd.quotation / pp.* 的 POST-body list）：
      - list GET /sales-orders/page（filter 进 query）
      - get  GET /sales-orders/{so_id}

    坑（§6 行 605，逐条对齐 CLI）：
      - **include_items 无 bulk 端点**（不同于 mm.PO 的 bulk-get-by-po）：按 header 逐条 fan-out
        GET /sales-orders/items/page?so_id=<id>&size=1000，concurrency=5，走 gotchas.enrich_items_fanout
        （**fail-isolated**：单 header 失败 → 该 header items=None + items_error，**绝不冒泡**；
        与 mm.PO 的 fail-loud bulk-get 是相反 fail-mode）。
      - get detail 行项以 `products[]` 返回 → alias `products[]`→`items[]`（**仅 items 缺时**，
        mirror CLI aliasProductsAsItems；items 已存在不覆盖）。
      - get(include_items=True)：用专用 /sales-orders/items/page?so_id 抓 fresh 行项 **REPLACE**
        inline products alias（专用端点覆盖 inline alias）。
      - **header total_amount/local_total_amount 不可信**（后端常返 0）：金额须从 items[] 求和，
        **不要**信 header 金额。
      - 时间 filter from_ordered_at/to_ordered_at/start_transfer_date 是 datetime ISO
        YYYY-MM-DDTHH:mm:ss（区别于 mm 的 plain date）——SDK 透传不强转。
      - 含币种 local_currency_no/original_currency_no → 旁挂 alpha companion（同 sales_order_item）。
    TODO: live sd __schema 复核端点单复数/filter_keys（parity 阶段校正）。
    """

    MOD = "sd"

    def __init__(
        self,
        cred: Credentials,
        session: Session,
        http: HttpClient,
        currency_index: Optional[dict] = None,
    ):
        super().__init__(cred, session, http)
        self._currency_index = currency_index

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/sales-orders/page"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/sales-orders/{entity_id}"

    def _items_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/sales-orders/items/page"

    def _normalize_currency_fields(self, items: list) -> list:
        return _attach_currency_companions(items, self._currency_index)

    def _fetch_items_for_so(self, so_id: str) -> list:
        """取单个 SO 的行项（专用 items 端点，size=1000 大页）——给 include_items fan-out / get 复用。"""
        url = self._base() + self._items_path(self._tenant_id())
        page = self._http.get_page(
            url, {"so_id": so_id, "page": "0", "size": str(_ITEMS_FETCH_SIZE)},
            requested_size=_ITEMS_FETCH_SIZE,
        )
        return self._normalize_currency_fields(page.items)

    def list(
        self,
        *,
        filter: Optional[dict] = None,
        plant: Optional[str] = None,
        status: Optional[str] = None,
        customer: Optional[str] = None,
        include_items: bool = False,
        size: int = 20,
        all: bool = True,
    ) -> Page:
        params: dict = dict(filter or {})
        if plant is not None:
            params["plant_id"] = plant
        if status is not None:
            params["status"] = status
        if customer is not None:
            params["account_id"] = customer  # --customer → account_id
        check_filter_keys("sd.sales_order", params, _SALES_ORDER_FILTER_KEYS)
        page = self._list(params, size, all, transform=self._normalize_currency_fields)
        if include_items:
            # per-header fail-isolated fan-out（concurrency=5）：失败 header 留 items=None+items_error。
            page.items = enrich_items_fanout(
                page.items,
                lambda h: self._fetch_items_for_so(h.get("so_id") or h.get("id")),
                concurrency=_INCLUDE_ITEMS_CONCURRENCY,
            )
        return page

    def get(self, so_id: str, *, include_items: bool = False) -> dict:
        rec = self._get(so_id)
        if include_items:
            # 专用 items 端点 REPLACE inline products alias（fresh 行项覆盖 inline）。
            rec["items"] = self._fetch_items_for_so(so_id)
        elif "items" not in rec and isinstance(rec.get("products"), list):
            # alias-if-absent：products[] → items[]，原 products 不动。
            rec["items"] = rec["products"]
        return rec


# sd.contract 后端 filter_keys（§6 行 619）。--customer→account_id（**NOT** customer_id）；
# signed_date_start/end 是 **plain date**（区别于 contract-ITEM 的 datetime ISO，不可混）。
_CONTRACT_FILTER_KEYS = frozenset({
    "account_id", "status", "execute_status", "contract_no", "project_name", "ct_query",
    "type", "signed_date_start", "signed_date_end", "category_id",
})


class ContractEntity(PagedEntity):
    """sd.contract：销售合同表头。**fanout-gotcha**（§6 行 619，3pt）。

    路由（GET 分页）：list GET /contracts/page；get GET /contracts/{contract_id}。

    坑（§6 行 619，逐条对齐 CLI）：
      - `--customer` → 后端 `account_id`（**NOT** customer_id——同 sd_info_record/quotation 的 account_id quirk）。
      - include_items：按 header 逐条 fan-out GET /contracts/items/page?contract_id=<id>&size=1000
        concurrency=5，**fail-isolated**（复用 gotchas.enrich_items_fanout，同 sales_order）。
      - get(include_items=True)：从 /contracts/items/page 抓行项 **plain APPEND** 到 items
        （contract get detail **无** products alias——区别于 sales_order 的 alias-first）。
      - contract HEADER 时间 signed_date_start/end 是 **plain date**；contract-ITEM 用 datetime ISO
        ——**不可混**两套 surface（§6 反复强调）。
      - 含币种 → 旁挂 alpha companion（同 sales_order_item）。
    TODO: live sd __schema 复核端点单复数/filter_keys（parity 阶段校正）。
    """

    MOD = "sd"

    def __init__(
        self,
        cred: Credentials,
        session: Session,
        http: HttpClient,
        currency_index: Optional[dict] = None,
    ):
        super().__init__(cred, session, http)
        self._currency_index = currency_index

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/contracts/page"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/contracts/{entity_id}"

    def _items_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/contracts/items/page"

    def _normalize_currency_fields(self, items: list) -> list:
        return _attach_currency_companions(items, self._currency_index)

    def _fetch_items_for_contract(self, contract_id: str) -> list:
        url = self._base() + self._items_path(self._tenant_id())
        page = self._http.get_page(
            url, {"contract_id": contract_id, "page": "0", "size": str(_ITEMS_FETCH_SIZE)},
            requested_size=_ITEMS_FETCH_SIZE,
        )
        return self._normalize_currency_fields(page.items)

    def list(
        self,
        *,
        filter: Optional[dict] = None,
        customer: Optional[str] = None,
        status: Optional[str] = None,
        category: Optional[str] = None,
        include_items: bool = False,
        size: int = 20,
        all: bool = True,
    ) -> Page:
        params: dict = dict(filter or {})
        if customer is not None:
            params["account_id"] = customer  # --customer → account_id (NOT customer_id)
        if status is not None:
            params["status"] = status
        if category is not None:
            params["category_id"] = category  # 关联 contract-category
        check_filter_keys("sd.contract", params, _CONTRACT_FILTER_KEYS)
        page = self._list(params, size, all, transform=self._normalize_currency_fields)
        if include_items:
            page.items = enrich_items_fanout(
                page.items,
                lambda h: self._fetch_items_for_contract(h.get("contract_id") or h.get("id")),
                concurrency=_INCLUDE_ITEMS_CONCURRENCY,
            )
        return page

    def get(self, contract_id: str, *, include_items: bool = False) -> dict:
        rec = self._get(contract_id)
        if include_items:
            # plain APPEND（无 products alias）——区别于 sales_order 的 alias-first/replace。
            rec["items"] = self._fetch_items_for_contract(contract_id)
        return rec


# sd.quotation 后端 filter_keys（§6 行 707）。DTO 用 `acc_name`（**不是** customer_id）；
# quotation_date_*/lock_date_* 是 datetime ISO，order_predict_year_* 是 integer。
_QUOTATION_FILTER_KEYS = frozenset({
    "acc_name", "quotation_no", "quotation_name", "status", "approval_status", "project_no",
    "project_name", "quotation_date_start", "quotation_date_end", "lock_date_start", "lock_date_end",
    "order_predict_year_start", "order_predict_year_end",
})


class QuotationEntity(PostPagedEntity):
    """sd.quotation：报价单。**fanout-gotcha**（§6 行 707，3pt）。

    路由分裂（list 与 get 走**不同** transport，不能共用单一 base）：
      - list **POST** /quotations/page（filter 进 JSON body、page/size 进 query；继承 PostPagedEntity，
        **绝不**退回 GET 的 PagedEntity._list）。
      - get  **GET**  /quotations/{id}（plain GET）。

    坑（§6 行 707，逐条对齐 CLI）：
      - quotation DTO 用 `acc_name`（account name），**不是** customer_id——`--customer` 映射到 body
        `acc_name`（typed flag → DTO 真实字段）。
      - get detail 行项以 `quotation_item_details[]` 返回 → alias →`items[]`（**仅 items 缺时**，
        mirror CLI aliasItemDetailsAsItems；items 已存在不覆盖）。
      - 时间 filter quotation_date_start/end / lock_date_start/end 是 datetime ISO（透传不强转）。
      - 含币种 → 旁挂 alpha companion（同 sales_order_item）。
    TODO: live sd __schema 复核端点单复数/filter_keys（parity 阶段校正）。
    """

    MOD = "sd"

    def __init__(
        self,
        cred: Credentials,
        session: Session,
        http: HttpClient,
        currency_index: Optional[dict] = None,
    ):
        super().__init__(cred, session, http)
        self._currency_index = currency_index

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/quotations/page"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/quotations/{entity_id}"

    def _normalize_currency_fields(self, items: list) -> list:
        return _attach_currency_companions(items, self._currency_index)

    def list(
        self,
        *,
        filter: Optional[dict] = None,
        status: Optional[str] = None,
        customer: Optional[str] = None,
        quotation_no: Optional[str] = None,
        size: int = 20,
        all: bool = True,
    ) -> Page:
        body: dict = dict(filter or {})
        if status is not None:
            body["status"] = status
        if customer is not None:
            body["acc_name"] = customer  # --customer → DTO acc_name（NOT customer_id）
        if quotation_no is not None:
            body["quotation_no"] = quotation_no
        check_filter_keys("sd.quotation", body, _QUOTATION_FILTER_KEYS)
        # POST-body 分页（PostPagedEntity._list）：filter 进 body、page/size 进 query。
        return self._list(body, size, all, transform=self._normalize_currency_fields)

    def get(self, quotation_id: str) -> dict:
        rec = self._get(quotation_id)
        if "items" not in rec and isinstance(rec.get("quotation_item_details"), list):
            # alias-if-absent：quotation_item_details[] → items[]，原字段不动。
            rec["items"] = rec["quotation_item_details"]
        return rec


class DeliveryReceiptItemValidationError(Exception):
    """delivery_receipt_item 入参校验失败（三必填参 company_id/ps_flag/account_id 缺任一）。

    在任何网络调用之前抛（mirror CLI VALIDATION exit）——坏参不打到后端。
    """


# source → dual-source path 段（§6 行 719）。'so' 默认，'material-doc' 走另一端点。
_DRI_SOURCE_PATHS = {
    "so": "by-so-items/list",
    "material-doc": "by-material-doc-items/list",
}


class DeliveryReceiptItemEntity:
    """sd.delivery_receipt_item：送货回执行项。**list-only**（§6 行 719，3pt）。

    **不**继承 PagedEntity——后端返裸 List<>（无 Spring Page 信封、无分页），且无 /{id} get。

    坑（§6 行 719，逐条对齐 CLI）：
      - **三必填参** company_id / ps_flag / account_id 全是 @RequestParam 必填——缺任一
        → raise DeliveryReceiptItemValidationError（**不打网络**，mirror CLI VALIDATION exit）。
      - **dual-source**：source='so'（默认）→ GET /delivery-receipts/by-so-items/list；
        source='material-doc' → GET /delivery-receipts/by-material-doc-items/list（参数化 path 段）。
      - 后端返**裸 List<>**（NOT Page）→ 自包成 wrapper Page(items, total=len, source=...)
        （走 envelope.coerce_to_page 包裸数组，再旁挂 source marker；**不**走 get_page/normalize）。
      - **无分页**（单 GET、无 --all、不翻页）；**无 .get**（list-only，忠实不假装）。
      - doc_no/to_no/storage_location_id/material_id/to_date_*/posting_date_* 仅 material-doc source
        有意义——source='so' 时不强行注入（调用方经 filter 透传，SDK 不主动塞）。
    TODO: live sd __schema 复核端点 path 段/必填参/material-doc-only filter（parity 阶段校正）。
    """

    MOD = "sd"

    def __init__(
        self,
        cred: Credentials,
        session: Session,
        http: HttpClient,
        currency_index: Optional[dict] = None,
    ):
        # currency_index 形参对齐 facade 统一装配签名（本实体当前不挂币种 companion，
        # 行项币种归一留 parity 阶段按 live 字段补——不臆造）。
        self._cred = cred
        self._session = session
        self._http = http
        self._currency_index = currency_index

    def _url(self, source: str) -> str:
        tid = self._session.token().tenant_id
        seg = _DRI_SOURCE_PATHS[source]
        return self._cred.base_url(self.MOD) + f"/v2/api/tenants/{tid}/delivery-receipts/{seg}"

    def list(
        self,
        *,
        source: str = "so",
        company: Optional[str] = None,
        ps_flag: Optional[str] = None,
        account: Optional[str] = None,
        so_id: Optional[str] = None,
        filter: Optional[dict] = None,
    ) -> Page:
        if source not in _DRI_SOURCE_PATHS:
            raise DeliveryReceiptItemValidationError(
                f"source 必须是 {sorted(_DRI_SOURCE_PATHS)} 之一，收到 {source!r}"
            )
        # 三必填参——任一缺失先 raise（绝不打网络）。
        missing = [
            name for name, val in (("company_id", company), ("ps_flag", ps_flag), ("account_id", account))
            if val is None
        ]
        if missing:
            raise DeliveryReceiptItemValidationError(
                f"delivery_receipt_item 必填参缺失: {missing}（company/ps_flag/account 三者皆必填）"
            )

        params: dict = dict(filter or {})
        params["company_id"] = company
        params["ps_flag"] = ps_flag
        params["account_id"] = account
        if so_id is not None:
            params["so_id"] = so_id

        # 后端返裸 List<> → 走 _request 拿原值（不 `or {}` 吞空），coerce_to_page 包形。
        raw = self._http._request("GET", self._url(source), params=params)
        page = coerce_to_page(raw)
        page.source = source  # 旁挂 source marker（wrapper 形 {items, total, source}）
        return page

