"""pp 模块 entity（#13 M2 子集）：mrp_history / mrp_rule。

本模块在 SDK 是首批 pp 实体（命名空间装配由收口阶段做，这里只写 entity 类）。

pp 是 **tenant-templated**（/v2/api/tenants/<tid>/）。这两实体后端均返 **flat List<>**（裸 JSON
数组、非 Spring Page 信封，分页无意义）→ 一律走 #10 基座的 `_list_bare`（→ http._request 原值 →
coerce_to_page 包 Page），**不**经 envelope.normalize（裸 list 喂 normalize 抛 AttributeError）、
**不**被 get_json 的 or {} 吞空。

坑（§6 行 474-581 + 538-568）：
- mrp_history：flat List、零 @RequestParam（list 签名 filterless，**不**加暗示可过滤的 kwargs；
  CLI 静默忽略任何 filter/size/all），但有真 get(id)——故 list-only-for-filters 但 list+get for verbs。
- mrp_rule：flat List；`include_items` 是 **backend-native** 真 query param（服务端原生支持、内嵌
  applied materials）→ 直接转发 ?include_items=true，**不**做 client-side fan-out/并发（与
  production-plan 的 client-side fan-out include_items 是两回事，绝不共用一套实现）；路径有
  **double /pp/** 段（base 已含 /mom/pp，path 再带 /pp/mrp-rules）照字面 hardcode，不归一掉内层 /pp/。
- 只读边界：pp 全部 GET/只读，本片只生成 list/get，无写。
"""
from __future__ import annotations

from typing import Callable, Optional

from ..auth import Session
from ..config import Credentials
from ..envelope import Page, coerce_to_page
from ..gotchas import enrich_items_fanout
from ..http import HttpClient
from ..pagination import iterate_all
from .base import PagedEntity, PostPagedEntity


class _PpBodyPagedEntity(PostPagedEntity):
    """pp 专属 POST-body 分页基座：page/size **进 body**（不进 query）。

    live parity 校正发现：pp 的 production-plan/demand-supply/sales-order 后端要求
    page/size 随 filter 一起进 **JSON body**（CLI 实现 `postPage(path, {...filter, page, size})`，
    无 query 参）。base.PostPagedEntity 把 page/size 进 query → pp 这批端点回 **409**。
    故 pp 这批不复用 base._list，改走本基座（与 mm/sd 的「分页进 query」分道，不改 base）。
    page/size 按 CLI 透传为 **JSON number**（非字符串）。
    """

    def _list(
        self,
        base_params: Optional[dict],
        size: int,
        all_pages: bool,
        transform: Optional[Callable[[list], list]] = None,
    ) -> Page:
        url = self._base() + self._list_path(self._tenant_id())
        filt = dict(base_params or {})

        def fetch(page_no: int) -> Page:
            # 镜像 CLI：filter + page/size 全进 body（number 型），无 query 参。
            body = {**filt, "page": page_no, "size": size}
            page = self._http.post_page(url, body=body, params=None, requested_size=size)
            if transform is not None:
                page.items = transform(page.items)
            return page

        if not all_pages:
            return fetch(0)
        agg = iterate_all(fetch)
        return Page(
            items=agg.items, page=None, total=None, has_next=agg.truncated, truncated=agg.truncated
        )


class MrpHistoryEntity(PagedEntity):
    """pp.mrp_history（flat List + get(id)，filterless）。

    list 签名保持 filterless（零 @RequestParam）——不接受 filter/size/all 之外暗示可过滤的 kwargs，
    后端静默忽略分页/过滤；走 _list_bare 包 Page。有真 get(id)（区别于纯 list-only）。

    TODO: live pp __schema 复核端点单复数/filter_keys（parity 阶段校正）——
      list 路径 /mrp-histories/open-list、get 路径 /mrp-histories/<id> 按 §6 文档写，未 live 验。
    """

    MOD = "pp"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/mrp-histories/open-list"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/mrp-histories/{entity_id}"

    def list(self) -> Page:
        # filterless：零 @RequestParam，不拼 filter/page/size（后端不认）。size/all 在 _list_bare
        # 不参与翻页，这里固定传以满足签名。
        return self._list_bare(None, 200, True)

    def get(self, entity_id: str) -> dict:
        return self._get(entity_id)


class MrpRuleEntity(PagedEntity):
    """pp.mrp_rule（flat List + backend-native include_items）。

    路径 double /pp/ 段照字面（base /mom/pp + path /v2/api/tenants/<tid>/pp/mrp-rules）。
    include_items 是 backend-native 真 query param → True 则直接转发 ?include_items=true，**不**做
    client-side fan-out（区别于 production-plan）；走 _list_bare 包 Page（flat List）。

    TODO: live pp __schema 复核端点单复数/filter_keys（parity 阶段校正）——
      路径 /pp/mrp-rules（double /pp/）与 include_items 键名按 §6 文档写，未 live 验。
    """

    MOD = "pp"

    def _list_path(self, tenant_id: str) -> str:
        # double /pp/：base 已是 /mom/pp，再叠 /pp/mrp-rules（照字面，不归一内层 /pp/）。
        return f"/v2/api/tenants/{tenant_id}/pp/mrp-rules"

    def list(self, *, include_items: bool = False) -> Page:
        # backend-native query param 直接转发；False 则不挂该键（不污染请求）。
        params = {"include_items": "true"} if include_items else None
        return self._list_bare(params, 200, True)


# ===========================================================================
# #14 M3（§6 行 492-581）：业务单据坑层主力。
# camelCase vs snake_case 在 pp 内碎到 entity——production_plan/demand_supply/sales_order 是
# camelCase（materialIds/plantId），kitting_template 是 snake_case（material_group/_category），
# **逐实体按 §6 透传，SDK 不做 key 转换**（错驼/错蛇后端静默忽略，parity 也测不出）。
# 端点单复数/路径/filter_keys 照 §6 文档写，每实体 docstring 标 live __schema 复核 TODO。
# ===========================================================================


class DemandSupplyEntity(_PpBodyPagedEntity):
    """pp.demand_supply（需求供给, §6 行 504）：simple-list-get，POST-body 分页。

    list 是 POST（MrpDemandQueryVO 进 body、page/size 进 query）→ 继承 PostPagedEntity，**绝不**
    退回 GET 的 PagedEntity._list；多值 materialIds/mrpType/purchaseGroups 进 body JSON 数组。
    filter key 是 **camelCase**（materialIds/historyId/plantId/demandType）→ 原样透传，不做 snake 转换。
    日期 filter 是 date 型（startProdDate/endProdDate，YYYY-MM-DD，非 datetime ISO）——SDK 只透传。
    historyId 关联某 MRP run（配对 mrp_history），docstring 标 cross-entity link，无自动 join。

    端点已核实（2026-06-04 对 ibrain-pp 后端 DemandSupplyEndpoint
    @RequestMapping /v2/api/tenants/{tenant_id}/demand-supplies）：裸 /demand-supplies（POST），
    page/size 随 body。**filter-gated**：必带 historyId（某次 MRP run，配对 mrp_history）才出数——
    不带 historyId 后端返空（非 no-data、非 SDK bug；ibrain-pp/cli capability 注明 agent 不带即「撞墙」）。
    parity 需 bespoke：先从 mrp_history 取 historyId 再 list(filter={historyId:..}) 比对 CLI。
    """

    MOD = "pp"

    def _list_path(self, tenant_id: str) -> str:
        # live parity 校正：CLI postPage 真端点是裸 /demand-supplies（无 /page），
        # page/size 随 body 走（PostPagedEntity）。旧 /demand-supplies/page → 405。
        return f"/v2/api/tenants/{tenant_id}/demand-supplies"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/demand-supplies/{entity_id}"

    def list(self, *, filter: Optional[dict] = None, size: int = 20, all: bool = True) -> Page:
        # filter 进 body（PostPagedEntity._list），camelCase 原样透传。
        return self._list(base_params=filter, size=size, all_pages=all)

    def get(self, entity_id: str) -> dict:
        return self._get(entity_id)


class SalesOrderEntity(_PpBodyPagedEntity):
    """pp.sales_order（SO **物料视图**, §6 行 516）：custom-verbs。

    **语义陷阱**：这是「每个 SO 影响哪些物料」的 MATERIAL VIEW（MaterialStatisticsVO），**不是**
    SO header 清单——与 pp.production_plan 的 soId filter 是两回事，调用方别混。

    list 是 POST（SaleOrdersVO 进 body、page/size 进 query）→ PostPagedEntity；camelCase filter
    （soId/contractId/plantId/materialNo/procurementTypes）原样进 body；procurementTypes 多值→数组、
    containIndependentDemand 布尔。get(so_id) 返**裸 List<MaterialStatisticsVO>**（非单对象）→ 包成
    {id, items} surrogate（同 wm/sd 的 list-return-shape，不假装返 SO header）。

    端点已核实（2026-06-04 对 ibrain-pp 后端 SalesOrderViewEndpoint
    @RequestMapping /v2/api/tenants/{tenant_id}/sales-orders + @PostMapping /so-material-view[/page]）。

    **数据获取（2026-06-04 后端+live 核实，纠正旧「穷举无数据/id 不通用」误判）**：soId **就是 sd
    模块销售订单的 id**——后端 queryMaterialStatisticBySoIds → getInternalSoByIds 直接查 t_sd_so
    （ibrain-pp ProjectViewService.java:1298）；旧 docstring「pp 侧 so_id 与 sd.sales_order id 不通用」
    **已证伪**。两条路径数据源相同、语义不同：
    · get(soId) → GET /sales-orders/{soId}/material-view（queryMaterialStatisticBySo，301 行，**不按
      plant 过滤**）→ 返该 SO 全量物料分解视图。aquaman 真实 SO 普遍有数据（2026-06-04 live 实测
      12/12 个 SO 各 2-6 物料行）→ **parity 已武装**（tests test_sales_order_material_view_get_parity_live）。
    · list(filter) → POST /so-material-view/page：getMdSalesOrderList **按 SO 行项的 plantId 过滤**
      （ProjectViewService.java:1302，`line.plantId == 入参 plantId`）→ 必带与该 SO 行项完全一致的
      plantId 才出数；不传/传错即空（**filter-gated、非无数据、非 SDK bug**）。sd SO header 不暴露该
      plant（production_plan 的是 MO plant，另一套），难种子化，故 list 路径默认空——这是端点语义，
      不是 SDK 欠账。要 parity list 路径需先拿到 SO 行项真实 plantId。
    """

    MOD = "pp"

    def _list_path(self, tenant_id: str) -> str:
        # live parity 校正：CLI POST 真端点是 /sales-orders/so-material-view/page
        # （复数 sales-orders + so-material-view 段）。旧 /sale-orders/page → 404。
        return f"/v2/api/tenants/{tenant_id}/sales-orders/so-material-view/page"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        # live parity 校正：CLI GET 真端点是 /sales-orders/<soId>/material-view（裸 List 物料视图）。
        return f"/v2/api/tenants/{tenant_id}/sales-orders/{entity_id}/material-view"

    def list(self, *, filter: Optional[dict] = None, size: int = 20, all: bool = True) -> Page:
        return self._list(base_params=filter, size=size, all_pages=all)

    def get(self, so_id: str) -> dict:
        """surrogate：后端返裸 List → 包 {id, items}（物料视图行，非 SO header）。"""
        url = self._base() + self._get_path(self._tenant_id(), so_id)
        raw = self._http._request("GET", url)  # 裸 List，走原值路径（不 get_json `or {}` 吞空）
        items = raw if isinstance(raw, list) else []
        return {"id": so_id, "items": items}


class BomTreeEntity:
    """pp.bom_tree（BOM 树, §6 行 528）：**get-only**（无 .list，忠实不假装）。

    不是普通 .get(id)：是 bulk POST 吃逗号分隔 / list[str] 的 material ids → 返**多棵树**。
    硬编码字面 path `/mds/materials/bom-tree/bulk`（跨进 mds-style，**不**带 /production-plans 前缀，
    base 只是 /mom/pp 的 tenant 段）。返回 {items:[BomTree], total} 信封 → coerce_to_page 包 Page。

    body key（material_ids 数组）按 §6 splitting CSV 后传——TODO 留待 live 复核确切 body key
    （schema arg 是 material-ids-csv，body 键名 material_ids vs materialIds 需 CLI 抓确认）。

    TODO: live pp __schema 复核 bulk body key + 端点字面 path（parity 阶段校正）——
      /mds/materials/bom-tree/bulk 与 body key material_ids 按 §6 文档写，未 live 验。
    """

    MOD = "pp"

    def __init__(self, cred: Credentials, session: Session, http: HttpClient):
        self._cred = cred
        self._session = session
        self._http = http

    def _url(self) -> str:
        tid = self._session.token().tenant_id
        # 硬编码字面：base + tenant 段 + mds-style bom-tree bulk（不归一、不加 /production-plans）。
        return self._cred.base_url(self.MOD) + f"/v2/api/tenants/{tid}/mds/materials/bom-tree/bulk"

    @staticmethod
    def _split_ids(material_ids) -> list:
        """CSV string 或 list[str] → list[str]（首尾空白剥离、空段剔除）。"""
        if isinstance(material_ids, str):
            parts = material_ids.split(",")
        else:
            parts = list(material_ids or [])
        return [p.strip() for p in parts if isinstance(p, str) and p.strip()]

    def get(self, material_ids) -> Page:
        """多 id fan 成多树：bulk POST material_ids 数组 → {items:[BomTree], total} → Page。"""
        ids = self._split_ids(material_ids)
        raw = self._http._request("POST", self._url(), json={"material_ids": ids})
        return coerce_to_page(raw)


class ProductionPlanRecordEntity:
    """pp.production_plan_record（生产计划记录, §6 行 547）：custom-verbs，path-scoped {ppId}。

    `productionPlanId` **必填且进 URL 路径段**（不是 query/body）——base 的 _list_path(tenant_id)
    表达不了第二个 scope 段，故不继承 PagedEntity 的路径模板，自定义 URL builder。
    缺失/空 ppId → **fail-loud**（raise，绝不静默调）。返**裸 List**（非分页信封）→ coerce 包 Page。
    天然配对 production_plan（列计划→钻记录），但 entity 忠实于 path-scoped 端点，无自动 join。

    TODO: live pp __schema 复核端点路径段（parity 阶段校正）——
      /production-plans/<ppId>/records 与 /records/<recordId> 按 §6 文档写，未 live 验。
    """

    MOD = "pp"

    def __init__(self, cred: Credentials, session: Session, http: HttpClient):
        self._cred = cred
        self._session = session
        self._http = http

    def _scope_base(self, pp_id: str) -> str:
        tid = self._session.token().tenant_id
        return self._cred.base_url(self.MOD) + f"/v2/api/tenants/{tid}/production-plans/{pp_id}/records"

    @staticmethod
    def _require_pp_id(pp_id) -> str:
        if not pp_id or not isinstance(pp_id, str):
            raise ValueError("production_plan_record 需要非空 production_plan_id（进 URL 路径段）")
        return pp_id

    def list(self, production_plan_id: str) -> Page:
        """productionPlanId 进路径段；裸 List → coerce 包 Page。缺失 fail-loud。"""
        pp_id = self._require_pp_id(production_plan_id)
        raw = self._http._request("GET", self._scope_base(pp_id))  # 裸 List 走原值路径
        return coerce_to_page(raw)

    def get(self, record_id: str, production_plan_id: str) -> dict:
        """record_id + production_plan_id 双必填；ppId 进路径段。"""
        pp_id = self._require_pp_id(production_plan_id)
        url = self._scope_base(pp_id) + f"/{record_id}"
        return self._http.get_json(url)


class KittingTemplateEntity(PagedEntity):
    """pp.kitting_template（齐套模板, §6 行 569）：custom-verbs。

    list 是 pp 唯一真 **GET-query-paged** 实体（其余 POST-body）→ 直接走 PagedEntity._list（GET）。
    filter key 是 **snake_case** `material_group`/`material_category`——与同模块 production_plan/
    demand_supply 的 camelCase **相反**，照 schema 原样透传，**绝不**误驼峰成 materialGroup/materialCategory。

    get 是 **surrogate**：后端无单模板 GET → 回退取该模板 items 首页（/{id}/manual-kitting-template-items/page）
    → 包 {id, items}。**只取首页**（非全量，可能 truncation）——docstring 标明，不假装返模板 header。

    TODO: live pp __schema 复核端点单复数/filter_keys（parity 阶段校正）——
      list /kitting-templates/page、items 子路径 /manual-kitting-template-items/page 按 §6 文档写，未 live 验。
    """

    MOD = "pp"

    def _list_path(self, tenant_id: str) -> str:
        # live parity 校正：CLI GET-paged 真端点挂在 /production-plans/ 段下，
        # 即 /production-plans/manual-kitting-templates/page。旧 /kitting-templates/page → 404。
        return f"/v2/api/tenants/{tenant_id}/production-plans/manual-kitting-templates/page"

    def list(self, *, filter: Optional[dict] = None, size: int = 20, all: bool = True) -> Page:
        # filter 进 query（GET-paged）；snake_case key 原样透传，不驼峰。
        return self._list(base_params=filter, size=size, all_pages=all)

    def get(self, template_id: str) -> dict:
        """surrogate：取该模板 items 首页 → {id, items}（非全量、可能 truncation）。"""
        # live parity 校正：items 子路径同样在 /production-plans/manual-kitting-templates/ 段下。
        path = (
            f"/v2/api/tenants/{self._tenant_id()}/production-plans/manual-kitting-templates/"
            f"{template_id}/manual-kitting-template-items/page"
        )
        page = self._sub_list(path, params=None, size=20, all_pages=False)  # 只取首页
        return {"id": template_id, "items": page.items}


class ProductionPlanEntity(_PpBodyPagedEntity):
    """pp.production_plan（生产计划, §6 行 492）：**最重坑层**，POST-body 分页 + client-side fan-out。

    list 是 POST（body filter、page/size 进 query）→ PostPagedEntity，**绝不**退回 GET-query 分页。
    filter key 是 **camelCase**（materialIds/plantId/moTypes/productionPlanStatus）→ 原样进 body，
    **绝不**复用 mm 的 snake material_ids；多值 moTypes/productionPlanStatus/materialIds 进 body 数组
    （无 413 chunk 需求——body 不是 query）。日期 filter 是 date 型（createdStartDate 等，非 datetime ISO）。

    include_items（无 bulk 端点）走 **client-side enrich_items_fanout**（fail-isolated, concurrency=5）：
    - 对每个 header fan-out 取 records/issues/kitting 三子源；
    - per-source 失败 → 该子源 inline `{error}` 子对象（fail-soft-per-source，镜像 CLI，stdout 仍合法 JSON）；
    - 某 header 整体抓取抛错 → 该 header `items=None` + `items_error`（**不冒泡**，其余 header 正常）。
    这与 mm.PO 的 fail-loud bulk-get 是**相反** fail-mode——复用 #11 的 enrich_items_fanout，**绝不**
    退回 skip-on-error 的 fan_out（契约相反）。fetch_items_for 可注入（默认打真子端点，测试可桩）。

    币种：§6 production-plan schema **无金额/币种归一字段**（filter_keys 与 records/issues/kitting
    子对象全程无金额）——production_plan 是产量/物料导向，不做币种归一，故 **不接 currency_index**。
    如未来 live 数据出现金额字段，照 sd 的 `_attach_currency_companions` 旁挂 normalize，缺则不臆造。

    TODO: live pp __schema 复核端点单复数/filter_keys + 三子源路径（parity 阶段校正）——
      list /production-plans/list、get /production-plans/<id>、子源 records/issues/kitting 路径按 §6 文档写，未 live 验。
    """

    MOD = "pp"

    # include_items 的三子源 → (输出键, 子路径段)（相对 /production-plans/<id>/）。
    # live parity 校正：records 真子路径是 records/list（CLI GET），issues 裸 /issues。
    # kitting 子源 CLI 未暴露独立端点，保留按 §6 文档值（per-source fail-soft 兜底）。
    _ITEM_SOURCES = (("records", "records/list"), ("issues", "issues"), ("kitting", "kitting"))

    def _list_path(self, tenant_id: str) -> str:
        # live parity 校正：CLI postPage 真端点是 /production-plans/query（不是 /list）。
        # 旧 /production-plans/list → 405。
        return f"/v2/api/tenants/{tenant_id}/production-plans/query"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/production-plans/{entity_id}"

    def list(
        self,
        *,
        filter: Optional[dict] = None,
        include_items: bool = False,
        size: int = 20,
        all: bool = True,
        fetch_items_for: Optional[Callable] = None,
    ) -> Page:
        # filter 进 body（camelCase 原样透传），分页参进 query。
        page = self._list(base_params=filter, size=size, all_pages=all)
        if include_items and page.items:
            fetcher = fetch_items_for or self._default_fetch_items
            # client-side fail-isolated fan-out：单 header 整体失败 → items=None+items_error，不冒泡。
            enriched = enrich_items_fanout(page.items, fetcher, concurrency=5)
            page.items = enriched
        return page

    def get(self, entity_id: str, *, include_items: bool = False) -> dict:
        detail = self._get(entity_id)
        if include_items:
            try:
                detail["items"] = self._default_fetch_items(detail)
            except Exception as e:  # get 单条同样 fail-isolated（不冒泡）
                detail["items"] = None
                detail["items_error"] = f"{type(e).__name__}: {e}"
        return detail

    # ---- include_items 三子源默认抓取（per-source fail-soft → inline {error}）----

    def _default_fetch_items(self, header: dict) -> dict:
        """对单 header 取 records/issues/kitting 三子源；per-source 失败 → inline {error} 子对象。

        per-source fail-soft（镜像 CLI）：某子源端点失败不抛、不污染其余子源，记 {error} 摘要。
        若需整 header 失败语义，由外层 enrich_items_fanout 提供（这里只做子源隔离）。
        """
        pp_id = header.get("id")
        out: dict = {}
        for key, sub_path in self._ITEM_SOURCES:
            try:
                page = self._sub_list(
                    f"/v2/api/tenants/{self._tenant_id()}/production-plans/{pp_id}/{sub_path}",
                    params=None,
                    size=200,
                    all_pages=True,
                )
                out[key] = page.items
            except Exception as e:  # per-source 隔离 → inline {error}，不抛
                out[key] = {"error": f"{type(e).__name__}: {e}"}
        return out
