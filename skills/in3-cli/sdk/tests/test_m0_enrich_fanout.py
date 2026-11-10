"""M0 基座②单测：gotchas.enrich_items_fanout —— per-header bounded FAIL-ISOLATED fan-out。

供 sd.sales-order / sd.contract / pp.production-plan 的 client-side include_items 用。
覆盖 AC：
- 对每个 header 调 fetch_items_for 取行项，成功时把 items 挂回该 header；并发受 concurrency 约束。
- fail-isolated 隔离：单 header 的 fetch 抛异常 → 该 header items=None + 旁挂 items_error，
  异常不冒泡，其余 header 正常返回（本片核心断言）。
- 三 fail-mode 对照：同一组失败输入下，enrich_items_fanout（失败留 items=None+items_error）、
  fan_out（失败项被 skip 不出现在结果）、fail-loud（失败直接抛错中断）三者行为各不相同。
"""
import threading
import time

import pytest

from in3_client.envelope import Page
from in3_client.gotchas import enrich_items_fanout, fan_out


def test_enrich_attaches_items_on_success():
    headers = [{"id": "A"}, {"id": "B"}]

    def fetch(h):
        return [{"line": h["id"] + "-1"}, {"line": h["id"] + "-2"}]

    out = enrich_items_fanout(headers, fetch)
    assert len(out) == 2
    assert out[0]["items"] == [{"line": "A-1"}, {"line": "A-2"}]
    assert out[1]["items"] == [{"line": "B-1"}, {"line": "B-2"}]
    # 原 header 字段保留，无 items_error
    assert out[0]["id"] == "A"
    assert "items_error" not in out[0]
    assert "items_error" not in out[1]


def test_enrich_does_not_mutate_input_headers():
    headers = [{"id": "A"}]
    enrich_items_fanout(headers, lambda h: [{"x": 1}])
    # 入参 header 不被就地塞 items（返回的是新 dict）
    assert "items" not in headers[0]


def test_enrich_fail_isolated_single_header_failure():
    """核心断言：单 header fetch 抛异常 → 该 header items=None + items_error，异常不冒泡，其余正常。"""
    headers = [{"id": "A"}, {"id": "BAD"}, {"id": "C"}]

    def fetch(h):
        if h["id"] == "BAD":
            raise RuntimeError("boom: 503 from backend")
        return [{"line": h["id"]}]

    out = enrich_items_fanout(headers, fetch)  # 不抛
    by_id = {r["id"]: r for r in out}
    # 失败 header：items=None + items_error 含错误摘要
    assert by_id["BAD"]["items"] is None
    assert "items_error" in by_id["BAD"]
    assert "boom" in by_id["BAD"]["items_error"]
    # 其余 header 正常
    assert by_id["A"]["items"] == [{"line": "A"}]
    assert "items_error" not in by_id["A"]
    assert by_id["C"]["items"] == [{"line": "C"}]
    # 全部 3 个 header 都在结果里（无丢失）
    assert len(out) == 3


def test_enrich_preserves_header_order():
    headers = [{"id": str(i)} for i in range(10)]
    out = enrich_items_fanout(headers, lambda h: [{"v": h["id"]}], concurrency=3)
    assert [r["id"] for r in out] == [str(i) for i in range(10)]


def test_enrich_concurrency_is_bounded():
    """并发上限受 concurrency 约束：同时在飞的 fetch 数不超过 concurrency。"""
    headers = [{"id": str(i)} for i in range(12)]
    lock = threading.Lock()
    state = {"inflight": 0, "max": 0}

    def fetch(h):
        with lock:
            state["inflight"] += 1
            state["max"] = max(state["max"], state["inflight"])
        time.sleep(0.02)
        with lock:
            state["inflight"] -= 1
        return [{"v": h["id"]}]

    enrich_items_fanout(headers, fetch, concurrency=4)
    assert state["max"] <= 4


def test_enrich_empty_headers_returns_empty():
    assert enrich_items_fanout([], lambda h: [{"x": 1}]) == []


# ---- 三 fail-mode 对照：同一组失败输入下三者行为各不相同 ----

def _three_ids():
    return ["ok1", "BAD", "ok2"]


def _page_fetch_one(mid):
    """fan_out 用：返回 Page；BAD 抛错。"""
    if mid == "BAD":
        raise RuntimeError("boom")
    return Page(items=[{"line": mid}], page=0, total=1, has_next=False)


def _fail_loud_bulk(ids):
    """fail-loud 路径模拟：任一失败直接抛错中断（mm.PurchaseOrder bulk-get 语义）。"""
    out = []
    for mid in ids:
        if mid == "BAD":
            raise RuntimeError("bulk fail-loud abort")
        out.append({"line": mid})
    return out


def test_three_fail_modes_differ_under_same_failure():
    ids = _three_ids()

    # (1) enrich_items_fanout: fail-isolated —— 失败项留 items=None + items_error，3 个 header 全在
    headers = [{"id": i} for i in ids]

    def enrich_fetch(h):
        if h["id"] == "BAD":
            raise RuntimeError("boom")
        return [{"line": h["id"]}]

    enriched = enrich_items_fanout(headers, enrich_fetch)
    assert len(enriched) == 3  # 失败项仍在
    bad = next(r for r in enriched if r["id"] == "BAD")
    assert bad["items"] is None and "items_error" in bad

    # (2) fan_out: skip-on-error —— 失败项被丢弃、不在结果里留痕（items 只剩 2 条成功项的）
    fanned = fan_out(ids, _page_fetch_one)
    assert isinstance(fanned, Page)
    # BAD 整个跳过：聚合 items 里只有 ok1 / ok2，没有任何 BAD 的痕迹
    assert fanned.items == [{"line": "ok1"}, {"line": "ok2"}]
    assert all("error" not in str(it) for it in fanned.items)

    # (3) fail-loud: 失败直接抛错中断，没有部分结果返回
    with pytest.raises(RuntimeError):
        _fail_loud_bulk(ids)
