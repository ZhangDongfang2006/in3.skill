"""token-paste 入口单测（#8 兜底）：用浏览器/devtools 抓到的现成 token 直接构造 Session/IN3，
不走 password-grant——绕开被封的 authorize 端点，支持 SSO/MFA 经 SPA 登录后捕获 token 复用。
"""
from dataclasses import dataclass, field

import in3_client
import pytest
from in3_client.auth import AuthFailedError, Session, TokenExpiredError
from in3_client.config import Credentials
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


@pytest.mark.parametrize("refresh", ["", "RT"])
def test_rejected_token_never_falls_back_to_password_even_with_stored_password(refresh):
    cred = Credentials("https://h/service", "indx", "corp:u@indx", "OLD-AES", "test")
    auth = FakeTransport([FakeResponse(400), FakeResponse(400)])
    data = FakeTransport([FakeResponse(401), FakeResponse(401)])
    sess = Session.from_token(cred, "AT", refresh_token=refresh, transport=auth)
    http = HttpClient(sess, transport=data)
    for _ in range(2):
        with pytest.raises(TokenExpiredError):
            http.get_json("https://h/data")
    assert all(c["params"]["grant_type"] == "refresh_token" for c in auth.calls)
    assert len(auth.calls) == bool(refresh)
    assert len(data.calls) == 1


def test_cleared_token_session_does_not_request_password():
    auth = FakeTransport([FakeResponse(400)])
    sess = Session.from_token(_CRED, "AT", transport=auth)
    sess.clear()
    with pytest.raises(AuthFailedError):
        sess.token()
    assert auth.calls == []


@pytest.mark.parametrize("username,password", [("", "AES"), ("corp:u@indx", ""), ("corp:u@indx", " ")])
def test_password_grant_requires_nonempty_username_and_password(username, password):
    cred = Credentials("https://h", "indx", username, password, "test")
    auth = FakeTransport([FakeResponse(400)])
    with pytest.raises(AuthFailedError):
        Session(cred, transport=auth).token()
    assert auth.calls == []


def test_refresh_keeps_identity_and_unrotated_refresh_token():
    auth = FakeTransport([FakeResponse(200, {"access_token": "AT2"})])
    sess = Session.from_token(_CRED, "AT", refresh_token="RT", tenant_id="99979",
                              user_id="u9", transport=auth)
    assert sess.refresh()
    assert sess.token().tenant_id == "99979"
    assert sess.token().user_id == "u9"
    assert sess.token().refresh_token == "RT"


def test_refreshed_token_rejected_again_stops_without_password_or_more_refreshes():
    auth = FakeTransport([FakeResponse(200, {"access_token": "AT2", "refresh_token": "RT2"})])
    data = FakeTransport([FakeResponse(401), FakeResponse(401)])
    sess = Session.from_token(_CRED, "AT", refresh_token="RT", transport=auth)
    http = HttpClient(sess, transport=data)
    for _ in range(2):
        with pytest.raises(TokenExpiredError):
            http.get_json("https://h/data")
    assert len(auth.calls) == 1 and len(data.calls) == 2


def test_refresh_rejects_changed_tenant_identity():
    auth = FakeTransport([FakeResponse(200, {"access_token": "AT2", "tenant_id": "other"})])
    sess = Session.from_token(_CRED, "AT", refresh_token="RT", tenant_id="99979", transport=auth)
    assert sess.refresh() is False
    assert sess.token().access_token == "AT"


@pytest.mark.parametrize("body", [["bad"], "not-a-token-response", {"error": "invalid_grant"}])
def test_malformed_refresh_response_does_not_trigger_password_grant(body):
    auth = FakeTransport([FakeResponse(200, body)])
    data = FakeTransport([FakeResponse(401)])
    sess = Session.from_token(_CRED, "AT", refresh_token="RT", transport=auth)
    with pytest.raises(TokenExpiredError):
        HttpClient(sess, transport=data).get_json("https://h/data")
    assert len(auth.calls) == 1 and auth.calls[0]["params"]["grant_type"] == "refresh_token"


def test_auth_errors_do_not_expose_response_or_request_secrets():
    secret = "sensitive-fixture-value"
    for response in (FakeResponse(400, text=secret), FakeResponse(200, {"refresh_token": secret})):
        with pytest.raises(AuthFailedError) as error:
            Session(Credentials("https://h", "indx", "u", secret, "test"),
                    transport=FakeTransport([response])).token()
        assert secret not in str(error.value)

    def network_failure(*args, **kwargs):
        raise OSError(f"URL contains password={secret}")

    with pytest.raises(AuthFailedError) as error:
        Session.from_token(_CRED, "AT", refresh_token=secret, transport=network_failure).refresh()
    assert secret not in str(error.value)


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
