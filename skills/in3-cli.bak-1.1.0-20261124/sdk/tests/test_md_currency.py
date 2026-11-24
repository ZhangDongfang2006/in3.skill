"""md.currency entity 单测：走 config→auth→GET mdm/currencies/page→envelope→pagination。

断言：URL 用 token 响应的 tenant_id 拼、分页参数 page(0基)/size、多页迭代取全、返回统一 Page。
md.currency 本片只原样穿过骨架，不做 156↔CNY 归一（那是后续片的 normalize_currency）。
"""
from dataclasses import dataclass, field

from in3_client.auth import Session
from in3_client.config import Credentials
from in3_client.envelope import Page
from in3_client.entities.md import CurrencyEntity
from in3_client.http import HttpClient


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
        self.calls.append({"method": method, "url": url, "headers": headers, "params": params})
        return self.responses.pop(0)


_CRED = Credentials(
    api_host="https://apiv3.industics.com/service",
    tenant_domain="indx",
    username="corp:zhuzheng@indx",
    encrypted_password="AESCIPHER==",
    alias="zhuzheng",
)
_TOKEN = {"access_token": "jwt", "tenant_id": "10030", "tenant_domain": "indx", "user_id": "u-42"}


def _entity(data_responses):
    sess = Session(_CRED, transport=FakeTransport([FakeResponse(200, _TOKEN)]))
    data_tr = FakeTransport(data_responses)
    http = HttpClient(sess, transport=data_tr)
    return CurrencyEntity(_CRED, sess, http), data_tr


def test_currency_list_builds_url_with_token_tenant_id():
    ent, tr = _entity([FakeResponse(200, {"content": [{"currency_code": "CNY"}], "last": True})])
    ent.list()
    assert tr.calls[0]["url"] == (
        "https://apiv3.industics.com/service/mom/md"
        "/v2/api/tenants/10030/mdm/currencies/page"
    )


def test_currency_list_sends_zero_based_page_and_size():
    ent, tr = _entity([FakeResponse(200, {"content": [{"currency_code": "CNY"}], "last": True})])
    ent.list(size=50)
    params = tr.calls[0]["params"]
    assert params["page"] == "0"
    assert params["size"] == "50"


def test_currency_list_returns_page_of_items():
    ent, tr = _entity([
        FakeResponse(200, {"content": [{"currency_code": "CNY", "iso_currency_no": "156"}], "last": True}),
    ])
    page = ent.list()
    assert isinstance(page, Page)
    assert page.items == [{"currency_code": "CNY", "iso_currency_no": "156"}]


def test_currency_list_paginates_all_via_last_flag():
    ent, tr = _entity([
        FakeResponse(200, {"content": [{"currency_code": "CNY"}], "last": False}),
        FakeResponse(200, {"content": [{"currency_code": "USD"}], "last": True}),
    ])
    page = ent.list(size=1)
    assert [it["currency_code"] for it in page.items] == ["CNY", "USD"]
    # 翻了两页，page 参数递增
    assert tr.calls[0]["params"]["page"] == "0"
    assert tr.calls[1]["params"]["page"] == "1"


def test_currency_list_single_page_when_all_false():
    ent, tr = _entity([
        FakeResponse(200, {"content": [{"currency_code": "CNY"}], "last": False}),
    ])
    page = ent.list(all=False)
    assert len(tr.calls) == 1
    assert page.items == [{"currency_code": "CNY"}]


def test_currency_list_passes_keyword_filter():
    ent, tr = _entity([FakeResponse(200, {"content": [], "last": True})])
    ent.list(keyword="人民币")
    assert tr.calls[0]["params"]["keyword"] == "人民币"
