"""#15 M4 qm 富自定义 verb 实体单测（直接实例化，不经 facade）。

覆盖 5 实体 × custom-verbs：
  rule_group     list / get / get_all / list_options
  check_sheet    list / list_items(POST 分页) / search_by_lot(4 必填) / get / get_by_no
  reject_order   list(8 multi-filter) / get(repair_code multi) / list_by_lot / list_nonqualified_types
  inspection_lot list / get / list_partials / check_and_next(?id= query-id)
  inspection_order list / get / list_by_lot / get_belong_info(2 bool) /
                   get_reject_order_id(?inspection_order_id= query-id, 跨实体) /
                   list_unqualified_items(POST 非分页) / list_basic_info

逐 verb 钉死非标点：
- query-id vs path-id（get 走 path、check_and_next/get_reject_order_id 走 ?id=）
- POST 分页 vs POST 非分页（check_sheet.list_items 用 post_page+iterate_all；
  inspection_order.list_unqualified_items 用 post_json 取 {items} 不 iterate）
- {items} 非分页 verb 用 _wrap_items 包 Page(page=None/total=None, has_next=False)
- reject_order 8 个 multi-filter 透传成 repeated query（list 值不 join 成逗号串）
- check_sheet get/get_by_no 同源（同一记录两路返同一对象）

桩照 tests/test_cr_bare_entities.py：FakeResponse / FakeTransport。
"""
from dataclasses import dataclass, field

import pytest

from in3_client.auth import Session
from in3_client.config import Credentials
from in3_client.envelope import Page
from in3_client.entities.qm import (
    CheckSheetEntity,
    InspectionLotEntity,
    InspectionOrderEntity,
    RejectOrderEntity,
    RuleGroupEntity,
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

_QM_BASE = "https://apiv3.industics.com/service/mom/qm"
_TENANT_PREFIX = _QM_BASE + "/v2/api/tenants/10030"


def _wire(entity_cls, data_responses, **kw):
    from in3_client.http import HttpClient

    sess = Session(_CRED, transport=FakeTransport([FakeResponse(200, _TOKEN)]))
    data_tr = FakeTransport(data_responses)
    http = HttpClient(sess, transport=data_tr)
    return entity_cls(_CRED, sess, http, **kw), data_tr


def _spring_page(items, last=True):
    return FakeResponse(200, {"content": items, "totalElements": len(items), "last": last})


# ========================================================
# rule_group：list / get / get_all / list_options
# ========================================================

def test_rule_group_list_paged_with_page_suffix():
    ent, tr = _wire(RuleGroupEntity, [_spring_page([{"id": "rg1"}])])
    page = ent.list()
    assert isinstance(page, Page)
    assert page.items == [{"id": "rg1"}]
    assert tr.calls[0]["method"] == "GET"
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/rule-groups/page"


def test_rule_group_get_path_id():
    ent, tr = _wire(RuleGroupEntity, [FakeResponse(200, {"id": "rg9", "group_name": "外观检"})])
    rec = ent.get("rg9")
    assert rec["id"] == "rg9"
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/rule-groups/rg9"
    assert tr.calls[0]["method"] == "GET"


def test_rule_group_get_all_wraps_items_and_repeated_query():
    # get-all 返 {items} 非分页；group_ids 透传成 repeated query（list 不 join）。
    ent, tr = _wire(RuleGroupEntity, [FakeResponse(200, {"items": [{"id": "a"}, {"id": "b"}]})])
    page = ent.get_all(["a", "b"])
    assert isinstance(page, Page)
    assert page.items == [{"id": "a"}, {"id": "b"}]
    # _wrap_items 形：has_next=False（一次全量）。
    assert page.has_next is False
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/rule-groups/get-all"
    # group_ids 仍是 list（doseq 展开 repeated query），绝不 join 成 "a,b"。
    assert tr.calls[0]["params"]["group_ids"] == ["a", "b"]


def test_rule_group_get_all_empty_fail_loud():
    # group_ids 空 → fail-loud，不发请求。
    ent, tr = _wire(RuleGroupEntity, [])
    with pytest.raises(ValueError):
        ent.get_all([])
    assert tr.calls == []


def test_rule_group_list_options_wraps_items():
    ent, tr = _wire(RuleGroupEntity, [FakeResponse(200, {"items": [{"code": "X"}]})])
    page = ent.list_options(check_type="INCOMING")
    assert page.items == [{"code": "X"}]
    assert page.has_next is False
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/rule-groups/options"
    assert tr.calls[0]["params"]["check_type"] == "INCOMING"


def test_rule_group_list_options_no_check_type():
    ent, tr = _wire(RuleGroupEntity, [FakeResponse(200, {"items": []})])
    page = ent.list_options()
    assert page.items == []
    # 不传 check_type 时 query 不含该键。
    assert "check_type" not in (tr.calls[0]["params"] or {})


# ========================================================
# check_sheet：list / list_items(POST 分页) / search_by_lot / get / get_by_no
# ========================================================

def test_check_sheet_list_paged():
    ent, tr = _wire(CheckSheetEntity, [_spring_page([{"id": "cs1"}])])
    page = ent.list()
    assert page.items == [{"id": "cs1"}]
    # 裸路径无 /page 后缀（对齐 CLI getPage：page/size 进 query）——parity live 校正。
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/check-sheets"
    assert tr.calls[0]["method"] == "GET"


def test_check_sheet_list_items_is_post_paged():
    # list-items 是 POST 分页：filter 进 body、page/size 进 query；post_page+iterate_all。
    ent, tr = _wire(CheckSheetEntity, [_spring_page([{"id": "i1"}], last=True)])
    page = ent.list_items(filter={"check_sheet_no": "CS-001"}, all=False)
    assert page.items == [{"id": "i1"}]
    call = tr.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == _TENANT_PREFIX + "/check-sheets/items"
    # filter 进 body。
    assert call["json"] == {"check_sheet_no": "CS-001"}
    # page/size 进 query（非 body）。
    assert call["params"]["page"] == "0"
    assert "size" in call["params"]


def test_check_sheet_search_by_lot_requires_4_args():
    ent, tr = _wire(CheckSheetEntity, [])
    with pytest.raises(ValueError):
        ent.search_by_lot(route_id="", route_step_id="rs", ref_no="r", lot_name="l")
    with pytest.raises(ValueError):
        ent.search_by_lot(route_id="rt", route_step_id=None, ref_no="r", lot_name="l")
    assert tr.calls == []


def test_check_sheet_search_by_lot_wraps_items():
    ent, tr = _wire(CheckSheetEntity, [FakeResponse(200, {"items": [{"id": "cs7"}]})])
    page = ent.search_by_lot(route_id="rt1", route_step_id="rs1", ref_no="REF9", lot_name="LOT9")
    assert isinstance(page, Page)
    assert page.items == [{"id": "cs7"}]
    assert page.has_next is False
    p = tr.calls[0]["params"]
    assert p["route_id"] == "rt1"
    assert p["route_step_id"] == "rs1"
    assert p["ref_no"] == "REF9"
    assert p["lot_name"] == "LOT9"


def test_check_sheet_get_path_id():
    ent, tr = _wire(CheckSheetEntity, [FakeResponse(200, {"id": "cs5", "check_sheet_no": "CS-5"})])
    rec = ent.get("cs5")
    assert rec["id"] == "cs5"
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/check-sheets/cs5"


def test_check_sheet_get_by_no_business_number():
    ent, tr = _wire(CheckSheetEntity, [FakeResponse(200, {"id": "cs5", "check_sheet_no": "CS-5"})])
    rec = ent.get_by_no("CS-5")
    assert rec["check_sheet_no"] == "CS-5"
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/check-sheets/by-no/CS-5"


def test_check_sheet_get_and_get_by_no_same_record_same_object():
    # #15 补的 AC：get(id) 与 get_by_no(no) 指向同一条检验单时返同一对象（逐字段 exact）。
    same = {"id": "cs5", "check_sheet_no": "CS-5", "status": "DONE", "delivered_by": "u9"}
    ent_id, _ = _wire(CheckSheetEntity, [FakeResponse(200, dict(same))])
    ent_no, _ = _wire(CheckSheetEntity, [FakeResponse(200, dict(same))])
    by_id = ent_id.get("cs5")
    by_no = ent_no.get_by_no("CS-5")
    assert by_id == by_no == same


# ========================================================
# reject_order：list(8 multi) / get(repair_code multi) / list_by_lot / list_nonqualified_types
# ========================================================

def test_reject_order_list_8_multi_filters_repeated_query_not_joined():
    ent, tr = _wire(RejectOrderEntity, [_spring_page([{"id": "ro1"}])])
    flt = {
        "statuses": ["A", "B"],
        "defect_codes": ["D1"],
        "source_codes": ["S1", "S2"],
        "supply_codes": ["SC1"],
        "nonqualified_type_codes": ["N1"],
        "area_ids": ["AR1", "AR2"],
        "line_ids": ["L1"],
        "approval_statuses": ["AP1"],
    }
    ent.list(filter=flt, all=False)
    params = tr.calls[0]["params"]
    # 每个 multi key 仍是 list（doseq → repeated query），绝不 join 成逗号串。
    for key, val in flt.items():
        assert params[key] == val
        assert not isinstance(params[key], str)


def test_reject_order_get_with_repair_code_multi():
    ent, tr = _wire(RejectOrderEntity, [FakeResponse(200, {"id": "ro9"})])
    rec = ent.get("ro9", repair_code=["RC1", "RC2"])
    assert rec["id"] == "ro9"
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/reject-orders/ro9"
    # repair_code 是 query scope（multi），非 path；list 透传。
    assert tr.calls[0]["params"]["repair_code"] == ["RC1", "RC2"]


def test_reject_order_get_without_repair_code():
    ent, tr = _wire(RejectOrderEntity, [FakeResponse(200, {"id": "ro9"})])
    ent.get("ro9")
    # 无 repair_code 时 query 不含该键。
    assert "repair_code" not in (tr.calls[0]["params"] or {})


def test_reject_order_list_by_lot_path_id_wraps_items():
    ent, tr = _wire(RejectOrderEntity, [FakeResponse(200, {"items": [{"id": "ro3"}]})])
    page = ent.list_by_lot("lot42")
    assert isinstance(page, Page)
    assert page.items == [{"id": "ro3"}]
    assert page.has_next is False
    # path-id（inspection_lot_id 进 path 段，非 query）。
    assert "lot42" in tr.calls[0]["url"]
    assert tr.calls[0]["method"] == "GET"


def test_reject_order_list_nonqualified_types_no_args_wraps_items():
    ent, tr = _wire(RejectOrderEntity, [FakeResponse(200, {"items": [{"code": "NQ1", "label": "划痕"}]})])
    page = ent.list_nonqualified_types()
    assert page.items == [{"code": "NQ1", "label": "划痕"}]
    assert page.has_next is False


# ========================================================
# inspection_lot：list / get / list_partials / check_and_next(?id=)
# ========================================================

def test_inspection_lot_list_dual_time_passthrough():
    # 双时间体系：date(start_delivery_date) 与 datetime(start_date) 并存，SDK 只透传不强转。
    ent, tr = _wire(InspectionLotEntity, [_spring_page([{"id": "il1"}])])
    flt = {
        "start_delivery_date": "2026-01-01",
        "end_delivery_date": "2026-01-31",
        "start_date": "2026-01-01T00:00:00",
        "end_date": "2026-01-31T23:59:59",
        "check_type_codes": ["CT1", "CT2"],
    }
    ent.list(filter=flt, all=False)
    p = tr.calls[0]["params"]
    assert p["start_delivery_date"] == "2026-01-01"
    assert p["start_date"] == "2026-01-01T00:00:00"
    # check_type_codes 是 multi（codes 复数）→ repeated query 不 join。
    assert p["check_type_codes"] == ["CT1", "CT2"]
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/inspection-lots/page"


def test_inspection_lot_get_path_id():
    ent, tr = _wire(InspectionLotEntity, [FakeResponse(200, {"id": "il5"})])
    ent.get("il5")
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/inspection-lots/il5"


def test_inspection_lot_list_partials_path_id_wraps_items():
    ent, tr = _wire(InspectionLotEntity, [FakeResponse(200, {"items": [{"id": "p1"}]})])
    page = ent.list_partials("il5")
    assert page.items == [{"id": "p1"}]
    assert page.has_next is False
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/inspection-lots/il5/partials"


def test_inspection_lot_check_and_next_query_id_not_path():
    # check-and-next 走 ?id= query（非 path）——与 get(id) 走 path 对照。
    ent, tr = _wire(InspectionLotEntity, [FakeResponse(200, {"instance_id": "next-1"})])
    rec = ent.check_and_next("il5")
    assert rec["instance_id"] == "next-1"
    # id 在 query，不在 path 段。
    assert tr.calls[0]["params"]["id"] == "il5"
    assert "/il5" not in tr.calls[0]["url"]
    # 端点段 camelCase checkAndNext（对齐 CLI 真路径）。
    assert tr.calls[0]["url"].endswith("/checkAndNext")


# ========================================================
# inspection_order：7 verb 最重
# ========================================================

def test_inspection_order_list_statuses_multi_and_qualified_bool():
    ent, tr = _wire(InspectionOrderEntity, [_spring_page([{"id": "io1"}])])
    ent.list(filter={"statuses": ["A", "B"], "qualified": "true"}, all=False)
    p = tr.calls[0]["params"]
    assert p["statuses"] == ["A", "B"]
    assert p["qualified"] == "true"
    # 裸路径无 /page 后缀（对齐 CLI getPage：page/size 进 query）——parity live 校正。
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/inspection-orders"


def test_inspection_order_get_path_id():
    ent, tr = _wire(InspectionOrderEntity, [FakeResponse(200, {"id": "io5"})])
    ent.get("io5")
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/inspection-orders/io5"


def test_inspection_order_list_by_lot_path_id_wraps_items():
    ent, tr = _wire(InspectionOrderEntity, [FakeResponse(200, {"items": [{"id": "io3"}]})])
    page = ent.list_by_lot("lot42")
    assert page.items == [{"id": "io3"}]
    assert page.has_next is False
    assert "lot42" in tr.calls[0]["url"]


def test_inspection_order_get_belong_info_two_bool_toggles():
    ent, tr = _wire(InspectionOrderEntity, [FakeResponse(200, {"project": {"id": "pj1"}})])
    ent.get_belong_info("io5", project=True, eqpt=True)
    call = tr.calls[0]
    assert "/io5/belong-info" in call["url"]
    # 两个独立 bool toggle，序列化为 'true'/'false'。
    assert call["params"]["project"] == "true"
    assert call["params"]["eqpt"] == "true"


def test_inspection_order_get_belong_info_default_false():
    ent, tr = _wire(InspectionOrderEntity, [FakeResponse(200, {})])
    ent.get_belong_info("io5")
    p = tr.calls[0]["params"]
    assert p["project"] == "false"
    assert p["eqpt"] == "false"


def test_inspection_order_get_reject_order_id_query_id_cross_entity():
    # get-reject-order-id：?inspection_order_id= query-id（非 path），返 RejectOrderDetailVO（跨实体）。
    reject_vo = {"reject_order_id": "ro-77", "reject_order_no": "RJ-77", "defect_code": "D9"}
    ent, tr = _wire(InspectionOrderEntity, [FakeResponse(200, reject_vo)])
    rec = ent.get_reject_order_id("io5")
    # 返回结构按 reject-order 形（含 reject_order_* 键），非 inspection-order。
    assert rec["reject_order_id"] == "ro-77"
    assert rec["reject_order_no"] == "RJ-77"
    # io_id 在 query（inspection_order_id），非 path。
    assert tr.calls[0]["params"]["inspection_order_id"] == "io5"
    assert "/io5" not in tr.calls[0]["url"]


def test_inspection_order_list_unqualified_items_post_non_paged():
    # list-unqualified-items 是 POST 非分页：post_json 取 {items}，不 iterate（无 page/size query）。
    ent, tr = _wire(InspectionOrderEntity, [FakeResponse(200, {"items": [{"id": "u1"}, {"id": "u2"}]})])
    page = ent.list_unqualified_items(filter={"inspection_order_no": "IO-9"})
    assert isinstance(page, Page)
    assert page.items == [{"id": "u1"}, {"id": "u2"}]
    assert page.has_next is False
    call = tr.calls[0]
    assert call["method"] == "POST"
    # filter 进 body。
    assert call["json"] == {"inspection_order_no": "IO-9"}
    # POST 非分页：query 不含 page/size（区别于 check_sheet.list_items 的 POST 分页）。
    assert "page" not in (call["params"] or {})
    assert "size" not in (call["params"] or {})


def test_inspection_order_list_basic_info_get_wraps_items():
    ent, tr = _wire(InspectionOrderEntity, [FakeResponse(200, {"items": [{"id": "b1"}]})])
    page = ent.list_basic_info(filter={"material_id": "m1"})
    assert page.items == [{"id": "b1"}]
    assert page.has_next is False
    assert tr.calls[0]["method"] == "GET"
    assert tr.calls[0]["params"]["material_id"] == "m1"


# ========================================================
# 只读边界守护：5 实体均无 create/update/delete
# ========================================================

@pytest.mark.parametrize("cls", [
    RuleGroupEntity, CheckSheetEntity, RejectOrderEntity, InspectionLotEntity, InspectionOrderEntity,
])
def test_qm_entities_no_write_methods(cls):
    ent, _ = _wire(cls, [])
    for w in ("create", "update", "delete", "post_write", "save", "remove"):
        assert not hasattr(ent, w)
