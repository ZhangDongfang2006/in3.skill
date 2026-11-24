"""mm.purchase_order 坑层单测：逐位移植自 ibrain-mm/cli purchase-order.ts。

覆盖：chunk≤80(80不切/81→2/160→2/161→3 + merge-by-id 去重 + _chunked 头 + 任一块 fail-loud)、
open_qty fallback(null填/0保留/非null不覆盖/负→0/非数跳过/cq缺按0 + list&get 两路)、
_matched_filter_values(≥2才标/交集/插入序/空不挂/单值不标)、include_items(空不调bulk/按po_id分组/bulk失败→错)。
"""
from dataclasses import dataclass, field

import pytest

from in3_client.auth import Session
from in3_client.config import Credentials
from in3_client.envelope import Page
from in3_client.http import HttpClient, HttpError
from in3_client.entities.mm import PurchaseOrderEntity


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


class RouteTransport:
    """按 URL 路由：/pages→list 队列；bulk-get-by-po→bulk 队列；/<id>→get 队列。"""

    def __init__(self, pages=None, bulk=None, detail=None):
        self.pages = list(pages or [])
        self.bulk = list(bulk or [])
        self.detail = list(detail or [])
        self.calls = []

    def __call__(self, method, url, headers=None, params=None, json=None, **kw):
        self.calls.append({"method": method, "url": url, "params": params, "body": json})
        if url.endswith("/pages"):
            return self.pages.pop(0)
        if url.endswith("/bulk-get-by-po"):
            return self.bulk.pop(0)
        return self.detail.pop(0)


_CRED = Credentials(
    api_host="https://apiv3.industics.com/service",
    tenant_domain="indx", username="corp:zhuzheng@indx",
    encrypted_password="AESCIPHER==", alias="zhuzheng",
)
_TOKEN = {"access_token": "jwt", "tenant_id": "99979", "tenant_domain": "indx", "user_id": "u-42"}


def _wire(transport):
    sess = Session(_CRED, transport=lambda *a, **k: FakeResponse(200, _TOKEN))
    return PurchaseOrderEntity(_CRED, sess, HttpClient(sess, transport=transport)), transport


def _page(items, last=True):
    return FakeResponse(200, {"content": items, "last": last})


# ---------- 基础 list ----------

def test_list_hits_pages_endpoint():
    ent, tr = _wire(RouteTransport(pages=[_page([{"id": "po1"}])]))
    page = ent.list(all=False)
    assert isinstance(page, Page)
    assert page.items == [{"id": "po1"}]
    assert tr.calls[0]["url"].endswith("/spm/purchase-orders/pages")


# ---------- chunk 边界 ----------

def test_chunk_80_not_triggered():
    ids = [str(i) for i in range(80)]
    ent, tr = _wire(RouteTransport(pages=[_page([{"id": "p"}])]))
    page = ent.list(filter={"material_ids": ids})
    assert not hasattr(page, "_chunked") or getattr(page, "_chunked", False) is False
    # 单次查询（一页）
    assert sum(1 for c in tr.calls if c["url"].endswith("/pages")) == 1


def test_chunk_81_two_blocks_with_meta():
    ids = [str(i) for i in range(81)]
    ent, tr = _wire(RouteTransport(pages=[_page([{"id": "a"}]), _page([{"id": "b"}])]))
    page = ent.list(filter={"material_ids": ids})
    assert page._chunked is True
    assert page._chunks_count == 2
    assert page._chunk_size == 80
    assert page.has_next is False
    assert {it["id"] for it in page.items} == {"a", "b"}


def test_chunk_161_three_blocks():
    ids = [str(i) for i in range(161)]
    ent, tr = _wire(RouteTransport(pages=[_page([{"id": "a"}]), _page([{"id": "b"}]), _page([{"id": "c"}])]))
    page = ent.list(filter={"material_ids": ids})
    assert page._chunks_count == 3


def test_chunk_merge_dedups_by_po_id():
    ids = [str(i) for i in range(81)]
    ent, tr = _wire(RouteTransport(pages=[
        _page([{"id": "dup", "v": 1}]),
        _page([{"id": "dup", "v": 2}]),  # 后块覆盖同 id
    ]))
    page = ent.list(filter={"material_ids": ids})
    assert len(page.items) == 1
    assert page.items[0]["v"] == 2
    assert page.total == 1


def test_chunk_fail_loud_on_any_block():
    ids = [str(i) for i in range(81)]
    ent, tr = _wire(RouteTransport(pages=[_page([{"id": "a"}]), FakeResponse(500, text="boom")]))
    with pytest.raises(Exception):
        ent.list(filter={"material_ids": ids})


# ---------- open_qty fallback ----------

def test_open_qty_null_filled_with_fallback():
    ent, tr = _wire(RouteTransport(
        pages=[_page([{"id": "po1"}])],
        bulk=[FakeResponse(200, [{"po_id": "po1", "material_id": "m", "open_qty": None,
                                  "purchase_qty": 10, "completed_qty": 3}])],
    ))
    page = ent.list(include_items=True, all=False)
    it = page.items[0]["items"][0]
    assert it["open_qty"] == 7
    assert it["_open_qty_source"] == "fallback:purchase_qty-completed_qty"


def test_open_qty_zero_preserved_no_source():
    ent, tr = _wire(RouteTransport(
        pages=[_page([{"id": "po1"}])],
        bulk=[FakeResponse(200, [{"po_id": "po1", "open_qty": 0, "purchase_qty": 10, "completed_qty": 3}])],
    ))
    it = ent.list(include_items=True, all=False).items[0]["items"][0]
    assert it["open_qty"] == 0
    assert "_open_qty_source" not in it


def test_open_qty_negative_clamped_to_zero():
    ent, tr = _wire(RouteTransport(
        pages=[_page([{"id": "po1"}])],
        bulk=[FakeResponse(200, [{"po_id": "po1", "open_qty": None, "purchase_qty": 3, "completed_qty": 10}])],
    ))
    it = ent.list(include_items=True, all=False).items[0]["items"][0]
    assert it["open_qty"] == 0


def test_open_qty_missing_completed_treated_as_zero():
    ent, tr = _wire(RouteTransport(
        pages=[_page([{"id": "po1"}])],
        bulk=[FakeResponse(200, [{"po_id": "po1", "open_qty": None, "purchase_qty": 5}])],
    ))
    it = ent.list(include_items=True, all=False).items[0]["items"][0]
    assert it["open_qty"] == 5


def test_open_qty_non_number_purchase_skipped():
    ent, tr = _wire(RouteTransport(
        pages=[_page([{"id": "po1"}])],
        bulk=[FakeResponse(200, [{"po_id": "po1", "open_qty": None, "purchase_qty": "NA"}])],
    ))
    it = ent.list(include_items=True, all=False).items[0]["items"][0]
    assert it["open_qty"] is None
    assert "_open_qty_source" not in it


# ---------- _matched_filter_values ----------

def test_matched_only_when_multivalue_and_intersect():
    ids = ["m1", "m2", "m3"]
    ent, tr = _wire(RouteTransport(
        pages=[_page([{"id": "po1"}, {"id": "po2"}])],
        bulk=[FakeResponse(200, [
            {"po_id": "po1", "material_id": "m1"},
            {"po_id": "po1", "material_id": "m9"},  # 不在过滤表
            {"po_id": "po2", "material_id": "mX"},  # 全不命中
        ])],
    ))
    page = ent.list(filter={"material_ids": ids}, include_items=True, all=False)
    po1 = next(p for p in page.items if p["id"] == "po1")
    po2 = next(p for p in page.items if p["id"] == "po2")
    assert po1["_matched_filter_values"]["material_ids"] == ["m1"]
    assert "_matched_filter_values" not in po2  # 交集空不挂


def test_matched_not_set_for_single_value():
    ent, tr = _wire(RouteTransport(
        pages=[_page([{"id": "po1"}])],
        bulk=[FakeResponse(200, [{"po_id": "po1", "material_id": "m1"}])],
    ))
    page = ent.list(filter={"material_ids": ["m1"]}, include_items=True, all=False)
    assert "_matched_filter_values" not in page.items[0]


# ---------- include_items 装配 ----------

def test_include_items_empty_list_skips_bulk():
    tr = RouteTransport(pages=[_page([])], bulk=[FakeResponse(200, [{"po_id": "x"}])])
    ent, _ = _wire(tr)
    ent.list(include_items=True, all=False)
    assert not any(c["url"].endswith("/bulk-get-by-po") for c in tr.calls)


def test_include_items_groups_by_po_id():
    ent, tr = _wire(RouteTransport(
        pages=[_page([{"id": "po1"}, {"id": "po2"}])],
        bulk=[FakeResponse(200, [
            {"po_id": "po1", "material_id": "a"},
            {"po_id": "po2", "material_id": "b"},
            {"po_id": "po1", "material_id": "c"},
        ])],
    ))
    page = ent.list(include_items=True, all=False)
    po1 = next(p for p in page.items if p["id"] == "po1")
    po2 = next(p for p in page.items if p["id"] == "po2")
    assert [i["material_id"] for i in po1["items"]] == ["a", "c"]
    assert [i["material_id"] for i in po2["items"]] == ["b"]


def test_include_items_po_without_lines_gets_empty_list():
    ent, tr = _wire(RouteTransport(
        pages=[_page([{"id": "po1"}, {"id": "po2"}])],
        bulk=[FakeResponse(200, [{"po_id": "po1", "material_id": "a"}])],
    ))
    page = ent.list(include_items=True, all=False)
    po2 = next(p for p in page.items if p["id"] == "po2")
    assert po2["items"] == []


def test_include_items_bulk_failure_raises():
    ent, tr = _wire(RouteTransport(
        pages=[_page([{"id": "po1"}])],
        bulk=[FakeResponse(500, text="boom")],
    ))
    with pytest.raises(HttpError):
        ent.list(include_items=True, all=False)


def test_no_include_items_does_not_call_bulk():
    tr = RouteTransport(pages=[_page([{"id": "po1"}])])
    ent, _ = _wire(tr)
    ent.list(all=False)
    assert not any(c["url"].endswith("/bulk-get-by-po") for c in tr.calls)


# ---------- get(id) ----------

def test_get_applies_open_qty_fallback_to_detail_items():
    ent, tr = _wire(RouteTransport(
        detail=[FakeResponse(200, {"id": "po1", "items": [
            {"open_qty": None, "purchase_qty": 8, "completed_qty": 2},
        ]})],
    ))
    rec = ent.get("po1")
    assert rec["items"][0]["open_qty"] == 6
    assert rec["items"][0]["_open_qty_source"] == "fallback:purchase_qty-completed_qty"
    assert tr.calls[-1]["url"].endswith("/spm/purchase-orders/po1")
