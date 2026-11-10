"""浏览器 OAuth（Authorization Code + PKCE + loopback）客户端逻辑单测。

可纯函数测的部分（PKCE/authorize URL/callback 解析/code 交换）全覆盖；真实 socket/浏览器属
集成（HITL）不在此。**运行时门禁**：当前后端 /uaas/oauth/authorize 一律 401（M0.5 实证），
browser_login 探测不可用即抛 BrowserOAuthUnavailable 降级——本测锁住该行为。
"""
import base64
import hashlib

import pytest

from in3_client.config import Credentials
from in3_client.oauth import (
    BrowserOAuthUnavailable,
    authorize_available,
    browser_login,
    build_authorize_url,
    exchange_code,
    generate_pkce,
    parse_callback,
)


class FakeResponse:
    def __init__(self, status_code, _json=None, content_type="application/json", text=""):
        self.status_code = status_code
        self._json = _json
        self._ct = content_type
        self.text = text

    @property
    def headers(self):
        return {"content-type": self._ct}

    def json(self):
        return self._json


_CRED = Credentials(
    api_host="https://apiv3.industics.com/service", tenant_domain="indx",
    username="corp:zhuzheng@indx", encrypted_password="AES==", alias="zhuzheng",
)


# ---------- PKCE ----------

def test_pkce_verifier_length_and_challenge_is_s256():
    verifier, challenge = generate_pkce()
    assert 43 <= len(verifier) <= 128
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert challenge == expected
    assert "=" not in challenge  # base64url 无填充


def test_pkce_pairs_are_random():
    assert generate_pkce()[0] != generate_pkce()[0]


# ---------- authorize URL ----------

def test_authorize_url_has_all_params():
    url = build_authorize_url("https://h/service", "cid", "http://127.0.0.1:5/callback", "CH", "ST")
    assert url.startswith("https://h/service/uaas/oauth/authorize?")
    for frag in ["response_type=code", "client_id=cid", "code_challenge=CH",
                 "code_challenge_method=S256", "state=ST", "callback"]:
        assert frag in url


# ---------- callback 解析 ----------

def test_parse_callback_extracts_code_and_state():
    code, state, err = parse_callback("code=abc&state=xyz")
    assert code == "abc" and state == "xyz" and err is None


def test_parse_callback_surfaces_error():
    code, state, err = parse_callback("error=access_denied&error_description=no")
    assert err == "access_denied" and code is None


# ---------- 运行时门禁 ----------

def test_authorize_available_false_on_401_problem_json():
    # 当前后端真实行为：401 + problem+json
    tr = lambda *a, **k: FakeResponse(401, content_type="application/problem+json", text="服务异常")
    assert authorize_available(tr, _CRED, "cid") is False


def test_authorize_available_true_on_login_page():
    tr = lambda *a, **k: FakeResponse(200, content_type="text/html", text="<form>login</form>")
    assert authorize_available(tr, _CRED, "cid") is True


def test_browser_login_raises_unavailable_when_gated():
    tr = lambda *a, **k: FakeResponse(401, content_type="application/problem+json")
    with pytest.raises(BrowserOAuthUnavailable):
        browser_login(_CRED, transport=tr, open_browser=False)


# ---------- code 交换 ----------

def test_exchange_code_builds_request_and_returns_token():
    calls = []

    def tr(method, url, headers=None, params=None, **kw):
        calls.append(params)
        return FakeResponse(200, {"access_token": "AT", "refresh_token": "RT",
                                  "tenant_id": "99979", "tenant_domain": "indx", "user_id": "u"})
    tok = exchange_code(tr, _CRED, code="CODE", verifier="VER",
                        redirect_uri="http://127.0.0.1:5/callback", client_id="cid", client_secret="sec")
    assert tok.access_token == "AT" and tok.refresh_token == "RT"
    p = calls[0]
    assert p["grant_type"] == "authorization_code"
    assert p["code"] == "CODE" and p["code_verifier"] == "VER"
    assert p["redirect_uri"] == "http://127.0.0.1:5/callback"  # 与授权请求逐字一致


def test_exchange_code_non_json_is_auth_failure():
    from in3_client.auth import AuthFailedError
    tr = lambda *a, **k: FakeResponse(200, content_type="text/html", text="<html>")
    with pytest.raises(AuthFailedError):
        exchange_code(tr, _CRED, "c", "v", "http://127.0.0.1:5/callback", "cid", "sec")
