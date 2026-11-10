"""http.HttpClient.get_page 单测：三头数据请求 + 401 重试一次 + 非 JSON 200 判失败 + 归一。

参照真 CLI src/http/client.ts 的边界：http 负责数据请求 + 401-重试一次；token 生命周期在 auth。
"""
from dataclasses import dataclass, field

import pytest

from in3_client.auth import AuthFailedError, Session
from in3_client.config import Credentials
from in3_client.envelope import Page
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
_TOKEN_BODY = {"access_token": "jwt-1", "tenant_id": "10030", "tenant_domain": "indx", "user_id": "u-42"}
_TOKEN_BODY2 = {"access_token": "jwt-2", "tenant_id": "10030", "tenant_domain": "indx", "user_id": "u-42"}


def _session(token_bodies=None):
    bodies = token_bodies or [_TOKEN_BODY]
    return Session(_CRED, transport=FakeTransport([FakeResponse(200, b) for b in bodies]))


def test_get_page_sends_three_auth_headers_and_normalizes():
    sess = _session()
    data_tr = FakeTransport([FakeResponse(200, {"content": [{"a": 1}], "totalElements": 1, "last": True})])
    http = HttpClient(sess, transport=data_tr)
    page = http.get_page("https://h/p", {"page": "0", "size": "20"}, requested_size=20)
    assert isinstance(page, Page)
    assert page.items == [{"a": 1}]
    assert page.total == 1
    assert page.has_next is False
    h = data_tr.calls[0]["headers"]
    assert h["Authorization"] == "Bearer jwt-1"
    assert h["T-CODE"] == "indx"
    assert h["X-Operator-ID"] == "u-42"


def test_get_page_retries_once_on_401_then_succeeds():
    sess = _session([_TOKEN_BODY, _TOKEN_BODY2])  # 初次 + 刷新
    data_tr = FakeTransport([
        FakeResponse(401, text="expired"),
        FakeResponse(200, {"content": [{"ok": 1}], "last": True}),
    ])
    http = HttpClient(sess, transport=data_tr)
    page = http.get_page("https://h/p", requested_size=20)
    assert page.items == [{"ok": 1}]
    # 重试用了刷新后的 token
    assert data_tr.calls[1]["headers"]["Authorization"] == "Bearer jwt-2"
    assert len(data_tr.calls) == 2


def test_get_page_second_401_raises():
    sess = _session([_TOKEN_BODY, _TOKEN_BODY2])
    data_tr = FakeTransport([FakeResponse(401), FakeResponse(401)])
    http = HttpClient(sess, transport=data_tr)
    with pytest.raises(Exception):
        http.get_page("https://h/p", requested_size=20)
    assert len(data_tr.calls) == 2  # 只重试一次


def test_get_page_200_non_json_is_auth_failure():
    sess = _session()
    data_tr = FakeTransport([FakeResponse(200, content_type="text/html", text="<html>login</html>")])
    http = HttpClient(sess, transport=data_tr)
    with pytest.raises(AuthFailedError):
        http.get_page("https://h/p", requested_size=20)


def test_get_page_total_below_len_becomes_none():
    sess = _session()
    # Spring Slice: total=0 但 items 有 2 条 → envelope 置 None（¥111K 防御）
    data_tr = FakeTransport([FakeResponse(200, {"items": [{"x": 1}, {"x": 2}], "total": 0})])
    http = HttpClient(sess, transport=data_tr)
    page = http.get_page("https://h/p", requested_size=20)
    assert page.items == [{"x": 1}, {"x": 2}]
    assert page.total is None
