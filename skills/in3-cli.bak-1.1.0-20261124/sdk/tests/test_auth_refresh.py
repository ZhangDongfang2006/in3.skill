"""auth.Session refresh-token 单测（#8 的可落地部分；后端实测支持 grant_type=refresh_token）。

password/refresh grant 都返 refresh_token（轮换）。401 时优先 refresh 静默刷新（不重发口令），
refresh 失败才回退重新换 token。
"""
from dataclasses import dataclass, field

import pytest

from in3_client.auth import AuthFailedError, Session
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
        self.calls.append({"params": params})
        return self.responses.pop(0)


_CRED = Credentials(
    api_host="https://apiv3.industics.com/service", tenant_domain="indx",
    username="corp:zhuzheng@indx", encrypted_password="AES==", alias="zhuzheng",
)


def _tok(access="a1", refresh="r1"):
    return {"access_token": access, "tenant_id": "99979", "tenant_domain": "indx",
            "user_id": "u-42", "refresh_token": refresh}


def test_token_captures_refresh_token():
    sess = Session(_CRED, transport=FakeTransport([FakeResponse(200, _tok(refresh="rTOK"))]))
    tok = sess.token()
    assert tok.refresh_token == "rTOK"


def test_refresh_uses_refresh_token_grant():
    tr = FakeTransport([FakeResponse(200, _tok("a1", "r1")), FakeResponse(200, _tok("a2", "r2"))])
    sess = Session(_CRED, transport=tr)
    sess.token()
    ok = sess.refresh()
    assert ok is True
    assert sess.token().access_token == "a2"      # 刷出新 access
    assert sess.token().refresh_token == "r2"      # refresh 轮换
    # 第二次调用走的是 refresh_token grant
    assert tr.calls[1]["params"]["grant_type"] == "refresh_token"
    assert tr.calls[1]["params"]["refresh_token"] == "r1"


def test_refresh_without_refresh_token_returns_false():
    # token 响应无 refresh_token → refresh() 返回 False（不炸）
    tr = FakeTransport([FakeResponse(200, {"access_token": "a", "tenant_id": "x", "tenant_domain": "indx", "user_id": "u"})])
    sess = Session(_CRED, transport=tr)
    sess.token()
    assert sess.refresh() is False


def test_refresh_failure_returns_false():
    tr = FakeTransport([FakeResponse(200, _tok()), FakeResponse(401, text="expired")])
    sess = Session(_CRED, transport=tr)
    sess.token()
    assert sess.refresh() is False  # refresh token 失效 → False，不抛


def test_refresh_non_json_returns_false():
    tr = FakeTransport([FakeResponse(200, _tok()), FakeResponse(200, content_type="text/html", text="<html>")])
    sess = Session(_CRED, transport=tr)
    sess.token()
    assert sess.refresh() is False
