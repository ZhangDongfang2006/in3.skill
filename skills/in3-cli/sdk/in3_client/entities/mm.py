"""mm 模块 entity：supplier（list/get）+ purchase_order（chunk/open_qty/_matched/include_items）
+ info_record/rfq（M1 simple-list-get，#12）+ bom/currency（M2 bare-array，#13）。

端点（ibrain-mm/cli src/commands/*.ts，base = api_host + /mom/mm）：
  supplier.list   GET  /v2/api/tenants/<tid>/srm/suppliers  （**无 /page 后缀**）
  supplier.get    GET  /v2/api/tenants/<tid>/srm/suppliers/<id>
  po.list         GET  /v2/api/tenants/<tid>/spm/purchase-orders/pages
  po bulk items   POST /v2/api/tenants/<tid>/spm/purchase-orders/items/bulk-get-by-po  {po_ids:[...]}
  po.get          GET  /v2/api/tenants/<tid>/spm/purchase-orders/<id>
  info_record.list GET /v2/api/tenants/<tid>/spm/info-records/page
  info_record.get  GET /v2/api/tenants/<tid>/spm/info-records/<id>
  rfq.list        POST /v2/api/tenants/<tid>/spm/request-for-quotations/pages  （**POST-body 分页、复数 pages**；
                       live parity 校正 2026-06-03：CLI rfq.js 用 client.postPage，GET 触发后端 500）
  rfq.get         GET  /v2/api/tenants/<tid>/spm/request-for-quotations/<id>
  bom.list        GET  /v2/api/tenants/<tid>/boms/list  （**裸数组**、material_id 必填）
  bom.get         GET  /v2/api/tenants/<tid>/boms/materials/<material_id>  （结构树，keyed by material_id）
  currency.list   GET  /v2/api/tenants/<tid>/mdm/currency/all/available  （**裸数组**、无 filter）
  currency.get    GET  /v2/api/tenants/<tid>/mdm/currency/detail?currency_no=<no>  （query param）

purchase_order 坑层逐位移植自 purchase-order.ts（见各方法注释）。
"""
from __future__ import annotations

from typing import Optional

from ..auth import Session
from ..config import Credentials
from ..envelope import Page
from ..filters import check_filter_keys
from ..gotchas import open_qty_fallback
from ..http import HttpClient, HttpError
from ..pagination import iterate_all
from .base import PagedEntity, PostPagedEntity

# mm.supplier 后端 exhaustive filter_keys（ibrain-mm-cli __schema .commands.supplier.list.filter_keys）。
_SUPPLIER_FILTER_KEYS = frozenset({
    "company_id", "name", "erp_code", "supplier_type", "status", "ranking", "package_code",
})
# mm.purchase-order 后端 exhaustive filter_keys（同 __schema .commands."purchase-order".list.filter_keys）。
_PO_FILTER_KEYS = frozenset({
    "plant_id", "company_id", "so_query", "so_id", "ct_query", "po_no", "order_type",
    "reverse_displayed", "supplier_id", "status", "if_use_config_status", "only_overdue",
    "only_open", "no_contract", "pr_no", "material_ids", "ordered_by_id", "purchase_type",
    "with_data_role", "from_created_date", "to_created_date", "from_modified_date",
    "to_modified_date", "from_ordered_at", "to_ordered_at", "supplier_order_no",
    "purchase_order_contract_no", "is_bound_purchase_order_contract", "supplier_name",
    "has_ref_limit", "sto_status", "is_contract_approved", "is_printed",
})
# mm.info-record filter_keys（§6 行 168，全单值；only_latest bool、before_price_valid_to date）。
_INFO_RECORD_FILTER_KEYS = frozenset({
    "supplier_id", "material_id", "material_group", "material_category", "brand",
    "info_record_no", "only_latest", "before_price_valid_to",
})
# mm.rfq filter_keys（§6 行 179；rfq_categories/statuses 是 multi，时间全 date）。
_RFQ_FILTER_KEYS = frozenset({
    "rfq_no", "rfq_categories", "statuses", "contact_user_id",
    "rfq_date_from", "rfq_date_to", "rfq_valid_to_date_from", "rfq_valid_to_date_to",
})
# mm.bom 额外 filter_keys（§6 行 226；material_id 是必传参数不进此表，故下面单列；其余皆 date/单值）。
_BOM_FILTER_KEYS = frozenset({
    "material_id", "bom_name", "bom_rev", "remark", "material_no", "bom_structure_type",
    "from_created_date", "to_created_date", "from_modified_date", "to_modified_date",
})


class SupplierEntity(PagedEntity):
    MOD = "mm"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/srm/suppliers"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/srm/suppliers/{entity_id}"

    def list(self, *, filter: Optional[dict] = None, size: int = 20, all: bool = True) -> Page:
        filter = dict(filter or {})
        check_filter_keys("mm.supplier", filter, _SUPPLIER_FILTER_KEYS)
        return self._list(filter, size, all)

    def get(self, entity_id: str) -> dict:
        return self._get(entity_id)


class PurchaseOrderEntity:
    """逐位移植 ibrain-mm/cli purchase-order.ts。坑层全下沉，agent 调一次即拿踩平的数据。"""

    MOD = "mm"
    # 后端把 ?material_ids=a&material_ids=b... 当 query string，列表过长 413（实测~100 起），留余量 80。
    THRESHOLD = 80

    def __init__(self, cred: Credentials, session: Session, http: HttpClient):
        self._cred = cred
        self._session = session
        self._http = http

    def _base(self) -> str:
        tid = self._session.token().tenant_id
        return self._cred.base_url(self.MOD) + f"/v2/api/tenants/{tid}/spm/purchase-orders"

    def list(
        self,
        *,
        filter: Optional[dict] = None,
        plant: Optional[str] = None,
        include_items: bool = False,
        size: int = 20,
        all: bool = True,
    ) -> Page:
        filter = dict(filter or {})
        check_filter_keys("mm.purchase_order", filter, _PO_FILTER_KEYS)
        mids = filter.get("material_ids")
        if isinstance(mids, list) and len(mids) > self.THRESHOLD:
            return self._list_chunked(filter, plant, include_items, size, mids)

        page = self._fetch_list(filter, plant, size, all)
        if include_items:
            self._enrich_with_items(page, filter)
        return page

    def get(self, po_id: str) -> dict:
        detail = self._http.get_json(self._base() + f"/{po_id}")
        if isinstance(detail.get("items"), list):
            open_qty_fallback(detail["items"])  # get 详情 items 也兜底（与 list 两路一致）
        return detail

    # ---- 内部 ----

    def _fetch_list(self, filter: dict, plant: Optional[str], size: int, all_pages: bool) -> Page:
        url = self._base() + "/pages"
        base_params: dict = {}
        if plant:
            base_params["plant_id"] = plant
        base_params.update(filter)  # material_ids（list→repeated query）等透传

        def fetch(page_no: int) -> Page:
            return self._http.get_page(
                url, {**base_params, "page": str(page_no), "size": str(size)}, requested_size=size
            )

        if not all_pages:
            return fetch(0)
        agg = iterate_all(fetch)
        return Page(items=agg.items, page=None, total=None, has_next=agg.truncated, truncated=agg.truncated)

    def _list_chunked(self, filter, plant, include_items, size, all_mids) -> Page:
        from ..gotchas import chunk_material_ids  # noqa: PLC0415

        chunks = chunk_material_ids(all_mids, self.THRESHOLD)
        merged: dict = {}  # po.id -> header，保持插入序，后块覆盖前块同 id
        for chunk in chunks:
            chunk_filter = {**filter, "material_ids": chunk}
            page = self._fetch_list(chunk_filter, plant, size, all_pages=True)  # 任一块抛 → 冒泡 fail-loud
            for item in page.items:
                merged[item["id"]] = item
        merged_items = list(merged.values())
        page = Page(items=merged_items, page=0, total=len(merged_items), has_next=False)
        page._chunked = True
        page._chunks_count = len(chunks)
        page._chunk_size = self.THRESHOLD
        if include_items:
            self._enrich_with_items(page, filter)
        return page

    def _enrich_with_items(self, page: Page, filter: dict) -> None:
        if not page.items:
            return
        po_ids = [h["id"] for h in page.items]
        flat = self._http.post_json(self._base() + "/items/bulk-get-by-po", {"po_ids": po_ids})
        by_po: dict = {}
        for item in flat or []:
            po_id = item.get("po_id")
            if not isinstance(po_id, str):
                continue
            by_po.setdefault(po_id, []).append(item)
        for header in page.items:
            items = by_po.get(header["id"], [])
            open_qty_fallback(items)
            header["items"] = items
        self._annotate_matched(page.items, filter)

    @staticmethod
    def _annotate_matched(headers: list, filter: dict) -> None:
        """多值(≥2) material_ids 时，按 items[].material_id ∩ 过滤表标 _matched（插入序、去重、仅命中挂）。"""
        wanted = filter.get("material_ids")
        if not isinstance(wanted, list) or len(wanted) < 2:
            return
        wanted_set = set(wanted)
        for header in headers:
            hit: list = []
            for it in header.get("items") or []:
                mid = it.get("material_id")
                if isinstance(mid, str) and mid in wanted_set and mid not in hit:
                    hit.append(mid)
            if hit:
                header["_matched_filter_values"] = {"material_ids": hit}


class InfoRecordEntity(PagedEntity):
    """mm.info_record（#12 simple-list-get）。标准 /page + /<id>，照 MaterialEntity。

    TODO: live mm __schema 复核端点单复数/filter_keys（parity 阶段校正）——尤其确认
      list 是 /spm/info-records/page（单数 page）、filter 全单值无 multi。
    含价格字段但 schema 未标币种归一字段，本期不挂 currency companion（§6 行 172）。
    """

    MOD = "mm"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/spm/info-records/page"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/spm/info-records/{entity_id}"

    def list(self, *, filter: Optional[dict] = None, size: int = 20, all: bool = True) -> Page:
        filter = dict(filter or {})
        check_filter_keys("mm.info_record", filter, _INFO_RECORD_FILTER_KEYS)
        return self._list(filter, size, all)

    def get(self, entity_id: str) -> dict:
        return self._get(entity_id)


class RfqEntity(PostPagedEntity):
    """mm.rfq（#12，**POST-body 分页**）。list 端点 /pages（复数）走 POST，get 是 /<id>（单数 path 段，GET）。

    live parity 校正（2026-06-03，tenant=zhuzheng）：早期估值把 list 当 GET（PagedEntity），
      真后端对 GET /request-for-quotations/pages **回 500**——CLI rfq.js 实际用 client.postPage
      （POST，filter 进 body、page/size 进 query），与 quotation 同形。故改继承 PostPagedEntity，
      _list 走 http.post_page。get 仍是 GET /<id>（CLI get 用 client.get），不变。
    rfq_categories/statuses 为 multi（POST body JSON 数组透传，不再是 GET repeated query）；
      filter 全 date 无 datetime（与 quotation 的 date+datetime 双套区分）。
    """

    MOD = "mm"

    def _list_path(self, tenant_id: str) -> str:
        # 注意：list 是 /pages（复数）走 POST-body，区别于 info-record 的 GET /page。
        return f"/v2/api/tenants/{tenant_id}/spm/request-for-quotations/pages"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        # get 是 /<id> 单数 path 段（不是 /pages/<id>），GET。
        return f"/v2/api/tenants/{tenant_id}/spm/request-for-quotations/{entity_id}"

    def list(self, *, filter: Optional[dict] = None, size: int = 20, all: bool = True) -> Page:
        filter = dict(filter or {})
        check_filter_keys("mm.rfq", filter, _RFQ_FILTER_KEYS)
        # PostPagedEntity._list：filter 进 body、page/size 进 query（rfq_categories/statuses 进 body JSON 数组）。
        return self._list(filter, size, all)

    def get(self, entity_id: str) -> dict:
        return self._get(entity_id)


class BomEntity(PagedEntity):
    """mm.bom（#13 bare-array、material_id 必填）。

    坑层（§6 行 223-233）：
      - list 端点 /boms/list 返**裸 JSON 数组**（无分页信封）→ 走 _list_bare/coerce_to_page，
        绝不走 normalize（裸数组进 normalize 会被 _extract_total 调 .get 抛 / 或被 get_json 的 `or {}` 吞）。
      - material_id **必填**：缺则 fail-loud raise ValueError（不打网络），与 CLI bom.ts 的 VALIDATION 一致。
        material_id 是必传关键字参数，不是可选 filter。
      - get(material_id) 走 /boms/materials/<material_id>（**非** /boms/<id>），返按 material_id keyed
        的整棵 BOM 结构树（含组件行项），故覆写 get()。
    TODO: live mm __schema 复核端点单复数/filter_keys（parity 阶段校正）——确认 /boms/list 裸数组、
      /boms/materials/<material_id> 路径、material_id 必填、date filter 键名。
    """

    MOD = "mm"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/boms/list"

    def list(
        self,
        *,
        material_id: Optional[str] = None,
        filter: Optional[dict] = None,
        size: int = 20,
        all: bool = True,
    ) -> Page:
        # fail-loud：缺 material_id 在发任何 HTTP 前就拒（忠实移植 bom.ts 的必填 VALIDATION）。
        if not material_id:
            raise ValueError("mm.bom.list 需要 material_id（来自 --material）—— 缺则后端 VALIDATION，SDK 前置拒绝")
        params = dict(filter or {})
        params["material_id"] = material_id
        check_filter_keys("mm.bom", params, _BOM_FILTER_KEYS)
        # 裸数组端点：走 _list_bare（_request 原值 → coerce_to_page），不经 normalize/get_json。
        return self._list_bare(params, size, all)

    def get(self, material_id: str) -> dict:
        # get 路径是 /boms/materials/<material_id>（keyed by material_id，非 db id）；返结构树。
        url = self._base() + f"/v2/api/tenants/{self._tenant_id()}/boms/materials/{material_id}"
        return self._http.get_json(url)


class CurrencyEntity(PagedEntity):
    """mm.currency（#13 bare-array、无 filter、query-param get）—— **mm 视角的可用币种**。

    坑层（§6 行 235-243）：
      - 与 md.currency 是**不同端点**：md.CurrencyEntity 走 /mdm/currencies/page（分页 + keyword/enabled
        filter）；mm.currency 走 /mdm/currency/all/available（**裸数组**、无分页无 filter、仅 enabled）。
        两个都叫 currency 但端点/形态不同——**不复用** md.CurrencyEntity，新建 mm 专属。
      - list 返裸数组 → 走 _list_bare/coerce_to_page（同 bom），否则被 normalize 吞。list 无任何参数。
      - get(currency_no) 是 **query-param** 形式 /mdm/currency/detail?currency_no=<no>（不是 path 段），
        参数语义是币种代码（如 156）不是数据库 id，故覆写 get()。
      - md.currency_index 归一字典已由 md.CurrencyEntity 建，mm.currency **不替换**它。
    TODO: live mm __schema 复核端点单复数/filter_keys（parity 阶段校正）——确认 /mdm/currency/all/available
      裸数组、/mdm/currency/detail?currency_no= 的 query-param get。
    """

    MOD = "mm"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/mdm/currency/all/available"

    def list(self, *, size: int = 20, all: bool = True) -> Page:
        # 无 filter_keys：list 不暴露 filter 参数。裸数组走 _list_bare。
        return self._list_bare(None, size, all)

    def get(self, currency_no: str) -> dict:
        # query-param get：/mdm/currency/detail?currency_no=<no>（不是 path 段）。
        url = self._base() + f"/v2/api/tenants/{self._tenant_id()}/mdm/currency/detail"
        return self._http.get_json(url, params={"currency_no": currency_no})


# ===========================================================================
# M3（issue #14 §6 行 140-220）：业务单据坑层（contract / purchase_requirement /
# source_list / ecn / quotation）。端点单复数/path/filter_keys 照 §6 写，每实体 docstring
# 标 live __schema 复核 TODO（§6 反复强调端点高度不规整需抓 CLI 确认，别当真值）。
# 只读边界：仅 list/get/query/items；ecn 的 /<id>/check、quotation 的 POST 都是只读查询语义。
# ===========================================================================

# mm.contract filter_keys（§6 行 140；category 单值 ONLINE|OFFLINE、supplier_id/status multi、date）。
_CONTRACT_FILTER_KEYS = frozenset({
    "company_id", "contract_no", "category", "supplier_id", "status",
    "ordered_by_id", "po_no", "from_created_date", "to_created_date",
})
# mm.purchase_requirement filter_keys（§6 行 152；purchase_type/status/approval_statuses multi、date）。
_PURCHASE_REQUIREMENT_FILTER_KEYS = frozenset({
    "plant_id", "pr_no", "purchase_type", "ordered_by", "org_id", "status",
    "approval_statuses", "from_created_date", "to_created_date",
    "include_approval_item", "include_completed_item", "plan_delivery_location",
})
# mm.source_list filter_keys（§6 行 188；全单值无 multi 无日期）。
_SOURCE_LIST_FILTER_KEYS = frozenset({
    "supplier_id", "material_id", "material_group", "material_category", "brand",
})
# mm.ecn filter_keys（§6 行 199；material_ids multi、from_time/to_time 是 datetime）。
_ECN_FILTER_KEYS = frozenset({
    "material_ids", "so_no", "contract_id", "user_id", "bomchange_id", "from_time", "to_time",
})
# mm.quotation filter_keys（§6 行 210；date+datetime 双套并存、supplier_ids/rfq_id integer multi）。
_QUOTATION_FILTER_KEYS = frozenset({
    "rfq_id", "rfq_no", "quotation_no", "statuses", "supplier_ids", "rfq_categories",
    "sources", "material_id", "rfq_date_from", "quotation_date_from",
    "quotation_date_time_from", "rfq_valid_to_date_from", "rfq_valid_to_date_from_time",
})


class ContractEntity(PagedEntity):
    """mm.contract（#14 simple-list-get + online/offline 404 fallback get）。

    坑层（§6 行 140-150）：
      - list /spm/contracts/pages，**header-only**：schema 未给行项 bulk 端点，**不造行项**
        （PO 那种 include_items 这里不做；如需行项只能逐条 N+1 get，本期不实现）。
      - get() 移植 contract.ts 双端点 404 fallback：先 GET /spm/online-contracts/<id>，
        **HttpError(404)** 再 GET /spm/offline-contracts/<id>，各自旁挂
        _contract_type='online'/'offline'；两路都 404 才 fail-loud（重抛 offline 那次 404）。
        非 404 的 online 错误（如 500）**不**回退、直接冒泡。PagedEntity._get 只走单 path，故覆写 get()。
      - category 单值字符串 ONLINE|OFFLINE（**不是** multi）；supplier_id/status 才是 multi
        （list→repeated query 透传）。
      - from/to_created_date 是 **date**（YYYY-MM-DD），不是 datetime——与 sd 的 datetime ISO 区分。
    TODO: live mm __schema 复核（parity 阶段校正）——确认 /spm/contracts/pages、
      online-contracts/offline-contracts 双端点、category 单值 / supplier_id·status multi。
    """

    MOD = "mm"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/spm/contracts/pages"

    def list(self, *, filter: Optional[dict] = None, size: int = 20, all: bool = True) -> Page:
        filter = dict(filter or {})
        check_filter_keys("mm.contract", filter, _CONTRACT_FILTER_KEYS)
        # supplier_id/status 是 multi：list 值原样透传，底层 transport 渲染 repeated query。
        return self._list(filter, size, all)

    def get(self, contract_id: str) -> dict:
        # online → offline 404 fallback；旁挂 _contract_type 判别器。
        online_url = self._base() + f"/v2/api/tenants/{self._tenant_id()}/spm/online-contracts/{contract_id}"
        try:
            detail = self._http.get_json(online_url)
            detail["_contract_type"] = "online"
            return detail
        except HttpError as e:
            if e.status != 404:
                raise  # 非 404（如 500）：不回退，直接冒泡
        # online 404 → 回退 offline（offline 再 404 则 fail-loud：HttpError 冒泡）。
        offline_url = self._base() + f"/v2/api/tenants/{self._tenant_id()}/spm/offline-contracts/{contract_id}"
        detail = self._http.get_json(offline_url)
        detail["_contract_type"] = "offline"
        return detail


class PurchaseRequirementEntity:
    """mm.purchase_requirement（#14 fanout-gotcha）——对外名纠正，**内部 path 用 typo**。

    坑层（§6 行 152-167）：
      - URL 拼写坑：后端 Java 类型是 PurchaseRequirent（少一个 e），路径就是
        /spm/purchase-requirents（typo）。SDK 内部用 typo path、对外命名 purchase_requirement
        （纠正）——逐字移植 purchase-requirement.ts。list /spm/purchase-requirents/pages、
        get /spm/purchase-requirents/<id>。
      - include_items=True 走 bulk-get（POST /spm/purchase-requirents/bulk-get），body 是
        **裸 prId 数组** [..]（**不是** {ids:[..]} / {po_ids:[..]}），返完整 detail 数组（每个自带
        items），按 id 挂回 header['items']。空 detail（某 header 无对应）→ items=[]。
      - **无 413 风险/无需 chunk**：bulk-get 返 detail 自带 items（非 query string 多值），比 PO 简单。
      - purchase_type/status/approval_statuses 都是 multi（list→repeated query）；date filter。
      - current_user/with_data_role 是内部 scoping 字段，默认不传（不在 filter_keys 白名单）。
    TODO: live mm __schema 复核（parity 阶段校正）——确认 typo path /spm/purchase-requirents、
      bulk-get 裸数组 body、multi filter、date filter。
    """

    MOD = "mm"

    def __init__(self, cred: Credentials, session: Session, http: HttpClient):
        self._cred = cred
        self._session = session
        self._http = http

    def _base(self) -> str:
        tid = self._session.token().tenant_id
        # 内部 path 故意用 typo（purchase-requirents，少个 e），忠实后端 Java 类型 PurchaseRequirent。
        return self._cred.base_url(self.MOD) + f"/v2/api/tenants/{tid}/spm/purchase-requirents"

    def list(
        self,
        *,
        filter: Optional[dict] = None,
        plant: Optional[str] = None,
        include_items: bool = False,
        size: int = 20,
        all: bool = True,
    ) -> Page:
        filter = dict(filter or {})
        check_filter_keys("mm.purchase_requirement", filter, _PURCHASE_REQUIREMENT_FILTER_KEYS)

        url = self._base() + "/pages"
        base_params: dict = {}
        if plant:
            base_params["plant_id"] = plant
        base_params.update(filter)  # multi（list→repeated query）等透传

        def fetch(page_no: int) -> Page:
            return self._http.get_page(
                url, {**base_params, "page": str(page_no), "size": str(size)}, requested_size=size
            )

        if not all:
            page = fetch(0)
        else:
            agg = iterate_all(fetch)
            page = Page(items=agg.items, page=None, total=None, has_next=agg.truncated, truncated=agg.truncated)

        if include_items:
            self._enrich_with_items(page)
        return page

    def get(self, pr_id: str) -> dict:
        return self._http.get_json(self._base() + f"/{pr_id}")

    def _enrich_with_items(self, page: Page) -> None:
        """include_items：bulk-get（body 裸 prId 数组）→ 按 id 把 detail.items 挂回 header。

        body 是裸数组（非 {ids:[..]}），与 PO 的 {po_ids:[..]} 不同；返 detail 数组每个自带 items。
        无对应 detail 的 header → items=[]（与 CLI 一致）。
        """
        if not page.items:
            return
        pr_ids = [h["id"] for h in page.items]
        # 裸数组 body：post_json(url, body=pr_ids)（http._request 直接把 list 当 json 透传）。
        details = self._http.post_json(self._base() + "/bulk-get", pr_ids)
        by_id: dict = {}
        for detail in details or []:
            did = detail.get("id")
            if did is not None:
                by_id[did] = detail
        for header in page.items:
            detail = by_id.get(header["id"])
            items = detail.get("items") if isinstance(detail, dict) else None
            header["items"] = items if isinstance(items, list) else []


class SourceListEntity(PagedEntity):
    """mm.source_list（#14 simple-list-get，标准 list + query-param get）。

    坑层（§6 行 188-197）：
      - list 标准 /spm/source-lists/page（继承 PagedEntity._list_path）。
      - get() 坑：**不是** /source-lists/<id> path 段，而是 GET /spm/source-lists?id=<id>
        （id 作 query param）。PagedEntity._get 拼 path/<id>，不适用——覆写 get() 走
        http.get_json(base+'/source-lists', params={'id': id})。
      - filter 全单值，无 multi、无日期。
    TODO: live mm __schema 复核（parity 阶段校正）——确认 /spm/source-lists/page、?id= query-param get、
      filter 全单值。
    """

    MOD = "mm"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/spm/source-lists/page"

    def list(self, *, filter: Optional[dict] = None, size: int = 20, all: bool = True) -> Page:
        filter = dict(filter or {})
        check_filter_keys("mm.source_list", filter, _SOURCE_LIST_FILTER_KEYS)
        return self._list(filter, size, all)

    def get(self, entity_id: str) -> dict:
        # query-param get：/spm/source-lists?id=<id>（不是 path 段）。
        url = self._base() + f"/v2/api/tenants/{self._tenant_id()}/spm/source-lists"
        return self._http.get_json(url, params={"id": entity_id})


class EcnEntity(PagedEntity):
    """mm.ecn（#14 simple-list-get，非标 path + datetime）。

    坑层（§6 行 199-208）：
      - 端点**不在 /spm/ 下**：list = /ecn-bom/page（**无 spm 前缀**）；
        get = /ecn-bom/<id>/check（尾缀 /check，后端叫"查看"=detail-by-id，**只读**，非写操作）。
        get 路径有尾缀 /check，PagedEntity._get 拼不出，故覆写 get()。
      - from_time/to_time 是 **datetime**（ISO YYYY-MM-DDTHH:mm:ss）——mm 里少见的 datetime（同 sd），
        不是 date，容易踩错。SDK 只透传不强转。
      - material_ids 是 **multi**（list→repeated query）。schema/CLI 未做 PO 那种 413 chunk≤80，
        本期**不强制 fanout/chunk**（忠实 CLI 行为）。
        TODO: 调用方传超长 material_ids 列表有 413 风险——本期默认不拦（与 CLI 一致）；parity 阶段
        若实测 413 再补 chunk（照 PO THRESHOLD）。
    TODO: live mm __schema 复核（parity 阶段校正）——确认 /ecn-bom/page（无 spm 前缀）、
      /ecn-bom/<id>/check 尾缀、from_time/to_time datetime、material_ids multi。
    """

    MOD = "mm"

    def _list_path(self, tenant_id: str) -> str:
        # 无 spm 前缀：/ecn-bom/page。
        return f"/v2/api/tenants/{tenant_id}/ecn-bom/page"

    def list(self, *, filter: Optional[dict] = None, size: int = 20, all: bool = True) -> Page:
        filter = dict(filter or {})
        check_filter_keys("mm.ecn", filter, _ECN_FILTER_KEYS)
        # material_ids multi、from_time/to_time datetime：list 值原样透传，不强转。
        return self._list(filter, size, all)

    def get(self, entity_id: str) -> dict:
        # get 尾缀 /check：/ecn-bom/<id>/check（只读 detail）。
        url = self._base() + f"/v2/api/tenants/{self._tenant_id()}/ecn-bom/{entity_id}/check"
        return self._http.get_json(url)


class QuotationEntity(PostPagedEntity):
    """mm.quotation（#14 POST-body 分页 + 怪异 get 路径 + date/datetime 双套）。

    坑层（§6 行 210-220）：
      - **POST-body 分页**（像 wm.available_stock）：filter 进 JSON body、page/size 进 query。
        继承 **PostPagedEntity**（_list 走 http.post_page + iterate_all），**绝不**退回 GET 的
        PagedEntity._list（否则 filter 退化成 repeated query string，与后端 POST body 契约不符）。
        多值过滤进 body JSON 数组（不是 GET 的 repeated query）。
      - get 端点路径很怪：GET /spm-rfq/quotation/query/<id>（list 是 /spm-rfq/pages，
        get 是完全不同子路径）——必覆写 get()。
      - 日期 filter **date 和 datetime 两套并存**：quotation_date_from=date /
        quotation_date_time_from=datetime；rfq_valid_to_date_from=date / *_from_time=datetime。
        调用方按需选，SDK **只透传 body、不强转、不互相覆盖**——两套 key 各自独立。
      - supplier_ids 是 **integer multi**、rfq_id 是 **integer**（JSON body 里给数字更安全）。
      - 含报价金额——schema 未标币种归一字段，本期**不挂 currency companion**。
    TODO: live mm __schema 复核（parity 阶段校正）——确认 POST /spm-rfq/pages、
      get /spm-rfq/quotation/query/<id>、date+datetime 双套 key、supplier_ids/rfq_id integer。
    """

    MOD = "mm"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/spm-rfq/pages"

    def list(self, *, filter: Optional[dict] = None, size: int = 20, all: bool = True) -> Page:
        filter = dict(filter or {})
        check_filter_keys("mm.quotation", filter, _QUOTATION_FILTER_KEYS)
        # PostPagedEntity._list：filter 进 body、page/size 进 query（绝不退化成 GET-query 分页）。
        return self._list(filter, size, all)

    def get(self, quotation_id: str) -> dict:
        # get 是完全不同子路径：/spm-rfq/quotation/query/<id>。
        url = self._base() + f"/v2/api/tenants/{self._tenant_id()}/spm-rfq/quotation/query/{quotation_id}"
        return self._http.get_json(url)
