"""wm 模块 M2 bare-array list-only 主数据单测：wm.move_type / wm.rd_category（issue #13）。

两个实体均为 list-only：后端返**裸 JSON 数组**，走 #10 的 _list_bare/coerce_to_page 包成
Page(items=arr, page=0, total=len, has_next=False)，**不**经 envelope.normalize（裸 list 进
normalize 会因 _extract_total 调 .get 抛 AttributeError）、**不**被 get_json `or {}` 吞成空 dict。

覆盖 §6 行 269-285 + 模块级坑 252-262：
- move_type: list-only 无 get，filter = move_direction(I/O)/move_type_no/disabled；
  disabled 是 bool flag → 透传序列化成字符串 'true'/'false'（不传 Python True/False）。
- rd_category: list-only 全量无 filter，最薄；无 get。
全程 FakeTransport 桩（直接实例化实体类，不经 facade），桩不碰真后端/CLI。
"""
from dataclasses import dataclass, field

import pytest

from in3_client.auth import Session
from in3_client.config import Credentials
from in3_client.envelope import Page
from in3_client.entities.wm import MoveTypeEntity, RdCategoryEntity


# ---------- 桩（照 test_m0_post_paged_bare_coerce.py / test_entities_simple.py）----------

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
        self.calls.append(
            {"method": method, "url": url, "headers": headers, "params": params, "json": kw.get("json")}
        )
        return self.responses.pop(0)


_CRED = Credentials(
    api_host="https://apiv3.industics.com/service",
    tenant_domain="indx",
    username="corp:zhuzheng@indx",
    encrypted_password="AESCIPHER==",
    alias="zhuzheng",
)
_TOKEN = {"access_token": "jwt", "tenant_id": "10030", "tenant_domain": "indx", "user_id": "u-42"}


def _wire(entity_cls, data_responses):
    from in3_client.http import HttpClient
    sess = Session(_CRED, transport=FakeTransport([FakeResponse(200, _TOKEN)]))
    data_tr = FakeTransport(data_responses)
    http = HttpClient(sess, transport=data_tr)
    return entity_cls(_CRED, sess, http), data_tr


# =========================================================
# wm.move_type —— list-only bare-array + filter + bool flag
# =========================================================

def test_move_type_list_bare_array_wrapped_not_swallowed():
    """裸数组被正确包成 items（回归 normalize 吞空 / get_json `or {}` 吞空）。"""
    ent, tr = _wire(MoveTypeEntity, [FakeResponse(200, [
        {"move_type_no": "101", "move_direction": "I"},
        {"move_type_no": "201", "move_direction": "O"},
    ])])
    page = ent.list()
    assert isinstance(page, Page)
    assert page.items == [
        {"move_type_no": "101", "move_direction": "I"},
        {"move_type_no": "201", "move_direction": "O"},
    ]
    assert page.page == 0
    assert page.total == 2
    assert page.has_next is False


def test_move_type_empty_bare_array_total_zero():
    """空裸数组 → Page(items=[], total=0)，不被吞成空 dict。"""
    ent, tr = _wire(MoveTypeEntity, [FakeResponse(200, [])])
    page = ent.list()
    assert page.items == []
    assert page.total == 0
    assert page.has_next is False


def test_move_type_list_url_get_method():
    """走 GET _request 原值路径（非 get_page）；URL 用 base_url(wm) + 端点。"""
    ent, tr = _wire(MoveTypeEntity, [FakeResponse(200, [])])
    ent.list()
    assert tr.calls[0]["method"] == "GET"
    assert tr.calls[0]["url"] == (
        "https://apiv3.industics.com/service/mom/wm/v2/api/tenants/10030/move-types"
    )


def test_move_type_filter_move_direction_and_no_passthrough():
    """move_direction(I/O) + move_type_no 作 query 透传。"""
    ent, tr = _wire(MoveTypeEntity, [FakeResponse(200, [])])
    ent.list(move_direction="I", move_type_no="101")
    params = tr.calls[0]["params"]
    assert params["move_direction"] == "I"
    assert params["move_type_no"] == "101"


def test_move_type_disabled_bool_true_serialized_to_string():
    """disabled bool flag：Python True → 字符串 'true'（CLI 透传约定，不传 Python True）。"""
    ent, tr = _wire(MoveTypeEntity, [FakeResponse(200, [])])
    ent.list(disabled=True)
    assert tr.calls[0]["params"]["disabled"] == "true"


def test_move_type_disabled_bool_false_serialized_to_string():
    ent, tr = _wire(MoveTypeEntity, [FakeResponse(200, [])])
    ent.list(disabled=False)
    assert tr.calls[0]["params"]["disabled"] == "false"


def test_move_type_disabled_string_passthrough_as_is():
    """已是字符串 'true'/'false' 时原样透传（不二次包装）。"""
    ent, tr = _wire(MoveTypeEntity, [FakeResponse(200, [])])
    ent.list(disabled="false")
    assert tr.calls[0]["params"]["disabled"] == "false"


def test_move_type_filter_dict_also_accepted():
    """显式 filter dict 与具名参合并透传（具名参覆盖同名 filter 键）。"""
    ent, tr = _wire(MoveTypeEntity, [FakeResponse(200, [])])
    ent.list(filter={"move_type_no": "999"}, move_direction="O")
    params = tr.calls[0]["params"]
    assert params["move_type_no"] == "999"
    assert params["move_direction"] == "O"


def test_move_type_no_filter_emits_no_business_params():
    """无 filter 时 query 不含业务键（只可能有端点自身需要的，无业务 filter）。"""
    ent, tr = _wire(MoveTypeEntity, [FakeResponse(200, [])])
    ent.list()
    params = tr.calls[0]["params"] or {}
    for k in ("move_direction", "move_type_no", "disabled"):
        assert k not in params


def test_move_type_has_no_get_method():
    """list-only 无 /{id} get —— 忠实不假装（照 sd.sales_order_item 诚实约定）。"""
    ent, _ = _wire(MoveTypeEntity, [])
    assert not hasattr(ent, "get")


def test_move_type_no_write_methods():
    """只读边界守护：不生成 create/update/delete/post-write。"""
    ent, _ = _wire(MoveTypeEntity, [])
    for w in ("create", "update", "delete", "post_write", "save", "remove"):
        assert not hasattr(ent, w)


# =========================================================
# wm.rd_category —— 最薄 list-only，全量无 filter
# =========================================================

def test_rd_category_list_bare_array_wrapped():
    ent, tr = _wire(RdCategoryEntity, [FakeResponse(200, [
        {"rd_category_no": "1", "rd_category_name": "采购入库"},
        {"rd_category_no": "2", "rd_category_name": "销售出库"},
    ])])
    page = ent.list()
    assert isinstance(page, Page)
    assert [it["rd_category_no"] for it in page.items] == ["1", "2"]
    assert page.page == 0
    assert page.total == 2
    assert page.has_next is False


def test_rd_category_empty_bare_array_total_zero():
    ent, tr = _wire(RdCategoryEntity, [FakeResponse(200, [])])
    page = ent.list()
    assert page.items == []
    assert page.total == 0
    assert page.has_next is False


def test_rd_category_list_url_get_method():
    ent, tr = _wire(RdCategoryEntity, [FakeResponse(200, [])])
    ent.list()
    assert tr.calls[0]["method"] == "GET"
    # live parity 校正：单数 rd-category + /list 后缀（旧复数 /rd-categories 报 405）。
    assert tr.calls[0]["url"] == (
        "https://apiv3.industics.com/service/mom/wm/v2/api/tenants/10030/rd-category/list"
    )


def test_rd_category_list_takes_no_business_filter_params():
    """最薄：list() 不收业务 filter 参数（全量无 filter）—— 仅 size/all。"""
    import inspect
    sig = inspect.signature(RdCategoryEntity.list)
    param_names = set(sig.parameters) - {"self"}
    assert param_names == {"size", "all"}


def test_rd_category_emits_no_business_params():
    ent, tr = _wire(RdCategoryEntity, [FakeResponse(200, [])])
    ent.list()
    # 全量无 filter：query 不含任何业务键。
    params = tr.calls[0]["params"] or {}
    assert "filter" not in params


def test_rd_category_has_no_get_method():
    ent, _ = _wire(RdCategoryEntity, [])
    assert not hasattr(ent, "get")


def test_rd_category_no_write_methods():
    ent, _ = _wire(RdCategoryEntity, [])
    for w in ("create", "update", "delete", "post_write", "save", "remove"):
        assert not hasattr(ent, w)
