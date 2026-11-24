"""token-paste 入口单测（#8 兜底）：用浏览器/devtools 抓到的现成 token 直接构造 Session/IN3，
不走 password-grant——绕开被封的 authorize 端点，支持 SSO/MFA 经 SPA 登录后捕获 token 复用。
"""
from dataclasses import dataclass, field

import in3_client
from in3_client.auth import Session
from in3_client.config import Credentials


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
        self.calls.append({"url": url, "headers": headers, "params": params})
        return self.responses.pop(0)


_CRED = Credentials(
    api_host="https://apiv3.industics.com/service", tenant_domain="indx",
    username="", encrypted_password="", alias="captured",
)


def test_session_from_token_sets_headers_without_password_grant():
    tr = FakeTransport([])  # 不应发任何 token 请求
    sess = Session.from_token(_CRED, access_token="AT", tenant_id="99979",
                              tenant_domain="indx", user_id="u9", refresh_token="RT", transport=tr)
    h = sess.headers()
    assert h["Authorization"] == "Bearer AT"
    assert h["T-CODE"] == "indx" and h["X-Operator-ID"] == "u9"
    assert len(tr.calls) == 0  # 现成 token，零 token 交换


def test_session_from_token_can_refresh():
    tr = FakeTransport([FakeResponse(200, {"access_token": "AT2", "tenant_id": "99979",
                                           "tenant_domain": "indx", "user_id": "u9", "refresh_token": "RT2"})])
    sess = Session.from_token(_CRED, access_token="AT", refresh_token="RT", transport=tr)
    assert sess.refresh() is True
    assert sess.token().access_token == "AT2"


def test_in3_from_token_runs_query_with_pasted_token():
    data = FakeTransport([FakeResponse(200, {"content": [{"currency_code": "CNY"}], "last": True})])
    in3 = in3_client.IN3.from_token(
        api_host="https://apiv3.industics.com/service", access_token="AT",
        tenant_id="99979", tenant_domain="indx", user_id="u9", refresh_token="RT",
        transport=data,
    )
    page = in3.md.currency.list()
    assert [c["currency_code"] for c in page.items] == ["CNY"]
    # 数据请求带的是粘贴的 token
    assert data.calls[0]["headers"]["Authorization"] == "Bearer AT"
