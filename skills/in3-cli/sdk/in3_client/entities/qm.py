"""qm 模块 entity（#15 M4 富自定义 verb）：质量检验 5 实体。

本模块在 SDK 是首批 qm 实体（命名空间装配由收口阶段做，这里只写 entity 类）。

5 实体均 tenant-templated（base = cred.base_url('qm') = api_host + /mom/qm，config 第 25
行已注册，**无需改 config**），继承 PagedEntity 拿标准 list(/page GET 分页)/get(path-id)，
再挂自定义 verb 方法（复用 self._base()/self._tenant_id()/self._http）。

模块级坑层（§6 行 909-995）——逐 verb 各自 wire，最易写错的几处：
- **query-id vs path-id**：get(id) 走 path 段；check_and_next/get_reject_order_id 走 ?id=/
  ?inspection_order_id= query（同样吃一个 id，wire 方式不同，逐 verb 核对真 CLI route）。
- **POST 分页 vs POST 非分页**：check_sheet.list_items 是 POST 分页（PostPagedEntity，
  filter 进 body、page/size 进 query、post_page+iterate_all）；inspection_order.
  list_unqualified_items 是 POST **非**分页（post_json 取 {items} 包 Page，不 iterate）。
- **{items} 非分页 wrap**：get_all/list_options/search_by_lot/list_by_lot/list_partials/
  list_nonqualified_types/list_unqualified_items/list_basic_info 等返 {items}，用 #11 的
  _wrap_items 包 Page(page=None/total=None, has_next=False)，**不**走 envelope.normalize。
- **reject_order 8 个 multi-filter**：statuses/defect_codes/source_codes/supply_codes/
  nonqualified_type_codes/area_ids/line_ids/approval_statuses 在 filter dict 给 list 时透传成
  repeated query（?statuses=A&statuses=B），**绝不** join 成逗号串（transport doseq 展开）。
- filter key 是 snake_case（material_id / inspection_lot_id / start_delivery_date），不是 pp 的
  camelCase——沿用 filter dict 直传即可。
- 只读边界：全部 verb 是 GET 或只读 POST（query/search），无一写操作——SDK 结构上不生成
  任何 create/update/delete。

TODO: live qm __schema 复核端点单复数/filter_keys/各 verb 子路径（parity 阶段逐 verb 校正）——
  本文件端点单复数、/page 后缀、?id= 参数名、子路径段均按 §6 文档逐字写，未 live 验。
"""
from __future__ import annotations

from typing import Optional

from ..envelope import Page, _wrap_items
from .base import PagedEntity, PostPagedEntity


# ============================================================
# rule_group：list / get / get_all / list_options
# ============================================================

class RuleGroupEntity(PagedEntity):
    """qm.rule_group（custom-verbs）：检验规则组。

    标准 list（/rule-groups/page，**带 /page 后缀**，照 md.material）+ get(path-id)，再挂两个
    {items} 非分页 verb：
    - get_all(group_ids)：required Set query（≥1），repeated query ?group_ids=A&group_ids=B（非
      chunk，列表通常小无 413 风险），server 去重；空列表 SDK 侧 fail-loud。
    - list_options(check_type=)：检验类型码表，{items} 非分页。
    filter_keys（§6）：group_name / material(bool) / check_group(bool) / general(bool) /
      check_group_code / material_id / check_type_code / check_method_code / check_standard_code /
      status(multi)——bool filter 透传需序列化为字符串 'true'/'false'（值由调用方给字符串）。

    TODO: live qm __schema 复核端点单复数/filter_keys（parity 阶段校正）。
    """

    MOD = "qm"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/rule-groups/page"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/rule-groups/{entity_id}"

    def list(self, *, filter: Optional[dict] = None, size: int = 20, all: bool = True) -> Page:
        return self._list(dict(filter or {}), size, all)

    def get(self, entity_id: str) -> dict:
        return self._get(entity_id)

    def get_all(self, group_ids: list) -> Page:
        """GET /rule-groups/get-all?group_ids=A&group_ids=B... —— 返 {items} 非分页。

        group_ids 必传 ≥1，空列表 fail-loud（不发请求）。list 透传成 repeated query，**不** join
        成逗号串、**不** chunk（列表小无 413 风险）。
        """
        if not group_ids:
            raise ValueError(
                "qm.rule_group.get_all() 需要非空 group_ids（≥1）—— 缺则不发查询（fail-loud）"
            )
        url = self._base() + f"/v2/api/tenants/{self._tenant_id()}/rule-groups/get-all"
        # group_ids 保持 list（transport doseq → repeated query），绝不 join。
        raw = self._http.get_json(url, params={"group_ids": list(group_ids)})
        return _wrap_items(raw)

    def list_options(self, check_type: Optional[str] = None) -> Page:
        """GET /rule-groups/options[?check_type=] —— 返 {items} 非分页。"""
        url = self._base() + f"/v2/api/tenants/{self._tenant_id()}/rule-groups/options"
        params: dict = {}
        if check_type is not None:
            params["check_type"] = check_type
        raw = self._http.get_json(url, params=params)
        return _wrap_items(raw)


# ============================================================
# check_sheet：list / list_items(POST 分页) / search_by_lot / get / get_by_no
# ============================================================

class CheckSheetEntity(PostPagedEntity):
    """qm.check_sheet（custom-verbs）：检验单。

    继承 PostPagedEntity（因 list_items 是 POST 分页），但**标准 list 仍是 GET 分页**——故
    list() 显式走 self._list_get()（GET），list_items() 才走继承的 POST 分页 _list()。

    verb：
    - list(GET /check-sheets/page 分页)
    - list_items(POST /check-sheets/items 分页：filter 进 body、page/size 进 query、
      post_page+iterate_all，照 wm.available_stock；body 是 Jackson SNAKE_CASE)
    - search_by_lot(route_id/route_step_id/ref_no/lot_name 四参全 required reverse-lookup，
      缺任一 SDK 侧 fail-loud；返 {items} 非分页)
    - get(path-id 内部 id)
    - get_by_no(check_sheet_no 业务号查；与 get 是两条不同 verb，path 段不同，不合并)
    ⚠️ get 与 get_by_no 取同一记录须返同一对象（#15 补的 AC）。
    filter_keys（§6）：check_sheet_no / statuses(multi) / delivered_by / delivered_org_id /
      start_delivery_date(date) / end_delivery_date(date) / check_type_code / my_only(bool)。
      date 是 date(YYYY-MM-DD) 非 datetime（区别于 inspection_lot 的 start_date/end_date）。

    TODO: live qm __schema 复核端点单复数/filter_keys/path 段（parity 阶段逐字核对）。
    """

    MOD = "qm"

    def _list_path(self, tenant_id: str) -> str:
        # PostPagedEntity._list（list_items 用）的端点：POST 分页。
        return f"/v2/api/tenants/{tenant_id}/check-sheets/items"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/check-sheets/{entity_id}"

    def list(self, *, filter: Optional[dict] = None, size: int = 20, all: bool = True) -> Page:
        """标准 list：GET /check-sheets 分页（**裸路径无 /page 后缀**，对齐 CLI getPage）。

        因本类继承 PostPagedEntity（list_items 用），标准 GET 分页走 _sub_list（GET get_page+
        iterate_all），**不**调被覆写成 POST 的 _list。CLI 真端点是裸 /check-sheets（page/size
        进 query），非 /check-sheets/page——parity live 校正（旧 /page 后缀 404）。
        """
        return self._sub_list(
            f"/v2/api/tenants/{self._tenant_id()}/check-sheets",
            params=dict(filter or {}),
            size=size,
            all_pages=all,
        )

    def list_items(self, *, filter: Optional[dict] = None, size: int = 20, all: bool = True) -> Page:
        """POST 分页（PostPagedEntity._list）：filter 进 body、page/size 进 query、post_page+iterate_all。

        区别于 inspection_order.list_unqualified_items 的 POST **非**分页——这里翻页取全量。
        body 是 CheckSheetItemQueryRequest（Jackson SNAKE_CASE，调用方给 snake_case filter dict）。
        """
        return self._list(dict(filter or {}), size, all)

    def search_by_lot(self, *, route_id: str, route_step_id: str, ref_no: str, lot_name: str) -> Page:
        """GET reverse-lookup，4 参全 required —— 缺任一 fail-loud（不发请求）；返 {items} 非分页。"""
        missing = [
            name
            for name, val in (
                ("route_id", route_id),
                ("route_step_id", route_step_id),
                ("ref_no", ref_no),
                ("lot_name", lot_name),
            )
            if not val
        ]
        if missing:
            raise ValueError(
                f"qm.check_sheet.search_by_lot() 缺必填参数 {missing} —— "
                "route_id/route_step_id/ref_no/lot_name 四参均必填（不发空查询）。"
            )
        url = self._base() + f"/v2/api/tenants/{self._tenant_id()}/check-sheets/lots"
        raw = self._http.get_json(url, params={
            "route_id": route_id,
            "route_step_id": route_step_id,
            "ref_no": ref_no,
            "lot_name": lot_name,
        })
        return _wrap_items(raw)

    def get(self, entity_id: str) -> dict:
        """GET path-id（内部 id）。"""
        return self._get(entity_id)

    def get_by_no(self, check_sheet_no: str) -> dict:
        """GET /check-sheets/by-no/{check_sheet_no}（业务号查）。与 get 是两条不同 verb，不合并。"""
        url = self._base() + f"/v2/api/tenants/{self._tenant_id()}/check-sheets/by-no/{check_sheet_no}"
        return self._http.get_json(url)


# ============================================================
# reject_order：list(8 multi) / get(repair_code multi) / list_by_lot / list_nonqualified_types
# ============================================================

class RejectOrderEntity(PagedEntity):
    """qm.reject_order（custom-verbs）：不合格品处理单。

    verb：
    - list(GET /reject-orders/page；28 filter，**8 个 multi**：statuses/defect_codes/source_codes/
      supply_codes/nonqualified_type_codes/area_ids/line_ids/approval_statuses——给 list 透传成
      repeated query，**绝不** join 逗号串)
    - get(entity_id, repair_code=)：path-id + 可选 repair_code multi（query scope 内嵌维修史，
      非 path）——区别于纯 get(id)
    - list_by_lot(inspection_lot_id)：GET path-id，非分页 {items}（与 inspection_order.list_by_lot
      同构但端点不同）
    - list_nonqualified_types()：无参码表 verb，{items}，供 agent code→label 翻译
    filter_keys（§6）：8 multi（见上）+ material_id / supplier_id / reject_order_no /
      inspection_order_no / start_delivery_date(date) / end_delivery_date(date) /
      start_check_date(date) / end_check_date(date) / po_id / mo_id / so_id。date 全 date 非 datetime。

    TODO: live qm __schema 复核端点单复数/filter_keys（parity 阶段校正）。
    """

    MOD = "qm"

    def _list_path(self, tenant_id: str) -> str:
        # 裸路径无 /page 后缀（对齐 CLI getPage：page/size 进 query）——旧 /page 后缀 404。
        return f"/v2/api/tenants/{tenant_id}/reject-orders"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/reject-orders/{entity_id}"

    def list(self, *, filter: Optional[dict] = None, size: int = 20, all: bool = True) -> Page:
        # 8 个 multi-filter 在 filter dict 给 list，透传时保持 list（transport doseq → repeated query）。
        return self._list(dict(filter or {}), size, all)

    def get(self, entity_id: str, *, repair_code: Optional[list] = None) -> dict:
        """GET /reject-orders/{id}[?repair_code=A&repair_code=B] —— repair_code 是 query scope（multi）。

        repair_code 给 list 时透传成 repeated query（scope 内嵌维修史），**非** path、**不** join。
        """
        url = self._base() + f"/v2/api/tenants/{self._tenant_id()}/reject-orders/{entity_id}"
        params: dict = {}
        if repair_code:
            params["repair_code"] = list(repair_code)
        return self._http.get_json(url, params=params or None)

    def list_by_lot(self, inspection_lot_id: str) -> Page:
        """GET path-id（inspection_lot_id 进 path 段，非 query）；返 {items} 非分页。"""
        url = (
            self._base()
            + f"/v2/api/tenants/{self._tenant_id()}/reject-orders/by-lot/{inspection_lot_id}"
        )
        raw = self._http.get_json(url)
        return _wrap_items(raw)

    def list_nonqualified_types(self) -> Page:
        """GET 主数据码表（无参）；返 {items} 非分页（agent 用它把码翻译成 label）。"""
        url = self._base() + f"/v2/api/tenants/{self._tenant_id()}/reject-orders/nonqualified-type-code"
        raw = self._http.get_json(url)
        return _wrap_items(raw)


# ============================================================
# inspection_lot：list / get / list_partials / check_and_next(?id=)
# ============================================================

class InspectionLotEntity(PagedEntity):
    """qm.inspection_lot（custom-verbs）：检验批。

    **双时间体系坑**（§6 行 974）：同一 list 上两套时间格式并存——
      - start_delivery_date / end_delivery_date 是 **date**（YYYY-MM-DD）
      - start_date / end_date 是 **datetime ISO**（YYYY-MM-DDTHH:mm:ss）
    SDK **只透传不校验/不强转**，调用方须按对应 key 给对的格式（传错后端静默忽略，parity 也测不出）。

    verb：
    - list(GET /inspection-lots/page，/page 后缀)
    - get(path-id)
    - list_partials(entity_id)：GET /inspection-lots/{id}/partials 拆批子批；path-id+子路径，{items} 非分页
    - check_and_next(lot_id)：GET 取「下一检验目标实例」(NewInstanceVO)，后端用 **?id= query**（非 path）
    filter_keys（§6）：check_type_codes(**multi，codes 复数**，与 reject/inspection-order 的单值
      check_type_code 不同) / inspection_lot_name / ref_no / external_ref_no / check_sheet_no /
      material_id / priority / statuses(multi) / supplier_id / start_delivery_date(date) /
      end_delivery_date(date) / start_date(datetime) / end_date(datetime) / contract_id / so_id /
      product_code / my_only(bool) / area_id / line_id。

    TODO: live qm __schema 复核端点单复数/filter_keys/?id= 参数名（parity 阶段校正）。
    """

    MOD = "qm"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/inspection-lots/page"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/inspection-lots/{entity_id}"

    def list(self, *, filter: Optional[dict] = None, size: int = 20, all: bool = True) -> Page:
        # 双时间 key 与 multi(check_type_codes/statuses) 均原样透传（list 保 list、date/datetime 不强转）。
        return self._list(dict(filter or {}), size, all)

    def get(self, entity_id: str) -> dict:
        return self._get(entity_id)

    def list_partials(self, entity_id: str) -> Page:
        """GET /inspection-lots/{id}/partials（path-id+子路径）；返 {items} 非分页。"""
        url = (
            self._base()
            + f"/v2/api/tenants/{self._tenant_id()}/inspection-lots/{entity_id}/partials"
        )
        raw = self._http.get_json(url)
        return _wrap_items(raw)

    def check_and_next(self, lot_id: str) -> dict:
        """GET .../inspection-lots/checkAndNext?id=lot_id —— id 走 **query**（非 path）。

        与 get(id) 走 path 对照：两者都吃 id 但 wire 方式不同（易写错点）。返 NewInstanceVO。
        端点段是 camelCase checkAndNext（对齐 CLI 真路径），非 kebab check-and-next。
        """
        url = self._base() + f"/v2/api/tenants/{self._tenant_id()}/inspection-lots/checkAndNext"
        return self._http.get_json(url, params={"id": lot_id})


# ============================================================
# inspection_order：7-verb 最重
# ============================================================

class InspectionOrderEntity(PagedEntity):
    """qm.inspection_order（custom-verbs，**7 verb 最重**）：检验单（检验结果）。

    verb：
    - list(GET /inspection-orders/page；29 filter，默认 created_date DESC 排序由**后端给**，SDK 不重排保 parity)
    - get(path-id 检验结果详情)
    - list_by_lot(inspection_lot_id)：GET path-id，{items} 非分页
    - get_belong_info(entity_id, project=, eqpt=)：GET /{id}/belong-info?project=&eqpt= —— **两个独立
      bool toggle**（可都 True），序列化为 query 'true'/'false'
    - get_reject_order_id(inspection_order_id)：GET reject-order-by-io?inspection_order_id=（**query-id
      非 path**）→ 返 **RejectOrderDetailVO（跨实体类型）**——方法名/返回类型标清，避免 agent 误判返
      inspection-order
    - list_unqualified_items(filter=)：**POST 非分页**（post_json 取 {items} 包 Page，**不** iterate）——
      区别于 check_sheet.list_items 的 POST **分页**（误用 post_page+iterate_all 即错）
    - list_basic_info(filter=)：GET 某源单历史已检单，7 filter(origin_ref_*/material_id/product_code/
      rule_group_id/checked_by)，{items} 非分页
    filter_keys（§6）：inspection_lot_id / inspection_lot_name / inspection_order_no / check_sheet_no /
      statuses(multi) / qualified(bool) / check_type_code / material_id / supplier_id /
      start_check_date(date) / end_check_date(date) / start_delivery_date(date) / end_delivery_date(date)
      / contract_id / so_id / product_code / report_generate_allowed(bool) / report_generate(bool) /
      report_download(bool) / ref_item_id。date 全 date 非 datetime（区别 inspection_lot）。

    TODO: live qm __schema 复核端点单复数/filter_keys/?id= 参数名/各 verb 子路径（parity 阶段逐字核对）。
    """

    MOD = "qm"

    def _list_path(self, tenant_id: str) -> str:
        # 裸路径无 /page 后缀（对齐 CLI getPage：page/size 进 query）——旧 /page 后缀 404。
        return f"/v2/api/tenants/{tenant_id}/inspection-orders"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/inspection-orders/{entity_id}"

    def list(self, *, filter: Optional[dict] = None, size: int = 20, all: bool = True) -> Page:
        # 默认 created_date DESC 由后端排，SDK 不重排（保 parity）。multi/bool 原样透传。
        return self._list(dict(filter or {}), size, all)

    def get(self, entity_id: str) -> dict:
        return self._get(entity_id)

    def list_by_lot(self, inspection_lot_id: str) -> Page:
        """GET path-id（inspection_lot_id 进 path 段，非 query）；返 {items} 非分页。"""
        url = (
            self._base()
            + f"/v2/api/tenants/{self._tenant_id()}/inspection-orders/by-lot/{inspection_lot_id}"
        )
        raw = self._http.get_json(url)
        return _wrap_items(raw)

    def get_belong_info(self, entity_id: str, *, project: bool = False, eqpt: bool = False) -> dict:
        """GET /inspection-orders/{id}/belong-info?project=&eqpt= —— project/eqpt 两个独立 bool toggle。

        两者可都 True；序列化为 query 'true'/'false'（透传约定，后端 query 收字符串非 Python bool）。
        date filter 全是 date 非 datetime（区别 inspection_lot）。
        """
        url = (
            self._base()
            + f"/v2/api/tenants/{self._tenant_id()}/inspection-orders/{entity_id}/belong-info"
        )
        params = {
            "project": _bool_flag(project),
            "eqpt": _bool_flag(eqpt),
        }
        return self._http.get_json(url, params=params)

    def get_reject_order_id(self, inspection_order_id: str) -> dict:
        """GET .../inspection-orders/get-reject-order-id?inspection_order_id= —— **query-id 非 path**。

        ⚠️ 返回的是 **RejectOrderDetailVO（跨实体类型）**，不是 inspection-order——调用方据
        reject_order_* 键消费，勿误判返 inspection-order。
        """
        url = (
            self._base()
            + f"/v2/api/tenants/{self._tenant_id()}/inspection-orders/get-reject-order-id"
        )
        return self._http.get_json(url, params={"inspection_order_id": inspection_order_id})

    def list_unqualified_items(self, *, filter: Optional[dict] = None) -> Page:
        """**POST 非分页**：post_json 取 {items} 包 Page，**不** iterate（无 page/size query）。

        区别于 check_sheet.list_items 的 POST **分页**——误用 post_page+iterate_all 即错。
        body 是 InspectionUnQualifiedQueryVO（SNAKE_CASE，调用方给 snake_case filter dict）。
        """
        url = (
            self._base()
            + f"/v2/api/tenants/{self._tenant_id()}/inspection-orders/un-qualified-items"
        )
        raw = self._http.post_json(url, body=dict(filter or {}))
        return _wrap_items(raw)

    def list_basic_info(self, *, filter: Optional[dict] = None) -> Page:
        """GET 某源单历史已检单（7 filter）；返 {items} 非分页。"""
        url = (
            self._base()
            + f"/v2/api/tenants/{self._tenant_id()}/inspection-orders/basic-info"
        )
        raw = self._http.get_json(url, params=dict(filter or {}) or None)
        return _wrap_items(raw)


def _bool_flag(val) -> str:
    """bool flag 透传序列化：Python True/False → 'true'/'false' 字符串（CLI 透传约定，
    后端 query 收字符串而非 Python bool）；已是字符串则原样透传。
    """
    if isinstance(val, bool):
        return "true" if val else "false"
    return val
