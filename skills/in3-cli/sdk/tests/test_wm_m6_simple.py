"""#17 M6 批 A · wm simple 5 实体单测（直接实例化，FakeTransport，不经 facade）。

覆盖 storage_location / storage_bin / warehouse / unit / requisition：
- list-only（storage_location/storage_bin）断言 `not hasattr(entity, 'get')`（忠实不假装）。
- list+get（warehouse/unit/requisition）双方法齐全。
- bool flag（fuzzy/exclude_forbidden_in/in_forbidden 等）透传 query 序列化成字符串 'true'/'false'。
- plant flag → plant_id query；storage_bin 20+ flag 走 filter dict（少量具名参，签名不爆炸）。
- 命名歧义边界（unit 是 SN 非计量单位）在 entity docstring；测试钉死端点 + flag 序列化。
- 只读边界：每实体断言 not hasattr create/update/delete。

桩照 tests/test_qm_verbs.py：FakeResponse / FakeTransport。
"""
from dataclasses import dataclass, field

import pytest

from in3_client.auth import Session
from in3_client.config import Credentials
from in3_client.envelope import Page
from in3_client.entities.wm import (
    RequisitionEntity,
    StorageBinEntity,
    StorageLocationEntity,
    UnitEntity,
    WarehouseEntity,
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


def _assert_read_only(ent):
    for m in _WRITE_METHODS:
        assert not hasattr(ent, m), f"只读边界破坏：{type(ent).__name__} 不该有 {m}"


# ========================================================
# storage_location：list-only，无 get
# ========================================================

def test_storage_location_list_paged_and_no_get():
    ent, tr = _wire(StorageLocationEntity, [_spring_page([{"id": "sl1"}])])
    page = ent.list(all=False)
    assert isinstance(page, Page)
    assert page.items == [{"id": "sl1"}]
    assert tr.calls[0]["method"] == "GET"
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/storage-locations/page"
    # list-only：忠实不暴露 get。
    assert not hasattr(ent, "get")
    _assert_read_only(ent)


def test_storage_location_plant_maps_to_plant_id():
    ent, tr = _wire(StorageLocationEntity, [_spring_page([])])
    ent.list(plant="P01", storage_location_no="SL-9", key_word="kw", all=False)
    p = tr.calls[0]["params"]
    assert p["plant_id"] == "P01"  # plant flag → plant_id query
    assert "plant" not in p
    assert p["storage_location_no"] == "SL-9"
    assert p["key_word"] == "kw"


# ========================================================
# storage_bin：list-only，无 get，bool flag 字符串化，filter dict 透传
# ========================================================

def test_storage_bin_list_no_get():
    ent, tr = _wire(StorageBinEntity, [_spring_page([{"id": "b1"}])])
    page = ent.list(all=False)
    assert page.items == [{"id": "b1"}]
    # live parity 校正：base 段是 /bins（CLI base10 = .../bins），非 /storage-bins。
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/bins/page"
    assert not hasattr(ent, "get")
    _assert_read_only(ent)


def test_storage_bin_bool_flag_in_filter_serialized_to_string():
    ent, tr = _wire(StorageBinEntity, [_spring_page([])])
    # 20+ flag 走 filter dict（避免签名爆炸）；bool flag → 'true'/'false' 字符串。
    ent.list(
        plant="P01",
        warehouse_no="WH1",
        filter={"in_forbidden": True, "not_include_unbound": False, "storage_section_name": "A"},
        all=False,
    )
    p = tr.calls[0]["params"]
    assert p["plant_id"] == "P01"
    assert p["warehouse_no"] == "WH1"
    assert p["in_forbidden"] == "true"          # bool → 字符串，不是 Python True
    assert p["not_include_unbound"] == "false"
    assert p["storage_section_name"] == "A"     # 非 bool 走 filter 原样透传


def test_storage_bin_any_bool_flag_in_filter_serialized_generic():
    """通用 bool 序列化：任意进 filter dict 的 bool（含原白名单外的 20+ flag）都转 'true'/'false'。

    钉死「不依赖白名单」——out_forbidden/default_entry_bin（原白名单内但本测前未断言）+
    arbitrary_unbound_only（白名单**外**的 bool flag，旧逻辑会漏转成 Python True/'True'）。
    """
    ent, tr = _wire(StorageBinEntity, [_spring_page([])])
    ent.list(
        filter={
            "out_forbidden": True,
            "default_entry_bin": False,
            # 白名单外的 bool flag：旧「仅白名单」逻辑会漏转 → 这里钉死必须转字符串。
            "arbitrary_unbound_only": True,
            "in_block_status": False,
            "max_volume": 100,          # 非 bool int 原样
            "storage_type": "PALLET",   # 非 bool str 原样
            "already_str": "false",     # 已是字符串不重复处理
        },
        all=False,
    )
    p = tr.calls[0]["params"]
    assert p["out_forbidden"] == "true"
    assert p["default_entry_bin"] == "false"
    assert p["arbitrary_unbound_only"] == "true"   # 白名单外也转，不再是 Python True
    assert p["in_block_status"] == "false"
    assert p["max_volume"] == 100                   # int 不误伤
    assert p["storage_type"] == "PALLET"            # str 不误伤
    assert p["already_str"] == "false"              # 已是字符串原样


# ========================================================
# warehouse：list + get，bool flag 字符串化
# ========================================================

def test_warehouse_list_and_get_both_present():
    # live parity 校正：warehouse list = GET .../warehouse-nos 裸数组（无 /page 无信封）→ _list_bare。
    ent, tr = _wire(WarehouseEntity, [FakeResponse(200, [{"id": "w1"}])])
    page = ent.list(all=False)
    assert page.items == [{"id": "w1"}]
    assert tr.calls[0]["method"] == "GET"
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/warehouse-nos"
    assert hasattr(ent, "get")
    _assert_read_only(ent)


def test_warehouse_get_path_id():
    ent, tr = _wire(WarehouseEntity, [FakeResponse(200, {"id": "w9", "warehouse_no": "WH9"})])
    rec = ent.get("w9")
    assert rec["id"] == "w9"
    # live parity 校正：单数 warehouse-no/{id}。
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/warehouse-no/w9"


def test_warehouse_bool_flags_serialized():
    ent, tr = _wire(WarehouseEntity, [FakeResponse(200, [])])  # 裸数组端点
    ent.list(plant="P01", exclude_forbidden_in=True, include_deleted=False, all=False)
    p = tr.calls[0]["params"]
    assert p["plant_id"] == "P01"
    assert p["exclude_forbidden_in"] == "true"
    assert p["include_deleted"] == "false"


def test_warehouse_all_named_bool_flags_serialized():
    """补齐前未断言的具名 bool flag（exclude_forbidden_out/is_all_multi_org）+ 白名单外
    filter dict bool，钉死任意 bool 都转字符串。"""
    ent, tr = _wire(WarehouseEntity, [FakeResponse(200, [])])  # 裸数组端点
    ent.list(
        exclude_forbidden_out=True,
        is_all_multi_org=False,
        filter={"extra_flag": True, "description": "main"},  # filter dict 里白名单外的 bool
        all=False,
    )
    p = tr.calls[0]["params"]
    assert p["exclude_forbidden_out"] == "true"
    assert p["is_all_multi_org"] == "false"
    assert p["extra_flag"] == "true"        # 白名单外的 filter bool 也转字符串
    assert p["description"] == "main"       # 非 bool 原样


# ========================================================
# unit：库存单元/SN（非计量单位），list + get，fuzzy bool
# ========================================================

def test_unit_list_and_get_both_present():
    ent, tr = _wire(UnitEntity, [_spring_page([{"id": "u1", "sn": "SN-1"}])])
    page = ent.list(all=False)
    assert page.items == [{"id": "u1", "sn": "SN-1"}]
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/units/page"
    assert hasattr(ent, "get")
    _assert_read_only(ent)


def test_unit_fuzzy_bool_serialized_and_sn_filter():
    ent, tr = _wire(UnitEntity, [_spring_page([])])
    ent.list(sn="SN-7", fuzzy=True, status="IN_STOCK", mo_id="mo1", all=False)
    p = tr.calls[0]["params"]
    assert p["sn"] == "SN-7"
    assert p["fuzzy"] == "true"          # bool → 字符串
    assert p["status"] == "IN_STOCK"
    assert p["mo_id"] == "mo1"


def test_unit_filter_dict_bool_serialized_generic():
    """unit 的 filter dict 里塞进来的任意 bool 也走通用序列化（fuzzy 具名 + filter dict 共治）。"""
    ent, tr = _wire(UnitEntity, [_spring_page([])])
    ent.list(fuzzy=False, filter={"include_scrapped": True, "sn_prefix": "SN"}, all=False)
    p = tr.calls[0]["params"]
    assert p["fuzzy"] == "false"
    assert p["include_scrapped"] == "true"   # filter dict bool 也转字符串
    assert p["sn_prefix"] == "SN"            # 非 bool 原样


def test_unit_get_path_id():
    ent, tr = _wire(UnitEntity, [FakeResponse(200, {"id": "u9"})])
    rec = ent.get("u9")
    assert rec["id"] == "u9"
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/units/u9"


# ========================================================
# requisition：list + get（领料申请）
# ========================================================

def test_requisition_list_and_get_both_present():
    ent, tr = _wire(RequisitionEntity, [_spring_page([{"id": "r1"}])])
    page = ent.list(all=False)
    assert page.items == [{"id": "r1"}]
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/requisitions/page"
    assert hasattr(ent, "get")
    _assert_read_only(ent)


def test_requisition_filters_passthrough():
    ent, tr = _wire(RequisitionEntity, [_spring_page([])])
    ent.list(plant="P01", mo_no="MO-1", finish_status="A,B", plan_start_date="2026-01-01", all=False)
    p = tr.calls[0]["params"]
    assert p["plant_id"] == "P01"
    assert p["mo_no"] == "MO-1"
    assert p["finish_status"] == "A,B"          # 多选逗号透传
    assert p["plan_start_date"] == "2026-01-01"


def test_requisition_get_path_id():
    ent, tr = _wire(RequisitionEntity, [FakeResponse(200, {"id": "r9"})])
    rec = ent.get("r9")
    assert rec["id"] == "r9"
    assert tr.calls[0]["url"] == _TENANT_PREFIX + "/requisitions/r9"
