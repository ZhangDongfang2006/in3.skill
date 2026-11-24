"""wm.stock 4 视图单测：路径/单值/多值 fan-out/互斥/material fail-loud/all 翻页/total None。

fan-out 并发下用「按 params['material_id'] 路由」的只读 transport，保证确定性。
"""
from dataclasses import dataclass

import pytest

from in3_client.auth import Session
from in3_client.config import Credentials
from in3_client.envelope import Page
from in3_client.http import HttpClient
from in3_client.entities.wm import StockEntity, StockValidationError


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


class KeyedTransport:
    """按 query 的 material_id 路由（线程安全只读）。by_mid: {mid: json or ('err',code)}。"""

    def __init__(self, by_mid=None, default=None):
        self.by_mid = by_mid or {}
        self.default = default
        self.urls = []

    def __call__(self, method, url, headers=None, params=None, json=None, **kw):
        self.urls.append(url)
        mid = (params or {}).get("material_id")
        spec = self.by_mid.get(mid, self.default)
        if isinstance(spec, tuple) and spec[0] == "err":
            return FakeResponse(spec[1], text="boom")
        return FakeResponse(200, spec if spec is not None else {"content": [], "last": True})


class QueueTransport:
    """单值 all 翻页用：按调用顺序返回（无并发）。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.params_seen = []

    def __call__(self, method, url, headers=None, params=None, json=None, **kw):
        self.params_seen.append(params)
        return self.responses.pop(0)


_CRED = Credentials(
    api_host="https://apiv3.industics.com/service",
    tenant_domain="indx", username="corp:zhuzheng@indx",
    encrypted_password="AESCIPHER==", alias="zhuzheng",
)
_TOKEN = {"access_token": "jwt", "tenant_id": "99979", "tenant_domain": "indx", "user_id": "u-42"}


def _entity(transport):
    sess = Session(_CRED, transport=lambda *a, **k: FakeResponse(200, _TOKEN))
    return StockEntity(_CRED, sess, HttpClient(sess, transport=transport)), transport


# ---------- 视图路径（单复数差异照实）----------

def test_view_paths():
    tr = KeyedTransport(default={"content": [{"x": 1}], "last": True})
    ent, _ = _entity(tr)
    ent.material(material_id="m1")
    assert tr.urls[-1].endswith("/stocks/material-stocks/page")      # 单数 page
    ent.bin(material_id="m1")
    assert tr.urls[-1].endswith("/stocks/bin-stocks/pages")          # 复数 pages
    ent.storage_location(material_id="m1")
    assert tr.urls[-1].endswith("/stocks/storage-location-stocks/pages")
    ent.storage_bin(material_id="m1")
    assert tr.urls[-1].endswith("/stocks/storage-bin-stocks/pages")


# ---------- 单值 ----------

def test_single_value_returns_page():
    tr = KeyedTransport({"m1": {"content": [{"q": 5}], "totalElements": 1, "last": True}})
    ent, _ = _entity(tr)
    page = ent.material(material_id="m1")
    assert isinstance(page, Page)
    assert page.items == [{"q": 5}]
    assert page.total == 1


# ---------- 多值 fan-out ----------

def test_multi_value_fans_out_and_aggregates():
    tr = KeyedTransport({
        "a": {"content": [{"id": "a1"}], "totalElements": 1, "last": True},
        "b": {"content": [{"id": "b1"}, {"id": "b2"}], "totalElements": 2, "last": True},
    })
    ent, _ = _entity(tr)
    page = ent.material(material_ids=["a", "b"])
    assert {it["id"] for it in page.items} == {"a1", "b1", "b2"}
    assert page.total == 3            # 1 + 2
    assert page.page == 0 and page.has_next is False


def test_multi_value_total_none_if_any_view_total_none():
    tr = KeyedTransport({
        "a": {"content": [{"id": "a1"}], "totalElements": 1, "last": True},
        "b": {"content": [{"id": "b1"}], "total": 0, "last": True},  # total<len → None
    })
    ent, _ = _entity(tr)
    page = ent.material(material_ids=["a", "b"])
    assert page.total is None


def test_multi_value_skip_on_error():
    tr = KeyedTransport({
        "a": {"content": [{"id": "a1"}], "totalElements": 1, "last": True},
        "b": ("err", 500),
        "c": {"content": [{"id": "c1"}], "totalElements": 1, "last": True},
    })
    ent, _ = _entity(tr)
    page = ent.material(material_ids=["a", "b", "c"])
    assert {it["id"] for it in page.items} == {"a1", "c1"}  # b 跳过不抛
    assert page.total == 2


def test_multi_value_ignores_all_flag():
    # 即使 all=True，多值走 fan-out 聚合页，不翻页
    tr = KeyedTransport({"a": {"content": [{"id": "a1"}], "last": False}})  # last=False
    ent, _ = _entity(tr)
    page = ent.material(material_ids=["a"], all=True)
    assert page.has_next is False  # 聚合页固定 has_next=False


# ---------- 互斥 / fail-loud ----------

def test_mutual_exclusion_raises():
    ent, _ = _entity(KeyedTransport())
    with pytest.raises(StockValidationError):
        ent.material(material_id="m1", material_ids=["m2"])


def test_undefined_placeholder_does_not_trigger_exclusion():
    # 单传 material_id，material_ids 经清洗为空（只含 "undefined"）→ 不误报互斥
    tr = KeyedTransport({"m1": {"content": [{"q": 1}], "last": True}})
    ent, _ = _entity(tr)
    page = ent.material(material_id="m1", material_ids=["undefined"])
    assert page.items == [{"q": 1}]


def test_material_view_fail_loud_when_no_material():
    ent, _ = _entity(KeyedTransport())
    with pytest.raises(StockValidationError):
        ent.material()  # 既无单值也无多值


def test_other_views_do_not_require_material():
    tr = KeyedTransport(default={"content": [{"x": 1}], "last": True})
    ent, _ = _entity(tr)
    page = ent.bin()  # bin 视图无 material 不报错
    assert page.items == [{"x": 1}]


# ---------- 单值 all 翻页 ----------

def test_single_all_paginates_with_last_and_page_size_200():
    tr = QueueTransport([
        FakeResponse(200, {"content": [{"i": 1}], "last": False}),
        FakeResponse(200, {"content": [{"i": 2}], "last": True}),
    ])
    ent, _ = _entity(tr)
    page = ent.bin(all=True)
    assert [it["i"] for it in page.items] == [1, 2]
    assert tr.params_seen[0]["size"] == "200"  # all 强制 page_size=200


def test_single_all_caps_at_max_items_and_marks_truncated():
    # 每页恒满（启发式 has_next 永真）→ 封顶早停
    pages = [FakeResponse(200, {"content": [{"i": k} for k in range(200)], "last": False}) for _ in range(10)]
    tr = QueueTransport(pages)
    ent, _ = _entity(tr)
    page = ent.bin(all=True, max_items=500)
    assert len(page.items) == 500
    assert page.truncated is True
    assert page.has_next is True
