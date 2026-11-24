"""auth.Session 单测：password-grant token 交换 + 三头组装。

注入 FakeTransport（不依赖 requests）。token 端点是 **GET + query params**（与真 CLI
src/auth/index.ts 一致，非 POST）。password 直发 credentials.json 里已 AES 加密的串。
"""
from dataclasses import dataclass, field

import pytest

from in3_client.auth import (
    DEFAULT_CLIENT_ID,
    DEFAULT_CLIENT_SECRET,
    AuthFailedError,
    Session,
)
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
    """按队列返回响应，记录每次 (method, url, headers, params)。"""
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

_TOKEN_BODY = {
    "access_token": "jwt-abc",
    "tenant_id": "10030",
    "tenant_domain": "indx",
    "user_id": "u-42",
}


def test_token_exchange_is_get_to_uaas_endpoint():
    tr = FakeTransport([FakeResponse(200, _TOKEN_BODY)])
    sess = Session(_CRED, transport=tr)
    tok = sess.token()
    assert tok.access_token == "jwt-abc"
    assert tok.user_id == "u-42"
    assert tok.tenant_domain == "indx"
    call = tr.calls[0]
    assert call["method"] == "GET"
    assert call["url"] == "https://apiv3.industics.com/service/uaas/oauth/token"


def test_token_request_carries_password_grant_params_directly():
    tr = FakeTransport([FakeResponse(200, _TOKEN_BODY)])
    sess = Session(_CRED, transport=tr)
    sess.token()
    params = tr.calls[0]["params"]
    assert params["grant_type"] == "password"
    assert params["username"] == "corp:zhuzheng@indx"
    # 直发 AES 串，SDK 不解密
    assert params["password"] == "AESCIPHER=="
    assert params["client_id"] == DEFAULT_CLIENT_ID
    assert params["client_secret"] == DEFAULT_CLIENT_SECRET


def test_client_id_secret_are_spa_shared_defaults():
    assert DEFAULT_CLIENT_ID == "8b80bf13ab4611ea8356000c29ba7340"
    assert DEFAULT_CLIENT_SECRET == "d6223c6102ec47dcb8a9797619dde758"


def test_headers_assemble_three_auth_headers():
    tr = FakeTransport([FakeResponse(200, _TOKEN_BODY)])
    sess = Session(_CRED, transport=tr)
    h = sess.headers()
    assert h["Authorization"] == "Bearer jwt-abc"
    assert h["T-CODE"] == "indx"            # 来自 token 响应 tenant_domain
    assert h["X-Operator-ID"] == "u-42"     # 来自 token 响应 user_id


def test_token_is_cached_across_calls():
    tr = FakeTransport([FakeResponse(200, _TOKEN_BODY)])
    sess = Session(_CRED, transport=tr)
    sess.token()
    sess.token()
    sess.headers()
    assert len(tr.calls) == 1  # 只换一次 token


def test_clear_forces_refetch():
    tr = FakeTransport([FakeResponse(200, _TOKEN_BODY), FakeResponse(200, _TOKEN_BODY)])
    sess = Session(_CRED, transport=tr)
    sess.token()
    sess.clear()
    sess.token()
    assert len(tr.calls) == 2


def test_token_endpoint_non_200_raises_with_status():
    tr = FakeTransport([FakeResponse(403, text="forbidden")])
    sess = Session(_CRED, transport=tr)
    with pytest.raises(AuthFailedError) as exc:
        sess.token()
    assert "403" in str(exc.value)


def test_token_endpoint_200_non_json_is_auth_failure():
    # 网关返回 200 + HTML 登录页 → 认证失败，绝不当作空结果。
    tr = FakeTransport([FakeResponse(200, content_type="text/html", text="<html>login</html>")])
    sess = Session(_CRED, transport=tr)
    with pytest.raises(AuthFailedError):
        sess.token()


def test_token_endpoint_200_missing_access_token_is_auth_failure():
    tr = FakeTransport([FakeResponse(200, {"tenant_id": "x"})])
    sess = Session(_CRED, transport=tr)
    with pytest.raises(AuthFailedError):
        sess.token()


def test_client_id_secret_overridable():
    tr = FakeTransport([FakeResponse(200, _TOKEN_BODY)])
    sess = Session(_CRED, transport=tr, client_id="cid2", client_secret="sec2")
    sess.token()
    params = tr.calls[0]["params"]
    assert params["client_id"] == "cid2"
    assert params["client_secret"] == "sec2"
