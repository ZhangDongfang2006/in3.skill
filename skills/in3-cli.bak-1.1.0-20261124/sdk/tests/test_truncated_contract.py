"""truncated 契约统一回归（issue #9 AC「truncated 封顶早停标记可见」）。

base.PagedEntity._list / mm.PurchaseOrderEntity._fetch_list / wm.AvailableStockEntity.list
三处在 all=True 时调 pagination.iterate_all 聚合全量；修前只把 agg.truncated 写进 has_next、
而 Page.truncated 恒 False —— 调用方看不到「封顶早停、结果不完整」。本测用 monkeypatch 把
iterate_all 换成「已封顶」桩，精确断言 truncated 透到 Page.truncated（而非只塞 has_next）。
wm.StockEntity._iterate_all 自带正确实现，单列一条回归守门。
"""
from dataclasses import dataclass, field

from in3_client.auth import Session
from in3_client.config import Credentials
from in3_client.http import HttpClient
from in3_client.pagination import AllPages
from in3_client.entities import base as base_mod
from in3_client.entities import mm as mm_mod
from in3_client.entities import wm as wm_mod
from in3_client.entities.md import MaterialEntity
from in3_client.entities.mm import PurchaseOrderEntity
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

    def __call__(self, method, url, headers=None, params=None, **kw):
        self.calls.append({"method": method, "url": url, "params": params})
        return self.responses.pop(0)


_CRED = Credentials(
    api_host="https://apiv3.industics.com/service",
    tenant_domain="indx",
    username="corp:zhuzheng@indx",
    encrypted_password="AESCIPHER==",
    alias="zhuzheng",
)
_TOKEN = {"access_token": "jwt", "tenant_id": "10030", "tenant_domain": "indx", "user_id": "u-42"}


def _session():
    return Session(_CRED, transport=FakeTransport([FakeResponse(200, _TOKEN)]))


def _http(sess):
    # iterate_all 被 monkeypatch 后不会真翻页，data transport 不被消费——给一条兜底即可。
    return HttpClient(sess, transport=FakeTransport([FakeResponse(200, {"content": [{"id": "x"}], "last": False})]))


def _capped(*_a, **_k):
    """模拟 iterate_all 封顶早停：truncated=True。"""
    return AllPages(items=[{"id": "x"}], pages_fetched=1000, truncated=True)


def _exhausted(*_a, **_k):
    """模拟 iterate_all 正常翻完：truncated=False。"""
    return AllPages(items=[{"id": "x"}], pages_fetched=2, truncated=False)


def test_base_list_propagates_truncated_to_page(monkeypatch):
    monkeypatch.setattr(base_mod, "iterate_all", _capped)
    sess = _session()
    page = MaterialEntity(_CRED, sess, _http(sess)).list(all=True)
    assert page.truncated is True      # 修前恒 False —— 调用方看不到不完整
    assert page.has_next is True        # 还有没翻完的页


def test_mm_po_list_propagates_truncated(monkeypatch):
    monkeypatch.setattr(mm_mod, "iterate_all", _capped)
    sess = _session()
    page = PurchaseOrderEntity(_CRED, sess, _http(sess)).list(all=True)
    assert page.truncated is True
    assert page.has_next is True


def test_wm_available_stock_list_propagates_truncated(monkeypatch):
    monkeypatch.setattr(wm_mod, "iterate_all", _capped)
    sess = _session()
    page = AvailableStockEntity(_CRED, sess, _http(sess)).list(all=True)
    assert page.truncated is True
    assert page.has_next is True


def test_base_list_not_truncated_when_exhausted(monkeypatch):
    monkeypatch.setattr(base_mod, "iterate_all", _exhausted)
    sess = _session()
    page = MaterialEntity(_CRED, sess, _http(sess)).list(all=True)
    assert page.truncated is False
    assert page.has_next is False       # 翻完了，无下页


def test_wm_stock_iterate_all_already_marks_truncated():
    """StockEntity._iterate_all 自带正确 truncated（封顶 max_items），守门防回归。"""
    sess = _session()
    # 每页满 200 条 → has_next 启发式恒 True；max_items=3 → 第一页就超、截断标 truncated。
    full = {"content": [{"id": i} for i in range(200)], "last": False}
    http = HttpClient(sess, transport=FakeTransport([FakeResponse(200, full)]))
    from in3_client.entities.wm import StockEntity
    page = StockEntity(_CRED, sess, http).material(material_id="m1", all=True, max_items=3)
    assert page.truncated is True
    assert len(page.items) == 3
