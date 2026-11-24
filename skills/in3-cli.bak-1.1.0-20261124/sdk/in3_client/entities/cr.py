"""cr 模块 entity（#13 M2 子集）：service_person / fee_category / work_log_category。

本模块在 SDK 是首批 cr 实体（命名空间装配由收口阶段做，这里只写 entity 类）。

cr 的结构性坑（§6 行 999-1076）：
- 端点是 **app-prefix** 形（/flsc/...、/ssme/...）——**非** /v2/api/tenants/<tid>/ 模板。
  与 md/mm/wm/sd 的 tenant-templated 路径根本不同。本片三实体都覆写 `_list_path(tenant_id)`
  **忽略** tenant_id 参数、返回固定 app-prefix 路径即可（base = cred.base_url('cr') 已是
  api_host + /mom/cr，config._BASE_SUFFIX['cr'] 已支持，**无需改 config.py**）。
- 三个 list-only/裸 List 实体返回裸 List<T>（非 Spring Page 信封）→ envelope.normalize 对裸
  list 返空/抛错。一律走 #10 基座的 `_list_bare`（→ http._request 拿原值 → coerce_to_page
  包 Page(items, page=0, total=len, has_next=False)），**绝不**过 normalize / get_json 的 or {}。
- fee_category 的 path 含 /page 但仍是裸 List（§6 'despite path /page'）——别被 path 名骗去当
  分页端点，仍走 _list_bare。
- service_person.query 的 q 是 required → 缺 q fail-loud raise ValueError，绝不发空查询。
- 只读边界：cr 全部 verb 是 list/get/query（读），本片只生成 list/query，无写。

收口/M5 决议待办（见返回 blockers）：cr 路径非 tenant-templated 的处理目前是 entity-local
（覆写 _list_path 忽略 tenant_id）；若后续要把「按模块取非模板 base 路径」上升为 base 层
约定，需收口阶段统一决策（本片不碰 frozen base.py/config.py）。
"""
from __future__ import annotations

from typing import Optional

from ..envelope import Page
from .base import PagedEntity, PostPagedEntity


class ServicePersonEntity(PagedEntity):
    """cr.service_person：裸 List<TenantUserVO> + query(*, q) 自定义 verb。

    list 返回裸 List（无分页、无 filter）→ _list_bare 包 Page；size/all 形参仅为 API 形状统一，
    实际忽略（后端不认 page/size，故不拼进 query）。query 是 GET service-staffs?q=<text>，
    q 必填——缺则 fail-loud。查的是 TenantUserVO（用户）不是服务单业务数据，字段是
    username/display_name 等。

    TODO: live cr __schema 复核端点单复数/filter_keys（parity 阶段校正）——
      list 路径 /flsc/service-staffs、query 路径同端点带 ?q= 均按 §6 文档逐字写，未 live 验。
    """

    MOD = "cr"

    def _list_path(self, tenant_id: str) -> str:
        # 忽略 tenant_id：cr 端点非 /v2/api/tenants/<tid>/ 模板，固定 app-prefix。
        return "/flsc/service-staffs"

    def list(self, *, size: int = 200, all: bool = True) -> Page:
        # 裸 List 端点：无分页/无 filter，size/all 仅形状统一不参与请求。
        return self._list_bare(None, size, all)

    def query(self, *, q: str) -> Page:
        # q 必填（schema required:true）→ fail-loud，绝不发空查询。
        if not q:
            raise ValueError("cr.service_person.query 需要非空 q —— 缺则不发查询（fail-loud）")
        return self._list_bare({"q": q}, 200, True)


class FeeCategoryEntity(PagedEntity):
    """cr.fee_category（list-only）：裸 List 包 Page，无 filter/分页/get。

    端点 path 含 /page 但实际返回裸 List（§6 'despite path /page'）→ 仍走 _list_bare 而非
    post_page/get_page，别被 path 名字骗。忠实不暴露 get（无 _get_path）。

    TODO: live cr __schema 复核端点单复数/filter_keys（parity 阶段校正）——
      路径 /flsc/fee-categories/page 按 §6 文档写，未 live 验。
    """

    MOD = "cr"

    def _list_path(self, tenant_id: str) -> str:
        return "/flsc/fee-categories/page"

    def list(self, *, size: int = 200, all: bool = True) -> Page:
        return self._list_bare(None, size, all)


class WorkLogCategoryEntity(PagedEntity):
    """cr.work_log_category（list-only）：裸 List 包 Page，纯字典枚举数据，无 filter/get/分页。

    同 fee_category：裸 List → _list_bare，不走 normalize。

    TODO: live cr __schema 复核端点单复数/filter_keys（parity 阶段校正）——
      路径 /flsc/work-log-categories/page 按 §6 文档写，未 live 验。
    """

    MOD = "cr"

    def _list_path(self, tenant_id: str) -> str:
        return "/flsc/work-log-categories/page"

    def list(self, *, size: int = 200, all: bool = True) -> Page:
        return self._list_bare(None, size, all)


# ---------- #16 M5：cr 非 tenant 路径业务实体（opp / service_order / fee）----------
#
# 三个非协商坑层（issue #16 / §6 行 1041-1073）：
#   ① 非 tenant 路径覆写——_list_path/_get_path 忽略 tenant_id，base 走 cred.base_url('cr')
#      （= api_host+/mom/cr）再拼**各自硬编码**的 app-prefix：
#        opp → /ssme（商机/SSME 子系统）  service_order → /flsc  fee → /flsc/v3（带版本段）
#      三前缀不同源，**别复制错**（fee 的 v3 与 service_order 的无 v3 是真实差异）。
#   ② 两种多值机制不混——opp（GET 端点）多值 filter 走 **repeated query**（filter 进
#      PagedEntity._list 的 base_params → query；list 值由 http/requests 序列化成 repeated key）；
#      service_order/fee（POST 端点）多值进 **body JSON 数组**（filter 进 PostPagedEntity._list
#      的 body → JSON 数组，后端按数组收）。两者机制分离，绝不互相套用。
#   ③ price-privileged fail-loud——fee 查费用金额；若后端/网关按自身授权返回
#      PRIVILEGE_DENIED（非 200）→ http._request 抛
#      HttpError 直接冒泡。fee.list **绝不** try/except 吞成空 Page（否则 agent 误判'真没费用'
#      vs '没权限'）。无 price 角色路径由 no-privilege 桩单测验 fail-loud。
#
# 复用纪律：service_order/fee 的 POST-body 分页直接继承 PostPagedEntity（filter 进 body、page/size
# 进 query、翻页靠 has_next 不靠 total——cr POST 端点 total 可能 null），entity 层不重写 iterate_all
# /unwrap。opp 继承 PagedEntity 复用 GET-query 分页骨架。filter 只透传不做白名单校验：§6 的
# filter_keys 是 PLAN 估值（未 live __schema 复核），硬编白名单会制造假性 fail-loud（同 filters.py
# 对 wm 的判断）——透传更忠实，待 parity 阶段拿到权威 filter_keys 再议。


class OppEntity(PagedEntity):
    """cr.opp（商机）：GET query-string 分页 + get。**simple-list-get**（§6 行 1041，2pt）。

    - list **GET** /ssme/opps/page（filter 透传成 query string、page/size 进 query；继承
      PagedEntity._list 的 GET-query 分页骨架，**绝不**改 POST-body）。
    - get  **GET** /ssme/opps/<id> 返回 OppDetailVO 单条归一记录。
    - 端点 app-prefix /ssme（商机/SSME 子系统）——与 service_order/fee 的 /flsc **不同源**，
      _list_path/_get_path 各自硬编码对的前缀。非 tenant-templated（无 /v2/api/tenants/<tid>/）→
      覆写时忽略 tenant_id 参数。
    - 多值 filter（stage_code/win_flag/status/industry_type 标 multi:true）走 **repeated query**：
      list 透传 dict（list 值由 http 层序列化成 repeated key），不需 fan-out/chunk（非大 id 列表）；
      **不**走 service_order/fee 的 body JSON 数组机制。
    - country/province/city/district 是 integer 类型 filter（地区编码）——dict 值原样透传给 http 层，
      **不**强转 str / 引号包裹（会影响语义）。
    - 时间 filter 按 cr 的 date 形（YYYY-MM-DD）透传，SDK 只透传不强转。

    filter_keys（§6 行 1044，PLAN 估值）：opp_no / opp_name / opp_query / account_id /
      sales_mgr_id / stage_code / win_flag / status / industry_type（+ 地区编码 country/province/
      city/district）。

    TODO: live cr __schema 复核端点单复数/filter_keys/app-prefix（parity 阶段校正）——
      路径 /ssme/opps/page、/ssme/opps/<id> 按 §6 文档逐字写，未 live 验。
    """

    MOD = "cr"

    def _list_path(self, tenant_id: str) -> str:
        # 忽略 tenant_id：非 /v2/api/tenants/<tid>/ 模板，固定 /ssme app-prefix。
        return "/ssme/opps/page"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/ssme/opps/{entity_id}"

    def list(self, *, filter: Optional[dict] = None, size: int = 20, all: bool = True) -> Page:
        # filter 进 base_params → query string（PagedEntity._list 的 GET 路径）；多值 list 值
        # 经 http 层序列化成 repeated query。integer 地区编码原样透传不强转。
        return self._list(dict(filter or {}), size, all)

    def get(self, entity_id: str) -> dict:
        # GET /ssme/opps/<id> 返回 OppDetailVO 单条记录（base._get 拼非 tenant 路径）。
        return self._get(entity_id)


class ServiceOrderEntity(PostPagedEntity):
    """cr.service_order（服务单）：POST-body 分页 + 深层嵌套 get。**fanout-gotcha**（§6 行 1052，3pt）。

    - list **POST** /flsc/service-orders/page（filter 进 JSON body、page/size 进 query；继承
      PostPagedEntity._list，复用 http.post_page + iterate_all——**绝不**退回 GET-query 分页）。
      翻页靠 **has_next**（last 字段）**不靠 total**（cr POST 端点 total 可能 null，按 total 会死循环）。
    - get  **GET** /flsc/service-orders/<id> 返回 ServiceOrderDetailVO，含深层嵌套
      work_logs / dispatch_history / evaluation_items —— **原样穿过不展平**（base._get 返原 dict）。
    - 端点 app-prefix /flsc 且非 tenant-templated → 覆写 _list_path/_get_path 忽略 tenant_id。
      与 opp 的 /ssme、fee 的 /flsc/v3 各自硬编码别混。
    - 多值 filter（status/service_staff/service_type_codes/service_order_types/service_areas/
      service_groups/creator_ids/work_log_staff 标 multi:true）进 **body JSON 数组**（后端按数组收）——
      **不**走 opp/wm 的 repeated-query 机制（GET vs POST 多值不混）。
    - 时间 filter 是 date 形（YYYY-MM-DD，schema type:date）：一堆成对 *_start/*_end
      （start_date/end_date、appointment_date_start/end、require_complete_date_start/end）——透传
      dict 即可，不做语义校验、不套 sd 的 datetime ISO。

    filter_keys（§6 行 1055，PLAN 估值）：service_order_sn / project_name_and_contract_no /
      account_name / so_no_and_so_name / status / service_staff / service_type_codes /
      start_date / end_date / appointment_date_start / appointment_date_end（含上述其余 multi 键）。

    TODO: live cr __schema 复核端点单复数/filter_keys/app-prefix（parity 阶段校正）——
      路径 /flsc/service-orders/page、/flsc/service-orders/<id> 按 §6 文档逐字写，未 live 验。
    """

    MOD = "cr"

    def _list_path(self, tenant_id: str) -> str:
        return "/flsc/service-orders/page"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/flsc/service-orders/{entity_id}"

    def list(self, *, filter: Optional[dict] = None, size: int = 20, all: bool = True) -> Page:
        # filter 进 body（PostPagedEntity._list）；多值 list 值留在 JSON 数组；date 形 *_start/*_end
        # 原样透传。翻页靠 has_next（iterate_all），绝不按 total。
        return self._list(dict(filter or {}), size, all)

    def get(self, entity_id: str) -> dict:
        # GET /flsc/service-orders/<id> 返深层嵌套 VO —— base._get 返原 dict，原样穿过不展平。
        return self._get(entity_id)


class FeeEntity(PostPagedEntity):
    """cr.fee（服务单费用）：POST-body 分页，**list-only**，**price-privileged**。**fanout-gotcha**（§6 行 1064，3pt）。

    - list **POST** /flsc/v3/service-orders/fees/page（filter 进 body、page/size 进 query；继承
      PostPagedEntity._list，同 service_order 的 POST-page 机制）。端点带 **/flsc/v3** 版本段——
      与 service_order 的 /flsc（无 v3）**不同**，path 各自硬编码别复制错。非 tenant-templated。
    - **无 get**（schema 无 get verb）——忠实只暴露 list，绝不假装 get（不定义 _get_path/get）。
    - **price-privileged fail-loud**：查的是费用金额；若后端/网关按自身授权返回
      PRIVILEGE_DENIED（非 200）→ http._request 抛 HttpError
      直接冒泡。list() **绝不** try/except 吞成空 Page —— agent 要能区分'真没费用'和'没权限'。
      （此处不写任何错误吞没逻辑即满足 fail-loud：错误天然冒泡。）
    - 多值 filter（fee_ids/service_staffs/service_types/fee_verify_status 标 multi:true）进
      **body JSON 数组**（POST 机制，非 repeated query）。
    - 时间 filter 是 fee_date_from/fee_date_to（date 形 YYYY-MM-DD，非 datetime），只透传不强转。

    filter_keys（§6 行 1066，PLAN 估值）：service_order_sn / account_name / so_text /
      fee_date_from / fee_date_to / service_types / service_order_status / service_staffs /
      fee_ids / fee_verify_status。

    TODO: live cr __schema 复核端点单复数/filter_keys/app-prefix（parity 阶段校正）——
      路径 /flsc/v3/service-orders/fees/page 按 §6 文档逐字写，未 live 验。
      has-privilege parity 需 price_viewer 角色 tenant，延后到测试环境就绪（no-privilege fail-loud
      已由桩单测覆盖）。
    """

    MOD = "cr"

    def _list_path(self, tenant_id: str) -> str:
        # /flsc/v3（带版本段）—— 与 service_order 的 /flsc（无 v3）不同，别复制错。
        return "/flsc/v3/service-orders/fees/page"

    def list(self, *, filter: Optional[dict] = None, size: int = 20, all: bool = True) -> Page:
        # POST-body 分页（PostPagedEntity._list）；多值进 body 数组、date 形透传。
        # PRIVILEGE_DENIED → http._request 抛 HttpError 冒泡（此处不吞，即 fail-loud）。
        return self._list(dict(filter or {}), size, all)
