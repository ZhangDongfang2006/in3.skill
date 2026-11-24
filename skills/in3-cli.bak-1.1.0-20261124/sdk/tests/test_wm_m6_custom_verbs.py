"""#17 M6 批 B · wm custom-verbs 10 实体单测（直接实例化，FakeTransport，不经 facade）。

覆盖 material_doc / trans_order / warehouse_request / inventory_check_task / mo /
assembly_order / check_order / sales_order_shipment / delivery_order / wm_config。

逐 verb 钉死本片非标点：
- Spring Slice total=null：material_doc/trans_order list 返回 total=None，分页只走 has_next。
- 'items' 双语义：warehouse_request.items(id)/inventory_check_task.items(id) 是单据明细
  （.../<id>/items 形态、收 entity_id）；trans_order.items(...) 是跨单独立查询（收自己的
  material_id/lot_name/bin_no、独立端点、不收 id）——签名与端点不混。
- material_doc.items DEPRECATED → 断言无 items 方法。
- 非 id verb 方法名贴 verb：mo.info(mo_no)/mo.kitting_items(mo_no)、delivery_order.summary
  (两参必填)、assembly_order.disassembly_list/get、check_order.details(id)/pending()、
  sales_order_shipment.lines(id)——断言方法名存在且不被错塞成 get。
- inventory_check_task.items 的 snake 入参 include_diff_only → camelCase query key diffOnly。
- datetime vs date：透传不强转（测试传值即断言原样进 query）。
- delivery_order.summary 缺任一参数 → fail-loud ValueError（不打网络）。
- 只读边界：每实体断言 not hasattr create/update/delete。
- sub-list verb 复用 base._sub_list（断言走 GET get_page 路径 + 端点正确）。

桩照 tests/test_qm_verbs.py：FakeResponse / FakeTransport。
"""
from dataclasses import dataclass, field

import pytest

from in3_client.auth import Session
from in3_client.config import Credentials
from in3_client.envelope import Page
from in3_client.entities.wm import (
    AssemblyOrderEntity,
    CheckOrderEntity,
    DeliveryOrderEntity,
    InventoryCheckTaskEntity,
    MaterialDocEntity,
    MoEntity,
    SalesOrderShipmentEntity,
    TransOrderEntity,
    WarehouseRequestEntity,
    WmConfigEntity,
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
        self.calls.append({"method": method, "url": url, "params": params, "json": kw.get("json")})
        return self.responses.pop(0)


_CRED = Credentials(
    api_host="https://apiv3.industics.com/service",
    tenant_domain="indx",
    username="corp:zhuzheng@indx",
    encrypted_password="AESCIPHER==",
    alias="zhuzheng",
)
_TOKEN = {"access_token": "jwt", "tenant_id": "10030", "tenant_domain": "indx", "user_id": "u-42"}

_WM_BASE = "https://apiv3.industics.com/service/mom/wm"
_TENANT_PREFIX = _WM_BASE + "/v2/api/tenants/10030"

_WRITE_METHODS = ("create", "update", "delete", "post", "put", "remove", "save")


def _wire(entity_cls, data_responses, **kw):
    from in3_client.http import HttpClient

    sess = Session(_CRED, transport=FakeTransport([FakeResponse(200, _TOKEN)]))
    data_tr = FakeTransport(data_responses)
    http = HttpClient(sess, transport=data_tr)
    return entity_cls(_CRED, sess, http, **kw), data_tr


def _spring_page(items, last=True):
    return FakeResponse(200, {"content": items, "totalElements": len(items), "last": last})


def _slice_page(items, last=True):
    """Spring Slice 形态：**不返 total**（total 缺失 → normalize 给 None），靠 last/has_next。"""
    return FakeResponse(200, {"content": items, "last": last})


def _assert_read_only(ent):
    for m in _WRITE_METHODS:
        assert not hasattr(ent, m), f"只读边界破坏：{type(ent).__name__} 不该有 {m}"


# ========================================================
# material_doc：Spring Slice total=null + datetime + items DEPRECATED 不实现
# ========================================================

def test_material_doc_list_slice_total_is_none():
    ent, tr = _wire(MaterialDocEntity, [_slice_page([{"id": "md1"}], last=True)])
    page = ent.list(all=False)
    assert isinstance(page, Page)
    assert page.items == [{"id": "md1"}]
    # Spring Slice：total 不可信 → None（绝不回退 len）。
    assert page.total is None
    # live parity 校正：list 是裸 base /material-docs（无 /page 后缀，CLI getPage(base5) 直打 base）。
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/material-docs"
    _assert_read_only(ent)


def test_material_doc_list_all_pages_via_has_next_not_total():
    # 两页：第一页 last=False（has_next 真）→ 翻第二页 last=True 终止。全程不依赖 total。
    ent, tr = _wire(
        MaterialDocEntity,
        [_slice_page([{"id": "a"}], last=False), _slice_page([{"id": "b"}], last=True)],
    )
    page = ent.list(all=True)
    assert [r["id"] for r in page.items] == ["a", "b"]
    assert page.total is None
    assert len(tr.calls) == 2  # 翻了两页（靠 has_next，不靠 total）


def test_material_doc_datetime_filter_passthrough():
    ent, tr = _wire(MaterialDocEntity, [_slice_page([])])
    ent.list(plant="P01", doc_at_start="2026-01-01T00:00:00", posting_at_end="2026-02-01T23:59:59", all=False)
    p = tr.calls[0]["params"]
    assert p["plant_id"] == "P01"
    assert p["doc_at_start"] == "2026-01-01T00:00:00"   # ISO datetime 原样透传
    assert p["posting_at_end"] == "2026-02-01T23:59:59"


def test_material_doc_get_path_id():
    ent, tr = _wire(MaterialDocEntity, [FakeResponse(200, {"id": "md9"})])
    rec = ent.get("md9")
    assert rec["id"] == "md9"
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/material-docs/md9"


def test_material_doc_items_deprecated_not_implemented():
    ent, _ = _wire(MaterialDocEntity, [])
    # items 子命令 DEPRECATED → 不暴露（只读边界 + 不延续废弃面）。
    assert not hasattr(ent, "items")


# ========================================================
# trans_order：list/get + 跨单 items（无 id），Slice total=null，datetime
# ========================================================

def test_trans_order_list_slice_total_none_and_datetime():
    ent, tr = _wire(TransOrderEntity, [_slice_page([{"id": "to1"}])])
    page = ent.list(plant="P01", start_transfer_date="2026-01-01T08:00:00", all=False)
    assert page.total is None
    # live parity 校正：base 段是 /tos 不是 /trans-orders（CLI base12 = .../tos）。
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/tos/page"
    p = tr.calls[0]["params"]
    assert p["plant_id"] == "P01"
    assert p["start_transfer_date"] == "2026-01-01T08:00:00"  # ISO datetime
    _assert_read_only(ent)


def test_trans_order_get_path_id():
    ent, tr = _wire(TransOrderEntity, [FakeResponse(200, {"id": "to9"})])
    rec = ent.get("to9")
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/tos/to9"


def test_trans_order_items_is_cross_doc_query_no_id():
    # items 无 id = 跨单独立查询：收自己的 material_id/lot_name/bin_no，独立端点（不是 get(id) 明细）。
    ent, tr = _wire(TransOrderEntity, [_slice_page([{"id": "ti1"}])])
    page = ent.items(material_id="M-1", lot_name="LOT-9", bin_no="BIN-3", all=False)
    assert page.items == [{"id": "ti1"}]
    # 独立分页端点（跨单），非 .../<id>/items。live parity 校正：兄弟段是 /tos-items（非 /trans-order-items）。
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/tos-items/page"
    p = tr.calls[0]["params"]
    assert p["material_id"] == "M-1"
    assert p["lot_name"] == "LOT-9"
    assert p["bin_no"] == "BIN-3"


def test_trans_order_items_signature_takes_no_positional_id():
    # 与 warehouse_request.items(id) 签名相反：跨单 items 不收 entity_id（纯 keyword filter）。
    import inspect

    sig = inspect.signature(TransOrderEntity.items)
    params = list(sig.parameters.values())
    # 仅 self + keyword-only（无 entity_id 位置参）。
    positional = [p for p in params if p.name != "self" and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    assert positional == []


# ========================================================
# warehouse_request：list/get + items(id) 单据明细
# ========================================================

def test_warehouse_request_list_get():
    ent, tr = _wire(WarehouseRequestEntity, [_spring_page([{"id": "wr1"}])])
    page = ent.list(warehouse_no="WH1", move_direction="in", status="A,B", all=False)
    assert page.items == [{"id": "wr1"}]
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/warehouse-requests/page"
    p = tr.calls[0]["params"]
    assert p["move_direction"] == "in"
    assert p["status"] == "A,B"  # 多选逗号透传
    _assert_read_only(ent)


def test_warehouse_request_items_takes_id_and_subpath():
    # items(id) = 该申请的明细行（端点 .../<id>/items/page，收 entity_id）。
    ent, tr = _wire(WarehouseRequestEntity, [_spring_page([{"id": "it1"}])])
    page = ent.items("wr9", material_no="M-5", all=False)
    assert page.items == [{"id": "it1"}]
    assert tr.calls[0]["method"] == "GET"
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/warehouse-requests/wr9/items/page"
    assert tr.calls[0]["params"]["material_no"] == "M-5"


def test_warehouse_request_items_signature_takes_positional_id():
    import inspect

    sig = inspect.signature(WarehouseRequestEntity.items)
    first = [p.name for p in sig.parameters.values() if p.name != "self"][0]
    assert first == "entity_id"  # 与 trans_order.items 跨单（无 id）相反


# ========================================================
# inventory_check_task：list/get(include_items)/items(id, diffOnly camelCase), date filter
# ========================================================

def test_inventory_check_task_list_date_filter():
    ent, tr = _wire(InventoryCheckTaskEntity, [_spring_page([{"id": "ict1"}])])
    ent.list(task_no="T-1", status="A,B", create_date_from="2026-01-01", all=False)
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/inventory-check-tasks/page"
    p = tr.calls[0]["params"]
    assert p["create_date_from"] == "2026-01-01"  # ISO date（非 datetime）
    assert p["status"] == "A,B"


def test_inventory_check_task_get_include_items_bool():
    ent, tr = _wire(InventoryCheckTaskEntity, [FakeResponse(200, {"id": "ict9"})])
    rec = ent.get("ict9", include_items=True, is_blind_pda=False)
    assert rec["id"] == "ict9"
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/inventory-check-tasks/ict9"
    p = tr.calls[0]["params"]
    assert p["include_items"] == "true"   # bool → 字符串
    assert p["is_blind_pda"] == "false"


def test_inventory_check_task_items_diffonly_camelcase():
    # snake 入参 include_diff_only → camelCase query key diffOnly（单点 camelCase 坑）。
    ent, tr = _wire(InventoryCheckTaskEntity, [_spring_page([{"id": "d1"}])])
    page = ent.items("ict9", include_diff_only=True, all=False)
    assert page.items == [{"id": "d1"}]
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/inventory-check-tasks/ict9/items/page"
    p = tr.calls[0]["params"]
    assert "diffOnly" in p              # camelCase query key
    assert p["diffOnly"] == "true"
    assert "diff_only" not in p
    assert "include_diff_only" not in p


# ========================================================
# mo：工单只读视图，list + info(mo_no) + kitting_items(mo_no)（按 mo_no 非 id）
# ========================================================

def test_mo_list_datetime_filter():
    ent, tr = _wire(MoEntity, [_spring_page([{"id": "mo1"}])])
    ent.list(plant="P01", mo_no="MO-1", only_finished=True, pp_plan_prod_start_date="2026-01-01T00:00:00", all=False)
    # live parity 校正：段是 /in-mos 不是 /mos（CLI base6 + /in-mos/page）。
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/in-mos/page"
    p = tr.calls[0]["params"]
    assert p["plant_id"] == "P01"
    assert p["only_finished"] == "true"
    assert p["pp_plan_prod_start_date"] == "2026-01-01T00:00:00"  # ISO datetime
    _assert_read_only(ent)


def test_mo_info_by_mo_no_not_get():
    ent, tr = _wire(MoEntity, [FakeResponse(200, {"mo_no": "MO-9"})])
    rec = ent.info("MO-9")
    assert rec["mo_no"] == "MO-9"
    # live parity 校正：端点 .../in-mos/moInfo，mo_no 走 query（非 path）。
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/in-mos/moInfo"
    assert tr.calls[0]["params"]["mo_no"] == "MO-9"
    # 方法名贴 verb：有 info/kitting_items，无 get（不硬塞 get(id)）。
    assert hasattr(ent, "info")
    assert hasattr(ent, "kitting_items")
    assert not hasattr(ent, "get")


def test_mo_kitting_items_by_mo_no():
    ent, tr = _wire(MoEntity, [_spring_page([{"id": "k1"}])])
    page = ent.kitting_items("MO-9", all=False)
    assert page.items == [{"id": "k1"}]
    # live parity 校正：端点 .../mo-kitting-items/page，mo_no 走 query（非 /mos/{mo_no}/kitting-items）。
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/mo-kitting-items/page"
    assert tr.calls[0]["params"]["mo_no"] == "MO-9"


# ========================================================
# assembly_order：装配 list/get + 拆解 disassembly_list/disassembly_get（双套）
# ========================================================

def test_assembly_order_assembly_list_get():
    ent, tr = _wire(AssemblyOrderEntity, [_spring_page([{"id": "ao1"}])])
    page = ent.list(all=False)
    assert page.items == [{"id": "ao1"}]
    # live parity 校正：list 是 **POST**（CLI postPage；旧 GET 触发 500）。
    assert tr.calls[0]["method"] == "POST"
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/assembly-orders/page"
    _assert_read_only(ent)


def test_assembly_order_get_path_id():
    ent, tr = _wire(AssemblyOrderEntity, [FakeResponse(200, {"id": "ao9"})])
    rec = ent.get("ao9")
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/assembly-orders/ao9"


def test_assembly_order_disassembly_list_separate_endpoint():
    ent, tr = _wire(AssemblyOrderEntity, [_spring_page([{"id": "do1"}])])
    page = ent.disassembly_list(all=False)
    assert page.items == [{"id": "do1"}]
    # live parity 校正：disassembly_list 同为 **POST**（CLI postPage）。
    assert tr.calls[0]["method"] == "POST"
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/disassembly-orders/page"  # 独立端点
    # 双套方法名都在，贴 verb。
    assert hasattr(ent, "disassembly_list")
    assert hasattr(ent, "disassembly_get")


def test_assembly_order_disassembly_get_separate_endpoint():
    ent, tr = _wire(AssemblyOrderEntity, [FakeResponse(200, {"id": "do9"})])
    rec = ent.disassembly_get("do9")
    assert rec["id"] == "do9"
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/disassembly-orders/do9"


# ========================================================
# check_order：wm 侧只读视图，list/get + details(id) + pending(), date filter
# ========================================================

def test_check_order_list_date_filter():
    ent, tr = _wire(CheckOrderEntity, [_spring_page([{"id": "co1"}])])
    ent.list(check_order_no="CO-1", status="A,B", check_at_start="2026-01-01", all=False)
    # live parity 校正：单数 /check-order（旧复数 /check-orders 404）。
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/check-order/page"
    p = tr.calls[0]["params"]
    assert p["check_at_start"] == "2026-01-01"  # ISO date（非 datetime）
    assert p["status"] == "A,B"
    _assert_read_only(ent)


def test_check_order_details_is_flat_filter_list_no_id():
    # live parity 校正：CLI 的 details 是 flat 过滤列表（端点 .../check-order/detail/page、收 filter 非 id）。
    ent, tr = _wire(CheckOrderEntity, [_spring_page([{"id": "cd1"}])])
    page = ent.details(all=False)
    assert page.items == [{"id": "cd1"}]
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/check-order/detail/page"  # 单数 detail，无 id
    assert hasattr(ent, "details")
    assert hasattr(ent, "pending")
    # 签名校正：details 不再收位置 id（CLI detail 无 id），纯 keyword filter。
    import inspect
    positional = [
        p for p in inspect.signature(CheckOrderEntity.details).parameters.values()
        if p.name != "self" and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    assert positional == []


def test_check_order_pending_independent_query():
    ent, tr = _wire(CheckOrderEntity, [_spring_page([{"id": "cp1"}])])
    page = ent.pending(all=False)
    assert page.items == [{"id": "cp1"}]
    # live parity 校正：端点 .../check-order/pending_check_order/page（snake 段）。
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/check-order/pending_check_order/page"


# ========================================================
# sales_order_shipment：主单据 list/get + lines(id), date filter
# ========================================================

def test_sales_order_shipment_list_date_filter():
    ent, tr = _wire(SalesOrderShipmentEntity, [_spring_page([{"id": "sos1"}])])
    ent.list(plant="P01", shipment_no="SHP-1", status="A,B", start_date="2026-01-01", all=False)
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/sales-order-shipments/page"
    p = tr.calls[0]["params"]
    assert p["plant_id"] == "P01"
    assert p["start_date"] == "2026-01-01"  # ISO date（非 datetime）
    assert p["status"] == "A,B"
    _assert_read_only(ent)


def test_sales_order_shipment_get_path_id():
    ent, tr = _wire(SalesOrderShipmentEntity, [FakeResponse(200, {"id": "sos9"})])
    rec = ent.get("sos9")
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/sales-order-shipments/sos9"


def test_sales_order_shipment_lines_takes_id():
    ent, tr = _wire(SalesOrderShipmentEntity, [_spring_page([{"id": "l1"}])])
    page = ent.lines("sos9", all=False)
    assert page.items == [{"id": "l1"}]
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/sales-order-shipments/sos9/lines/page"
    assert hasattr(ent, "lines")
    assert not hasattr(ent, "summary")  # 与 delivery_order 区分：本主单据无 summary


# ========================================================
# delivery_order：summary 旁路 lookup，两参必填 fail-loud
# ========================================================

def test_delivery_order_summary_both_params():
    ent, tr = _wire(DeliveryOrderEntity, [_spring_page([{"id": "do1"}])])
    page = ent.summary(delivery_order_name="DO-1", ref_order_id="ref-9", all=False)
    assert page.items == [{"id": "do1"}]
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/delivery-orders/summary"
    p = tr.calls[0]["params"]
    assert p["delivery_order_name"] == "DO-1"
    assert p["ref_order_id"] == "ref-9"
    # summary 旁路 lookup：无 list/get/id；方法名 summary 贴 verb。
    assert hasattr(ent, "summary")
    assert not hasattr(ent, "list")
    assert not hasattr(ent, "get")
    _assert_read_only(ent)


def test_delivery_order_summary_missing_name_fail_loud_no_network():
    ent, tr = _wire(DeliveryOrderEntity, [])  # 无桩响应：若发网络会 IndexError pop，反证未发
    with pytest.raises(ValueError):
        ent.summary(delivery_order_name="", ref_order_id="ref-9")
    assert tr.calls == []  # 本地 fail-loud，不打网络


def test_delivery_order_summary_missing_ref_fail_loud_no_network():
    ent, tr = _wire(DeliveryOrderEntity, [])
    with pytest.raises(ValueError):
        ent.summary(delivery_order_name="DO-1", ref_order_id="")
    assert tr.calls == []


# ========================================================
# wm_config：6 子 verb 全只读查策略
# ========================================================

def test_wm_config_six_read_only_verbs_endpoints():
    cases = [
        ("document_configs", "document-configs"),
        ("document_lot_strategies", "document-lot-strategies"),
        ("movement_lot_strategies", "movement-lot-strategies"),
        ("delivery_order_config", "delivery-order-config"),
        ("delivery_order_creation_config", "delivery-order-creation-config"),
        ("movement_creation_config", "movement-creation-config"),
    ]
    for method_name, leaf in cases:
        ent, tr = _wire(WmConfigEntity, [_spring_page([{"k": leaf}])])
        page = getattr(ent, method_name)(all=False)
        assert page.items == [{"k": leaf}]
        assert tr.calls[0]["method"] == "GET"
        assert tr.calls[0]["url"] == _TENANT_PREFIX + f"/wm-config/{leaf}"


def test_wm_config_read_only_boundary():
    ent, _ = _wire(WmConfigEntity, [])
    # 名字像配置写入，但 schema 全是读取 → 无任何写方法。
    _assert_read_only(ent)
