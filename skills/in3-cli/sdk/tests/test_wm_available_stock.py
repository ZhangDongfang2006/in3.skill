"""wm.available_stock 单测：POST 分页（page/size 在 query、filter 在 body）+ by_materials fan-out。

真实坑层（已对真后端核实）：① POST-only，空 filter 返 0 → by_materials 是主入口；
② 可用库存字段 = available_qty（**非** total_quantity，可为负）；③ 无 top-level id → dedup
主键 (material_id, plant_no)；④ multi-filter 并集语义 → 回挂 _matched_filter_values。
"""
from dataclasses import dataclass, field

import pytest

from in3_client.auth import Session
from in3_client.config import Credentials
from in3_client.envelope import Page
from in3_client.http import HttpClient
from in3_client.entities.wm import AvailableStockEntity


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

    def __call__(self, method, url, headers=None, params=None, json=None, **kw):
        self.calls.append({"method": method, "url": url, "params": params, "body": json})
        return self.responses.pop(0)


_CRED = Credentials(
    api_host="https://apiv3.industics.com/service",
    tenant_domain="indx", username="corp:zhuzheng@indx",
    encrypted_password="AESCIPHER==", alias="zhuzheng",
)
_TOKEN = {"access_token": "jwt", "tenant_id": "10030", "tenant_domain": "indx", "user_id": "u-42"}


def _wire(data_responses):
    sess = Session(_CRED, transport=FakeTransport([FakeResponse(200, _TOKEN)]))
    data_tr = FakeTransport(data_responses)
    return AvailableStockEntity(_CRED, sess, HttpClient(sess, transport=data_tr)), data_tr


def _rec(mid, plant="1", qty=0):
    return {"material_id": mid, "plant_no": plant, "available_qty": qty}


def test_list_is_post_with_pagesize_in_query_and_filter_in_body():
    ent, tr = _wire([FakeResponse(200, {"content": [_rec("a")], "last": True})])
    ent.list(filter={"material_ids": ["a"]}, all=False)
    call = tr.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == (
        "https://apiv3.industics.com/service/mom/wm"
        "/v2/api/tenants/10030/stocks/available-stocks/page"
    )
    assert call["params"]["page"] == "0" and call["params"]["size"]   # 分页在 query
    assert call["body"] == {"material_ids": ["a"]}                    # filter 在 body


def test_list_normalizes_and_total_below_len_is_none():
    ent, tr = _wire([FakeResponse(200, {"content": [_rec("a"), _rec("b")], "total": 0})])
    page = ent.list(all=False)
    assert isinstance(page, Page)
    assert page.total is None


def test_by_materials_empty_sends_no_request():
    ent, tr = _wire([])
    page = ent.by_materials([])
    assert page.items == []
    assert len(tr.calls) == 0  # 不发畸形 body


def test_by_materials_chunks_over_80():
    ids = [str(i) for i in range(81)]
    # 两块，各返 last=True
    ent, tr = _wire([
        FakeResponse(200, {"content": [_rec(i) for i in ids[:80]], "last": True}),
        FakeResponse(200, {"content": [_rec(ids[80])], "last": True}),
    ])
    page = ent.by_materials(ids)
    assert len(tr.calls) == 2
    assert tr.calls[0]["body"]["material_ids"] == ids[:80]
    assert tr.calls[1]["body"]["material_ids"] == [ids[80]]
    assert len(page.items) == 81


def test_by_materials_dedups_by_material_and_plant():
    # 两块返回同一 (material_id, plant) → 去重；不同 plant → 保留
    ent, tr = _wire([
        FakeResponse(200, {"content": [_rec("a", "1"), _rec("a", "2")], "last": True}),
    ])
    page = ent.by_materials(["a"])
    keys = {(r["material_id"], r["plant_no"]) for r in page.items}
    assert keys == {("a", "1"), ("a", "2")}


def test_by_materials_fail_loud_on_any_chunk_failure():
    ids = [str(i) for i in range(81)]
    ent, tr = _wire([
        FakeResponse(200, {"content": [_rec(i) for i in ids[:80]], "last": True}),
        FakeResponse(500, text="boom"),  # 第二块炸
    ])
    with pytest.raises(Exception):
        ent.by_materials(ids)  # 绝不静默返回第一块


def test_by_materials_attaches_matched_filter_values():
    # 请求 a,b,c；后端并集多返 z；交集应是 a,b
    ent, tr = _wire([
        FakeResponse(200, {"content": [_rec("a"), _rec("b"), _rec("z")], "last": True}),
    ])
    page = ent.by_materials(["a", "b", "c"])
    for r in page.items:
        assert set(r["_matched_filter_values"]["material_ids"]) == {"a", "b"}


def test_by_materials_available_qty_present():
    ent, tr = _wire([FakeResponse(200, {"content": [_rec("a", qty=-10.0)], "last": True})])
    page = ent.by_materials(["a"])
    assert page.items[0]["available_qty"] == -10.0
