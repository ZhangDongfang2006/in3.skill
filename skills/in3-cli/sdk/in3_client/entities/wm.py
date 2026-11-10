"""wm 模块 entity。v1 #4 落 available_stock（POST 分页 + by_materials fan-out）。

端点（ibrain-wm/apps/cli src/commands/available-stock.ts，base = api_host + /mom/wm）：
  POST /v2/api/tenants/<tid>/stocks/available-stocks/page  —— filter 在 body、page/size 在 query

已对真后端核实的坑层：
- 空 filter 返 0 条 → **by_materials 是主入口**（北极星用它查 Top10 物料库存）。
- 可用库存字段 = `available_qty`（**非** issue 猜的 total_quantity；可为负=超提）。
- 记录**无 top-level id** → fan-out 去重主键 = (material_id, plant_no)。
- multi-filter 并集语义 → 回挂 _matched_filter_values.material_ids（返回 ∩ 请求）。
"""
from __future__ import annotations

from typing import Optional

from ..auth import Session
from ..config import Credentials
from ..envelope import Page
from ..gotchas import as_string_array, chunk_material_ids, dedup_by, fan_out, matched_filter_values
from ..http import HttpClient
from ..pagination import iterate_all
from .base import PagedEntity, PostPagedEntity


def _bool_flag(val) -> str:
    """bool flag 透传序列化：Python True/False → 'true'/'false' 字符串（CLI 透传约定，
    后端 query 收字符串而非 Python bool）；已是字符串则原样透传。
    """
    if isinstance(val, bool):
        return "true" if val else "false"
    return val


def _serialize_bool_params(params: dict) -> dict:
    """通用 bool 序列化：就地把 params dict 里**所有** Python bool 值转 'true'/'false' 字符串。

    不依赖白名单——覆盖任意具名参 + filter dict 透传进来的 bool flag（storage_bin 20+ flag 场景）。
    复用 _bool_flag：非 bool（int/str/list/已是 'true'/'false' 字符串）原样保留，绝不误伤。
    """
    for key, val in params.items():
        if isinstance(val, bool):
            params[key] = _bool_flag(val)
    return params

# 可用库存记录的去重主键（无 top-level id）。
_DEDUP_KEYS = ("material_id", "plant_no")
# fan-out 分块大小（≤80，防大 id 列表 413/截断）。
_CHUNK = 80


class AvailableStockEntity:
    MOD = "wm"

    def __init__(self, cred: Credentials, session: Session, http: HttpClient):
        self._cred = cred
        self._session = session
        self._http = http

    def _url(self) -> str:
        tid = self._session.token().tenant_id
        return self._cred.base_url(self.MOD) + f"/v2/api/tenants/{tid}/stocks/available-stocks/page"

    def list(self, *, filter: Optional[dict] = None, size: int = 20, all: bool = True) -> Page:
        url = self._url()
        body = dict(filter or {})

        def fetch(page_no: int) -> Page:
            return self._http.post_page(
                url, body=body, params={"page": str(page_no), "size": str(size)}, requested_size=size
            )

        if not all:
            return fetch(0)
        agg = iterate_all(fetch)
        return Page(items=agg.items, page=None, total=None, has_next=agg.truncated, truncated=agg.truncated)

    def by_materials(self, ids: list, size: int = 200) -> Page:
        """对一批 material_id fan-out 取可用库存：≤80 分块 → 合并 → 按 (material_id,plant_no)
        去重 → 回挂 _matched_filter_values。任一块失败整体抛（fail-loud，绝不静默返部分）。
        空 ids 不发请求、返空 Page。
        """
        if not ids:
            return Page(items=[], page=None, total=None, has_next=False)

        merged: list = []
        for chunk in chunk_material_ids(ids, _CHUNK):
            # 任一块抛 → 直接冒泡，绝不 try/except 吞成空集。
            merged.extend(self.list(filter={"material_ids": chunk}, size=size, all=True).items)

        merged = dedup_by(merged, _DEDUP_KEYS)
        matched = matched_filter_values(merged, ids, key="material_id")
        for rec in merged:
            rec["_matched_filter_values"] = {"material_ids": matched}
        return Page(items=merged, page=None, total=None, has_next=False)


# ---------- wm.stock：4 物理视图 + fan-out（#6）----------

class StockValidationError(Exception):
    """stock 入参校验失败（单/多值互斥、material 视图缺 material）。"""


# 视图 → 端点路径（单/复数差异照实，不可写错）。
_STOCK_VIEWS = {
    "material": "material-stocks/page",          # 单数 page
    "bin": "bin-stocks/pages",                    # 复数 pages
    "storage_location": "storage-location-stocks/pages",
    "storage_bin": "storage-bin-stocks/pages",
}
_STOCK_ALL_PAGE_SIZE = 200
_STOCK_ALL_MAX = 1000


class StockEntity:
    """wm.stock 4 视图：material / bin / storage_location / storage_bin。

    单值 material_id → 单次（可 all 翻页 page_size=200/封顶 max_items）；多值 material_ids →
    并发 fan-out（每 id 一次、skip-on-error、聚合页）。单/多值互斥；material 视图缺 material fail-loud。
    入参先过 as_string_array 清洗（剔 ""/"undefined"/非串）。total 不可信置 None（与 CLI 的 ||len
    安全差异：SDK 不把不可信 total 当真）。
    """

    MOD = "wm"

    def __init__(self, cred: Credentials, session: Session, http: HttpClient):
        self._cred = cred
        self._session = session
        self._http = http

    def _url(self, view: str) -> str:
        tid = self._session.token().tenant_id
        return self._cred.base_url(self.MOD) + f"/v2/api/tenants/{tid}/stocks/{_STOCK_VIEWS[view]}"

    def _query(self, view, enforce_material, material_id, material_ids, filter, all, size,
               concurrency, max_items) -> Page:
        cleaned = as_string_array(material_ids)
        if cleaned and material_id:
            raise StockValidationError("--material-id (单值) 与 --material-ids (多值) 互斥，二选一")
        if enforce_material and not material_id and not cleaned:
            raise StockValidationError("stock material 需要 material_id 或 material_ids")

        url = self._url(view)
        base_params = dict(filter or {})

        # 多值 → 并发 fan-out 聚合页（**不**走 all 翻页）。
        if cleaned:
            def fetch_one(mid: str) -> Page:
                params = {**base_params, "material_id": mid, "page": "0", "size": str(size)}
                return self._http.get_page(url, params, requested_size=size)
            return fan_out(cleaned, fetch_one, concurrency)

        # 单值（或无 material 的非 material 视图）。
        params0 = dict(base_params)
        if material_id:
            params0["material_id"] = material_id
        if not all:
            return self._http.get_page(
                url, {**params0, "page": "0", "size": str(size)}, requested_size=size
            )
        return self._iterate_all(url, params0, max_items)

    def _iterate_all(self, url, params0, max_items) -> Page:
        """单值 all 翻页：page_size=200、靠 has_next（last/启发式）、封顶 max_items 截断标 truncated。"""
        items: list = []
        page_no = 0
        last_total = None
        truncated = False
        has_next = True
        while True:
            page = self._http.get_page(
                url, {**params0, "page": str(page_no), "size": str(_STOCK_ALL_PAGE_SIZE)},
                requested_size=_STOCK_ALL_PAGE_SIZE,
            )
            items.extend(page.items)
            last_total = page.total
            if len(items) >= max_items:
                items = items[:max_items]
                truncated = True
                has_next = True
                break
            if not page.has_next:
                has_next = False
                break
            page_no += 1
        # total 仅当可信（非 None 且 >= 累积条数）才取，否则 None（绝不把不可信 total 当真）。
        total = last_total if (last_total is not None and last_total >= len(items)) else None
        return Page(items=items, page=0, total=total, has_next=has_next, truncated=truncated)

    # ---- 4 视图入口 ----
    def material(self, *, material_id=None, material_ids=None, filter=None, all=False,
                 size=20, concurrency=16, max_items=_STOCK_ALL_MAX) -> Page:
        return self._query("material", True, material_id, material_ids, filter, all, size, concurrency, max_items)

    def bin(self, *, material_id=None, material_ids=None, filter=None, all=False,
            size=20, concurrency=16, max_items=_STOCK_ALL_MAX) -> Page:
        return self._query("bin", False, material_id, material_ids, filter, all, size, concurrency, max_items)

    def storage_location(self, *, material_id=None, material_ids=None, filter=None, all=False,
                         size=20, concurrency=16, max_items=_STOCK_ALL_MAX) -> Page:
        return self._query("storage_location", False, material_id, material_ids, filter, all, size, concurrency, max_items)

    def storage_bin(self, *, material_id=None, material_ids=None, filter=None, all=False,
                    size=20, concurrency=16, max_items=_STOCK_ALL_MAX) -> Page:
        return self._query("storage_bin", False, material_id, material_ids, filter, all, size, concurrency, max_items)


# ---------- wm.move_type / wm.rd_category：M2 bare-array list-only 主数据（#13）----------


class MoveTypeEntity(PagedEntity):
    """wm.move_type（移动类型, 主数据）：list-only 裸数组。

    后端返**裸 JSON 数组**（无 Spring Page 信封）→ 走 _list_bare/coerce_to_page 包 Page
    (items=arr, page=0, total=len, has_next=False)，**不**经 envelope.normalize（裸 list 进
    normalize 会因 _extract_total 调 .get 抛 AttributeError）、**不**被 get_json `or {}` 吞空。
    纯参考主数据，无 /{id} get —— 忠实不暴露 .get（照 sd.sales_order_item 诚实约定）。
    filter：move_direction(I=入/O=出) / move_type_no / disabled（disabled 是 bool flag →
    透传序列化成字符串 'true'/'false'，不传 Python True/False）。

    TODO: live wm __schema 复核端点单复数/filter_keys（parity 阶段校正）——
      端点单复数需 `exec wm move-type list --help` 抓 path 确认（暂照 /move-types 写）。
    """

    MOD = "wm"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/move-types"

    def list(
        self,
        *,
        filter=None,
        move_direction=None,
        move_type_no=None,
        disabled=None,
        size: int = 20,
        all: bool = True,
    ) -> Page:
        params = dict(filter or {})
        if move_direction is not None:
            params["move_direction"] = move_direction
        if move_type_no is not None:
            params["move_type_no"] = move_type_no
        if disabled is not None:
            params["disabled"] = _bool_flag(disabled)
        return self._list_bare(params, size, all)


class RdCategoryEntity(PagedEntity):
    """wm.rd_category（收发类别, 主数据）：最薄 list-only 裸数组，全量无 filter。

    schema description 明写 '全量, 无 filter' → list() 不收业务 filter 参数（仅 size/all）。
    后端返裸数组 → _list_bare/coerce_to_page 包 Page（同 move_type，绕 normalize/get_json 吞空坑）。
    无 /{id} get —— 不暴露 .get。

    端点（live parity 校正 2026-06-03，CLI src/commands/rd-category.ts 反查）：
      list = GET .../rd-category/list（**单数 rd-category + /list 后缀** —— 旧 /rd-categories 复数报
             405 方法/路径错；CLI get(.../rd-category/list) 直返裸数组）。
    """

    MOD = "wm"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/rd-category/list"

    def list(self, *, size: int = 20, all: bool = True) -> Page:
        return self._list_bare(None, size, all)


# ============================================================
# #17 M6 · wm 最重模块收口（simple 5 + custom-verbs 10）
# ============================================================
#
# 模块级坑（§6 252-262，全片适用）——逐实体在 docstring 各自重申要点：
# - Spring Slice total=null：base._list / _sub_list 已正确处理（total 不可信置 None +
#   iterate_all 靠 has_next/truncated），**绝不**自己用 .total 判分页（wm-cli 0.1.6 二修过）。
# - datetime vs date 碎到 entity：material_doc/trans_order = ISO datetime
#   (YYYY-MM-DDTHH:mm:ss)；inventory_check_task/check_order/sales_order_shipment = ISO date
#   (YYYY-MM-DD)。SDK 只透传不强转，各 entity docstring 标清两套 key 各自格式。
# - 'items' 双语义：(a) items(id) = 单据明细行（warehouse_request/inventory_check_task，
#   端点 .../<id>/items[/page]）；(b) items 无 id = 跨单行项独立查询（trans_order，收自己的
#   material_id/lot_name/bin_no filter，独立分页端点）。两者签名/端点不混。
# - bool flag 透传序列化成字符串 'true'/'false'（_bool_flag），不传 Python True/False。
# - 命名歧义（docstring 写清边界）：sales_order_shipment（主单据）vs delivery_order（summary
#   旁路 lookup）两个「销售发运单」；check_order 是 wm 侧只读视图（区别 qm 检验单）；
#   wm.unit 是库存单元/SN（非计量单位）；wm.mo 是工单只读视图（非 pp 写接口）。
# - 只读边界：15 个 entity 只生成 list/get/items/lines/details/pending/info/kitting_items/
#   summary/config 类读方法，绝不生成 create/update/delete（wm_config 名字像配置但全是读策略）。
# - sub-list verb（items/lines/details/pending）一律复用 base._sub_list，不重写 iterate_all。
#
# TODO（全片）: live wm __schema / `exec wm <entity> --help` 复核真实 entity 名 / filter_keys /
#   端点单复数与各 custom-verb 子路径形态（多处 PLAN 自标「抓 CLI 确认」），parity 阶段逐字校正。


# ---------- 批 A · simple 5（照 md.MaterialEntity 抄，base 够用）----------


class StorageLocationEntity(PagedEntity):
    """wm.storage_location（库存地点, 主数据）：list-only 裸 Spring 分页，**无 /{id} get**。

    schema description 明写「无 /{id} get，用 --storage-location-no 过滤」→ 忠实不暴露 .get。
    具名 filter 透传：storage_location_no / storage_location_name / key_word；plant flag →
    plant_id query（同 mm.po 的 plant→plant_id 约定）。其余键走 filter dict。

    TODO: live wm __schema 复核端点单复数/filter_keys（暂照 /storage-locations/page 写）。
    """

    MOD = "wm"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/storage-locations/page"

    def list(
        self,
        *,
        filter: Optional[dict] = None,
        storage_location_no=None,
        storage_location_name=None,
        plant=None,
        key_word=None,
        size: int = 20,
        all: bool = True,
    ) -> Page:
        params = dict(filter or {})
        if storage_location_no is not None:
            params["storage_location_no"] = storage_location_no
        if storage_location_name is not None:
            params["storage_location_name"] = storage_location_name
        if plant is not None:
            params["plant_id"] = plant  # plant flag → plant_id query
        if key_word is not None:
            params["key_word"] = key_word
        return self._list(params, size, all)


class StorageBinEntity(PagedEntity):
    """wm.storage_bin（货位, 主数据, 多 bool flag）：list-only，**无 /{id} get**。

    措辞纪律：CONTEXT 禁用「库位」→ docstring/文档一律用「货位」。
    flag 极多（20+，大量 bool 类 not_include_unbound/in_forbidden/out_forbidden/
    default_entry_bin 等）→ 走 **filter dict 透传** + 少量常用具名参（plant/warehouse_no/
    storage_bin_no/bin_type），避免方法签名爆炸。bool flag 透传 query 时序列化成字符串
    'true'/'false'（_bool_flag），不传 Python True/False。plant flag → plant_id query。

    端点（live parity 校正 2026-06-03，CLI src/commands/storage-bin.ts 反查）：
      list = GET .../bins/page（**base 段是 /bins 不是 /storage-bins** —— CLI base10 = .../bins）。
    """

    MOD = "wm"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/bins/page"

    def list(
        self,
        *,
        filter: Optional[dict] = None,
        plant=None,
        warehouse_no=None,
        storage_bin_no=None,
        bin_type=None,
        size: int = 20,
        all: bool = True,
    ) -> Page:
        params = dict(filter or {})
        if plant is not None:
            params["plant_id"] = plant  # plant flag → plant_id query
        if warehouse_no is not None:
            params["warehouse_no"] = warehouse_no
        if storage_bin_no is not None:
            params["storage_bin_no"] = storage_bin_no
        if bin_type is not None:
            params["bin_type"] = bin_type
        # 20+ flag 走 filter dict 透传 → 通用序列化所有 bool（不依赖白名单，全覆盖任意 bool flag）。
        _serialize_bool_params(params)
        return self._list(params, size, all)


class WarehouseEntity(PagedEntity):
    """wm.warehouse（仓库, warehouse-no）：标准 list + get 双方法（照 md.MaterialEntity）。

    bool flag（exclude_forbidden_in/exclude_forbidden_out/include_deleted/is_all_multi_org）
    透传 query 时序列化成字符串 'true'/'false'（_bool_flag）。plant flag → plant_id query。
    具名透传：plant/warehouse_no/description + 上述 bool flag；其余走 filter dict。

    端点（live parity 校正 2026-06-03，CLI src/commands/warehouse.ts 反查）：
      list = GET .../warehouse-nos（**裸数组、无信封、无 /page** —— CLI get(.../warehouse-nos) 再
             本地包 {items, total:len, has_next:false}）→ SDK 走 _list_bare（绕 normalize 吞空坑）。
      get  = GET .../warehouse-no/{id}（**单数 warehouse-no**）。
    """

    MOD = "wm"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/warehouse-nos"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/warehouse-no/{entity_id}"

    def list(
        self,
        *,
        filter: Optional[dict] = None,
        plant=None,
        warehouse_no=None,
        description=None,
        exclude_forbidden_in=None,
        exclude_forbidden_out=None,
        include_deleted=None,
        is_all_multi_org=None,
        size: int = 20,
        all: bool = True,
    ) -> Page:
        params = dict(filter or {})
        if plant is not None:
            params["plant_id"] = plant
        if warehouse_no is not None:
            params["warehouse_no"] = warehouse_no
        if description is not None:
            params["description"] = description
        for name, val in (
            ("exclude_forbidden_in", exclude_forbidden_in),
            ("exclude_forbidden_out", exclude_forbidden_out),
            ("include_deleted", include_deleted),
            ("is_all_multi_org", is_all_multi_org),
        ):
            if val is not None:
                params[name] = val
        # 通用序列化所有 bool（具名参 + filter dict 透传进来的同类 flag，不依赖白名单）。
        _serialize_bool_params(params)
        # 裸数组端点（warehouse-nos 一次返全量、无 Spring 信封）→ _list_bare（绕 normalize/get_json 吞空）。
        return self._list_bare(params, size, all)

    def get(self, entity_id: str) -> dict:
        return self._get(entity_id)


class UnitEntity(PagedEntity):
    """wm.unit（库存单元/序列号 SN）：标准 list + get 双方法。

    ⚠️ 命名歧义：这是**库存单元/SN**（按 sn/mo_id/bin_id 索引的实物单元），**不是** md/mm 的
    计量单位（unit-of-measure）——勿混淆。fuzzy 是 bool（true=模糊匹配 sn），透传字符串
    'true'/'false'（_bool_flag）。具名透传：sn/fuzzy/status/material_no/bin_id/mo_id。

    TODO: live wm __schema 复核端点单复数/filter_keys（暂照 /units/page + /{id} 写）。
    """

    MOD = "wm"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/units/page"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/units/{entity_id}"

    def list(
        self,
        *,
        filter: Optional[dict] = None,
        sn=None,
        fuzzy=None,
        status=None,
        material_no=None,
        bin_id=None,
        mo_id=None,
        size: int = 20,
        all: bool = True,
    ) -> Page:
        params = dict(filter or {})
        if sn is not None:
            params["sn"] = sn
        if fuzzy is not None:
            params["fuzzy"] = fuzzy
        if status is not None:
            params["status"] = status
        if material_no is not None:
            params["material_no"] = material_no
        if bin_id is not None:
            params["bin_id"] = bin_id
        if mo_id is not None:
            params["mo_id"] = mo_id
        # 通用序列化所有 bool（fuzzy 具名 + filter dict 透传进来的任意 bool flag）。
        _serialize_bool_params(params)
        return self._list(params, size, all)

    def get(self, entity_id: str) -> dict:
        return self._get(entity_id)


class RequisitionEntity(PagedEntity):
    """wm.requisition（领料申请）：标准 list + get 双方法（照 md.MaterialEntity）。

    flag 多但都是简单透传：plant→plant_id / tr_no / mo_no / order_type / warehouse_id /
    status / finish_status（多选逗号）/ plan_start_date / plan_end_date / open_indicator。
    时间 filter（plan_start_date/plan_end_date）schema 仅标 ISO，按 wm 多数单据偏 datetime
    透传不强转——**TODO live 抓 CLI 确认 date vs datetime**（§6 行 379）。

    TODO: live wm __schema 复核端点单复数/filter_keys + plan_*_date 形态（暂照 /requisitions/page 写）。
    """

    MOD = "wm"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/requisitions/page"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/requisitions/{entity_id}"

    def list(
        self,
        *,
        filter: Optional[dict] = None,
        plant=None,
        tr_no=None,
        mo_no=None,
        order_type=None,
        warehouse_id=None,
        status=None,
        finish_status=None,
        plan_start_date=None,
        plan_end_date=None,
        size: int = 20,
        all: bool = True,
    ) -> Page:
        params = dict(filter or {})
        if plant is not None:
            params["plant_id"] = plant
        for name, val in (
            ("tr_no", tr_no),
            ("mo_no", mo_no),
            ("order_type", order_type),
            ("warehouse_id", warehouse_id),
            ("status", status),
            ("finish_status", finish_status),  # 多选逗号 → 透传给后端
            ("plan_start_date", plan_start_date),
            ("plan_end_date", plan_end_date),
        ):
            if val is not None:
                params[name] = val
        return self._list(params, size, all)

    def get(self, entity_id: str) -> dict:
        return self._get(entity_id)


# ---------- 批 B · custom-verbs 10（方法名贴 verb，绝不硬塞 get）----------


class MaterialDocEntity(PagedEntity):
    """wm.material_doc（物料凭证）：list + get；items 子命令 schema 标 DEPRECATED → **不实现**。

    Spring Slice 形态：后端**不返 total**（total=null），计数走 items.length、分页靠 has_next
    ——base._list 已正确处理（total 不可信置 None + iterate_all 靠 has_next/truncated），
    **绝不**自己用 .total 判分页（wm-cli 0.1.6 二修过的坑）。
    时间 filter 是 **ISO datetime**（doc_at_start/doc_at_end/posting_at_start/posting_at_end
    值形如 YYYY-MM-DDTHH:mm:ss）——与 inventory_check_task/check_order 的 ISO date 不同，是
    entity 内坑，SDK 只透传不强转。plant flag → plant_id query。
    只读边界 + 不延续废弃面：**无 items 方法**（DEPRECATED 不暴露）。

    端点（live parity 校正 2026-06-03，CLI src/commands/material-doc.ts 反查）：
      list = GET .../material-docs（**裸 base，无 /page 后缀** —— CLI 用 getPage(base5) 直打 base）；
      get  = GET .../material-docs/{id}。
    """

    MOD = "wm"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/material-docs"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/material-docs/{entity_id}"

    def list(
        self,
        *,
        filter: Optional[dict] = None,
        plant=None,
        doc_no=None,
        cancel=None,
        request_by=None,
        doc_at_start=None,        # ISO datetime
        doc_at_end=None,          # ISO datetime
        posting_at_start=None,    # ISO datetime
        posting_at_end=None,      # ISO datetime
        ref_no=None,
        size: int = 20,
        all: bool = True,
    ) -> Page:
        params = dict(filter or {})
        if plant is not None:
            params["plant_id"] = plant
        for name, val in (
            ("doc_no", doc_no),
            ("cancel", cancel),
            ("request_by", request_by),
            ("doc_at_start", doc_at_start),
            ("doc_at_end", doc_at_end),
            ("posting_at_start", posting_at_start),
            ("posting_at_end", posting_at_end),
            ("ref_no", ref_no),
        ):
            if val is not None:
                params[name] = val
        return self._list(params, size, all)

    def get(self, entity_id: str) -> dict:
        return self._get(entity_id)
    # 注意：material_doc.items schema 标 DEPRECATED → 不实现（只读边界 + 不延续废弃面）。


class TransOrderEntity(PagedEntity):
    """wm.trans_order（调拨单）：list / get + **跨单 items（无 id）**。

    三 verb：
    - list（单据头，Spring Slice total=null，走 has_next 不用 .total）
    - get（单条）
    - **items（无 id = 跨单行项独立查询）**：收**自己的** filter（material_id/lot_name/bin_no/
      supplier_id/po_id/mo_id 等），独立分页端点 .../trans-order-items/page，**不是** get(id)
      的明细行——与 warehouse_request.items(id) 单据明细语义相反，签名不收 entity_id。
    时间 filter（start_transfer_date/end_transfer_date）是 **ISO datetime**。
    move_type_code 多选逗号 → 直接透传给后端（SDK 不本地拆分）。

    items 复用 base._sub_list（不重写 iterate_all）。

    端点（live parity 校正 2026-06-03，CLI src/commands/trans-order.ts 反查）：
      list  = GET .../tos/page（**base 段是 /tos 不是 /trans-orders** —— CLI base12 = .../tos）；
      get   = GET .../tos/{id}；
      items = GET .../tos-items/page（**跨单行项，base12 兄弟段 tos-items**，非 /trans-order-items）。
    """

    MOD = "wm"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/tos/page"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/tos/{entity_id}"

    def list(
        self,
        *,
        filter: Optional[dict] = None,
        plant=None,
        to_no=None,
        source_warehouse_no=None,
        destination_warehouse_no=None,
        move_type_code=None,        # 多选逗号，透传
        contract_id=None,
        so_id=None,
        start_transfer_date=None,   # ISO datetime
        end_transfer_date=None,     # ISO datetime
        size: int = 20,
        all: bool = True,
    ) -> Page:
        params = dict(filter or {})
        if plant is not None:
            params["plant_id"] = plant
        for name, val in (
            ("to_no", to_no),
            ("source_warehouse_no", source_warehouse_no),
            ("destination_warehouse_no", destination_warehouse_no),
            ("move_type_code", move_type_code),
            ("contract_id", contract_id),
            ("so_id", so_id),
            ("start_transfer_date", start_transfer_date),
            ("end_transfer_date", end_transfer_date),
        ):
            if val is not None:
                params[name] = val
        return self._list(params, size, all)

    def get(self, entity_id: str) -> dict:
        return self._get(entity_id)

    def items(
        self,
        *,
        filter: Optional[dict] = None,
        material_id=None,
        lot_name=None,
        bin_no=None,
        supplier_id=None,
        po_id=None,
        mo_id=None,
        size: int = 20,
        all: bool = True,
    ) -> Page:
        """跨单行项查询（**无 id**）：独立分页端点，收自己的 filter（非 get(id) 的明细行）。

        复用 base._sub_list 翻页（Spring Slice total=null → has_next/truncated）。
        """
        params = dict(filter or {})
        for name, val in (
            ("material_id", material_id),
            ("lot_name", lot_name),
            ("bin_no", bin_no),
            ("supplier_id", supplier_id),
            ("po_id", po_id),
            ("mo_id", mo_id),
        ):
            if val is not None:
                params[name] = val
        path = f"/v2/api/tenants/{self._tenant_id()}/tos-items/page"
        return self._sub_list(path, params=params, size=size, all_pages=all)


class WarehouseRequestEntity(PagedEntity):
    """wm.warehouse_request（出入库申请）：list / get + **items(id) = 单据明细**。

    items 是 **items(id)** 形态（收 entity_id，端点 .../<id>/items/page）——与 trans_order
    的跨单 items（无 id）相反：这里 items(id) 取**该申请的**行项明细。
    status/finish_status 多选逗号分隔 → 透传。无 datetime filter，较简单。
    move_direction 取 in/out。

    items 复用 base._sub_list（不重写 iterate_all）。

    TODO: live wm __schema 复核端点单复数 + items 子路径（暂照 /warehouse-requests/page +
      /{id} + /<id>/items/page 写）。
    """

    MOD = "wm"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/warehouse-requests/page"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/warehouse-requests/{entity_id}"

    def list(
        self,
        *,
        filter: Optional[dict] = None,
        warehouse_no=None,
        move_direction=None,        # in/out
        ref_order_name=None,
        ref_order_no=None,
        business_partner=None,
        so_id=None,
        contract_id=None,
        warehouse_request_no=None,
        contains_manual=None,
        status=None,                # 多选逗号
        finish_status=None,         # 多选逗号
        size: int = 20,
        all: bool = True,
    ) -> Page:
        params = dict(filter or {})
        for name, val in (
            ("warehouse_no", warehouse_no),
            ("move_direction", move_direction),
            ("ref_order_name", ref_order_name),
            ("ref_order_no", ref_order_no),
            ("business_partner", business_partner),
            ("so_id", so_id),
            ("contract_id", contract_id),
            ("warehouse_request_no", warehouse_request_no),
            ("status", status),
            ("finish_status", finish_status),
        ):
            if val is not None:
                params[name] = val
        if contains_manual is not None:
            params["contains_manual"] = _bool_flag(contains_manual)
        return self._list(params, size, all)

    def get(self, entity_id: str) -> dict:
        return self._get(entity_id)

    def items(self, entity_id: str, *, material_no=None, size: int = 20, all: bool = True) -> Page:
        """items(id) = 该申请的行项明细（端点 .../<id>/items/page），复用 base._sub_list。"""
        params: dict = {}
        if material_no is not None:
            params["material_no"] = material_no
        path = f"/v2/api/tenants/{self._tenant_id()}/warehouse-requests/{entity_id}/items/page"
        return self._sub_list(path, params=params, size=size, all_pages=all)


class InventoryCheckTaskEntity(PagedEntity):
    """wm.inventory_check_task（盘点任务）：list / get(include_items/is_blind_pda) + items(id, diffOnly)。

    时间 filter（create_date_from/create_date_to/plan_finish_date_from/to/release_date_from/to）
    是 **ISO date**（YYYY-MM-DD）——与同模块 material_doc/trans_order 的 datetime 不同，entity
    内坑，SDK 只透传不强转。status 多选逗号。

    **单点 camelCase 坑**：items 的 Python 入参是 snake `include_diff_only`，但透传的 query key
    是驼峰 **`diffOnly`**（不是 diff_only / include_diff_only）——序列化时保持驼峰。
    get 支持 include_items（详情时一并返 items，get 级而非 list 级）+ is_blind_pda（盲盘模式），
    两者均为可选 query，bool 透传 'true'/'false'。

    items 复用 base._sub_list（不重写 iterate_all）。

    TODO: live wm __schema 复核端点单复数 + items 子路径 + diffOnly key（暂照
      /inventory-check-tasks/page + /{id} + /<id>/items/page 写）。
    """

    MOD = "wm"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/inventory-check-tasks/page"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/inventory-check-tasks/{entity_id}"

    def list(
        self,
        *,
        filter: Optional[dict] = None,
        task_name=None,
        task_no=None,
        warehouse_id=None,
        status=None,                # 多选逗号
        create_date_from=None,      # ISO date
        create_date_to=None,        # ISO date
        size: int = 20,
        all: bool = True,
    ) -> Page:
        params = dict(filter or {})
        for name, val in (
            ("task_name", task_name),
            ("task_no", task_no),
            ("warehouse_id", warehouse_id),
            ("status", status),
            ("create_date_from", create_date_from),
            ("create_date_to", create_date_to),
        ):
            if val is not None:
                params[name] = val
        return self._list(params, size, all)

    def get(self, entity_id: str, *, include_items=None, is_blind_pda=None) -> dict:
        """get(id)，可选 include_items（详情一并返 items）+ is_blind_pda（盲盘模式），bool 透传字符串。"""
        params: dict = {}
        if include_items is not None:
            params["include_items"] = _bool_flag(include_items)
        if is_blind_pda is not None:
            params["is_blind_pda"] = _bool_flag(is_blind_pda)
        url = self._base() + self._get_path(self._tenant_id(), entity_id)
        return self._http.get_json(url, params=params or None)

    def items(self, entity_id: str, *, include_diff_only=None, size: int = 20, all: bool = True) -> Page:
        """items(id) 明细行，复用 base._sub_list。

        ⚠️ camelCase 坑：Python 入参 `include_diff_only`（snake）→ query key **`diffOnly`**（驼峰），
        bool 透传 'true'/'false'。
        """
        params: dict = {}
        if include_diff_only is not None:
            params["diffOnly"] = _bool_flag(include_diff_only)  # snake 入参 → camelCase query key
        path = f"/v2/api/tenants/{self._tenant_id()}/inventory-check-tasks/{entity_id}/items/page"
        return self._sub_list(path, params=params, size=size, all_pages=all)


class MoEntity(PagedEntity):
    """wm.mo（工单**只读视图**）：list + **info(mo_no) / kitting_items(mo_no)**（按 mo_no 非 id）。

    ⚠️ 命名歧义：这是 wm 侧的工单**只读视图**，**不是** pp 模块的 mo 写接口——只读边界内。
    verb 非标准：
    - info(mo_no)：按 **mo_no**（业务号，非 internal id）取详情，端点 .../mo/{mo_no}/info ——
      方法名贴 verb 用 info()，**不**硬塞成 get()。
    - kitting_items(mo_no)：配套齐套行项，按 mo_no 索引，复用 base._sub_list。
    时间 filter（pp_plan_prod_start/end_date / pp_plan_stock_start/end_date）是 ISO datetime
    （pp 计划字段下沉到 wm 视图）。plant flag → plant_id query。

    端点（live parity 校正 2026-06-03，CLI src/commands/mo.ts 反查）：
      list          = GET .../in-mos/page（**段是 /in-mos 不是 /mos**）；
      info(mo_no)   = GET .../in-mos/moInfo?mo_no=<no>（**mo_no 走 query 非 path**，camelCase moInfo）；
      kitting_items = GET .../mo-kitting-items/page?mo_no=<no>（**兄弟段 mo-kitting-items + mo_no query**，
                      非 /mos/{mo_no}/kitting-items）。
    """

    MOD = "wm"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/in-mos/page"

    def list(
        self,
        *,
        filter: Optional[dict] = None,
        plant=None,
        mo_no=None,
        mo_type=None,
        work_center_name=None,
        product_code=None,
        only_finished=None,
        pp_plan_prod_start_date=None,   # ISO datetime
        pp_plan_prod_end_date=None,     # ISO datetime
        size: int = 20,
        all: bool = True,
    ) -> Page:
        params = dict(filter or {})
        if plant is not None:
            params["plant_id"] = plant
        for name, val in (
            ("mo_no", mo_no),
            ("mo_type", mo_type),
            ("work_center_name", work_center_name),
            ("product_code", product_code),
            ("pp_plan_prod_start_date", pp_plan_prod_start_date),
            ("pp_plan_prod_end_date", pp_plan_prod_end_date),
        ):
            if val is not None:
                params[name] = val
        if only_finished is not None:
            params["only_finished"] = _bool_flag(only_finished)
        return self._list(params, size, all)

    def info(self, mo_no: str, *, plant=None) -> dict:
        """按 **mo_no**（非 id）取工单详情。CLI 校正：端点 .../in-mos/moInfo、**mo_no 走 query 非 path**，
        可选 plant→plant_id query。方法名贴 verb（非 get）。"""
        params: dict = {"mo_no": mo_no}
        if plant is not None:
            params["plant_id"] = plant
        url = self._base() + f"/v2/api/tenants/{self._tenant_id()}/in-mos/moInfo"
        return self._http.get_json(url, params=params)

    def kitting_items(self, mo_no: str, *, size: int = 20, all: bool = True) -> Page:
        """按 mo_no 取配套齐套行项。CLI 校正：端点 .../mo-kitting-items/page、**mo_no 走 query**，
        复用 base._sub_list。"""
        path = f"/v2/api/tenants/{self._tenant_id()}/mo-kitting-items/page"
        return self._sub_list(path, params={"mo_no": mo_no}, size=size, all_pages=all)


class AssemblyOrderEntity(PostPagedEntity):
    """wm.assembly_order（装配/拆解单, 双实体合一）：4 verb = 装配 list/get + 拆解 disassembly_list/get。

    两套端点合一个 entity：
    - 装配单：list / get → .../assembly-orders[/page | /{id}]
    - 拆解单：disassembly_list / disassembly_get → .../disassembly-orders[/page | /{id}]
    schema 无具名业务 filter flag（只有通用 --filter）→ 两个 list 收 filter dict 透传即可，最薄。

    端点（live parity 校正 2026-06-03，CLI src/commands/assembly-order.ts 反查）：
      list/disassembly_list = **POST** .../assembly-orders/page · .../disassembly-orders/page（filter 进
        body、page/size 进 query —— CLI 用 postPage；旧版 SDK 走 GET 触发 **500**，故继承 PostPagedEntity
        + disassembly 直接 http.post_page）；
      get/disassembly_get   = GET .../assembly-orders/{id} · .../disassembly-orders/{id}。
    """

    MOD = "wm"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/assembly-orders/page"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/assembly-orders/{entity_id}"

    def list(self, *, filter: Optional[dict] = None, size: int = 20, all: bool = True) -> Page:
        # PostPagedEntity._list：filter 进 body、page/size 进 query（CLI postPage 校正）。
        return self._list(dict(filter or {}), size, all)

    def get(self, entity_id: str) -> dict:
        return self._get(entity_id)

    def disassembly_list(self, *, filter: Optional[dict] = None, size: int = 20, all: bool = True) -> Page:
        """拆解单 list（独立端点 POST /disassembly-orders/page，filter 进 body、page/size 进 query）。"""
        url = self._base() + f"/v2/api/tenants/{self._tenant_id()}/disassembly-orders/page"
        body = dict(filter or {})

        def fetch(page_no: int) -> Page:
            return self._http.post_page(
                url, body=body, params={"page": str(page_no), "size": str(size)}, requested_size=size
            )

        if not all:
            return fetch(0)
        agg = iterate_all(fetch)
        return Page(items=agg.items, page=None, total=None, has_next=agg.truncated, truncated=agg.truncated)

    def disassembly_get(self, entity_id: str) -> dict:
        """拆解单 get（独立端点 /disassembly-orders/{id}）。"""
        url = self._base() + f"/v2/api/tenants/{self._tenant_id()}/disassembly-orders/{entity_id}"
        return self._http.get_json(url)


class CheckOrderEntity(PagedEntity):
    """wm.check_order（检验单, wm 侧**只读视图**）：list / get + details(id) / pending()。

    ⚠️ 命名歧义：这是 **wm 侧只读视图**，与 **qm 模块**的检验单区分——勿调错模块。
    4 verb：
    - list / get（标准）
    - details(id)：某检验单的明细行（单据明细，端点 .../<id>/details/page），复用 base._sub_list。
    - pending()：待检列表（**独立分页查询**，端点 .../check-orders/pending，非某单明细），
      复用 base._sub_list、收自己的 filter。
    时间 filter（check_at_start/check_at_end）是 **ISO date**（YYYY-MM-DD）——与 material_doc
    的 datetime 区分，entity 内坑。order_type/status 多选逗号。

    details/pending 复用 base._sub_list（不重写 iterate_all）。

    端点（live parity 校正 2026-06-03，CLI src/commands/check-order.ts 反查）：
      list    = GET .../check-order/page（**单数 check-order** —— 旧 /check-orders 复数 404）；
      get     = GET .../check-order/{id}；
      details = GET .../check-order/detail/page（**flat 过滤列表、无 id**，单数 detail —— CLI 的
                details 收 filter 非 id，与旧 /<id>/details/page 的「某单明细」语义不同，照 CLI 校正）；
      pending = GET .../check-order/pending_check_order/page（snake 段 pending_check_order）。
    """

    MOD = "wm"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/check-order/page"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/check-order/{entity_id}"

    def list(
        self,
        *,
        filter: Optional[dict] = None,
        supplier_id=None,
        check_order_no=None,
        order_type=None,            # 多选逗号
        purchase_type=None,
        po_id=None,
        po_no=None,
        material_id=None,
        status=None,                # 多选逗号
        check_at_start=None,        # ISO date
        check_at_end=None,          # ISO date
        size: int = 20,
        all: bool = True,
    ) -> Page:
        params = dict(filter or {})
        for name, val in (
            ("supplier_id", supplier_id),
            ("check_order_no", check_order_no),
            ("order_type", order_type),
            ("purchase_type", purchase_type),
            ("po_id", po_id),
            ("po_no", po_no),
            ("material_id", material_id),
            ("status", status),
            ("check_at_start", check_at_start),
            ("check_at_end", check_at_end),
        ):
            if val is not None:
                params[name] = val
        return self._list(params, size, all)

    def get(self, entity_id: str) -> dict:
        return self._get(entity_id)

    def details(self, *, filter: Optional[dict] = None, size: int = 20, all: bool = True) -> Page:
        """details = flat 检验单明细列表（CLI 校正：端点 .../check-order/detail/page、收 filter 非 id），
        复用 base._sub_list。⚠️ 与旧设想的 details(id) 不同——CLI 的 detail 是跨单过滤列表无 id。"""
        path = f"/v2/api/tenants/{self._tenant_id()}/check-order/detail/page"
        return self._sub_list(path, params=dict(filter or {}), size=size, all_pages=all)

    def pending(self, *, filter: Optional[dict] = None, size: int = 20, all: bool = True) -> Page:
        """pending() = 待检列表（独立分页查询，端点 .../check-order/pending_check_order/page），
        复用 base._sub_list。"""
        path = f"/v2/api/tenants/{self._tenant_id()}/check-order/pending_check_order/page"
        return self._sub_list(path, params=dict(filter or {}), size=size, all_pages=all)


class SalesOrderShipmentEntity(PagedEntity):
    """wm.sales_order_shipment（销售发运单, **主单据**）：list / get + lines(id)。

    ⚠️ 命名歧义：wm 另有 delivery_order 也叫「销售发运单」（summary 旁路 lookup）——两者**不同**：
    本 entity 是**主单据**（标准 list/get + lines 明细行），delivery_order 是 summary 旁路。
    时间 filter（start_date/end_date）是 **ISO date**（YYYY-MM-DD）——与同模块单据的 datetime
    不同，entity 内坑。status/finish_status 多选逗号；column_a..e 自定义字段走 filter dict 透传。
    plant flag → plant_id query。

    lines 复用 base._sub_list（不重写 iterate_all）。

    TODO: live wm __schema 复核端点单复数 + lines 子路径（暂照 /sales-order-shipments/page +
      /{id} + /<id>/lines/page 写）。
    """

    MOD = "wm"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/sales-order-shipments/page"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/sales-order-shipments/{entity_id}"

    def list(
        self,
        *,
        filter: Optional[dict] = None,
        plant=None,
        shipment_no=None,
        so_id=None,
        contract_id=None,
        account_id=None,
        shipment_type=None,
        status=None,                # 多选逗号
        finish_status=None,         # 多选逗号
        start_date=None,            # ISO date
        end_date=None,              # ISO date
        logistics_no=None,
        open_indicator=None,
        size: int = 20,
        all: bool = True,
    ) -> Page:
        params = dict(filter or {})
        if plant is not None:
            params["plant_id"] = plant
        for name, val in (
            ("shipment_no", shipment_no),
            ("so_id", so_id),
            ("contract_id", contract_id),
            ("account_id", account_id),
            ("shipment_type", shipment_type),
            ("status", status),
            ("finish_status", finish_status),
            ("start_date", start_date),
            ("end_date", end_date),
            ("logistics_no", logistics_no),
            ("open_indicator", open_indicator),
        ):
            if val is not None:
                params[name] = val
        return self._list(params, size, all)

    def get(self, entity_id: str) -> dict:
        return self._get(entity_id)

    def lines(self, entity_id: str, *, size: int = 20, all: bool = True) -> Page:
        """lines(id) = 发运单行项（单据明细，端点 .../<id>/lines/page），复用 base._sub_list。"""
        path = f"/v2/api/tenants/{self._tenant_id()}/sales-order-shipments/{entity_id}/lines/page"
        return self._sub_list(path, size=size, all_pages=all)


class DeliveryOrderEntity(PagedEntity):
    """wm.delivery_order（销售发运单 **summary 旁路 lookup**）：仅 summary(两参必填)。

    ⚠️ 命名歧义：与 sales_order_shipment 同名「销售发运单」但**不同**——本 entity 是 summary
    旁路 lookup（无 list/get/id 概念），sales_order_shipment 才是主单据。
    只有 summary 一个 verb，两个 filter **必填**（delivery_order_name + ref_order_id），缺任一
    → 本地 fail-loud（raise ValueError，**不发空网络请求**）。方法名用 summary() 贴 verb，不叫 list()。

    TODO: live wm __schema 复核 summary 端点形态（§6 行 440 自标非标端点抓 CLI 确认——暂照
      /delivery-orders/summary 带两参 query 写）。
    """

    MOD = "wm"

    def summary(
        self,
        *,
        delivery_order_name: str,
        ref_order_id: str,
        filter: Optional[dict] = None,
        size: int = 20,
        all: bool = True,
    ) -> Page:
        """summary 旁路 lookup：delivery_order_name + ref_order_id **两参必填**，缺则 fail-loud。"""
        missing = [
            name
            for name, val in (
                ("delivery_order_name", delivery_order_name),
                ("ref_order_id", ref_order_id),
            )
            if not val
        ]
        if missing:
            raise ValueError(
                f"wm.delivery_order.summary() 缺必填参数 {missing} —— "
                "delivery_order_name/ref_order_id 两参均必填（summary 旁路 lookup，不发空查询）。"
            )
        params = dict(filter or {})
        params["delivery_order_name"] = delivery_order_name
        params["ref_order_id"] = ref_order_id
        path = f"/v2/api/tenants/{self._tenant_id()}/delivery-orders/summary"
        return self._sub_list(path, params=params, size=size, all_pages=all)


class WmConfigEntity(PagedEntity):
    """wm.wm_config（WM 业务配置, 6 子 verb）：**全只读查策略**，绝不改策略。

    ⚠️ 边界：wm_config 是**业务配置**（规则/策略数据），**不是** CLI 连接 config——名字像配置
    写入，但 schema 全是读取（document_configs 等是**查**策略不是**改**策略）。只读边界内、无写。
    6 个独立端点各一个薄 list-like 方法（复用 base._sub_list）：
    - document_configs / document_lot_strategies / movement_lot_strategies
    - delivery_order_config / delivery_order_creation_config / movement_creation_config
    无具名 filter（各 verb 全量 / 通用 filter 透传）。

    TODO: live wm __schema 复核 6 个端点 path（§6 行 453 自标抓 CLI 确认 6 path——暂照
      /wm-config/<sub> 写）。
    """

    MOD = "wm"

    def _sub(self, leaf: str, size: int, all: bool) -> Page:
        path = f"/v2/api/tenants/{self._tenant_id()}/wm-config/{leaf}"
        return self._sub_list(path, size=size, all_pages=all)

    def document_configs(self, *, size: int = 20, all: bool = True) -> Page:
        return self._sub("document-configs", size, all)

    def document_lot_strategies(self, *, size: int = 20, all: bool = True) -> Page:
        return self._sub("document-lot-strategies", size, all)

    def movement_lot_strategies(self, *, size: int = 20, all: bool = True) -> Page:
        return self._sub("movement-lot-strategies", size, all)

    def delivery_order_config(self, *, size: int = 20, all: bool = True) -> Page:
        return self._sub("delivery-order-config", size, all)

    def delivery_order_creation_config(self, *, size: int = 20, all: bool = True) -> Page:
        return self._sub("delivery-order-creation-config", size, all)

    def movement_creation_config(self, *, size: int = 20, all: bool = True) -> Page:
        return self._sub("movement-creation-config", size, all)
