"""BDD step defs 共享支撑：FakeTransport 桩 + Session/IN3 构造 + 录制 fixture 加载。

不碰真后端/CLI —— token 端点与数据端点都走注入的 FakeTransport，照 tests/test_auth.py /
test_md_currency.py 的 prior art。集中在此供 auth/md_currency/poc 三个 step 文件复用。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from in3_client.auth import Session
from in3_client.config import Credentials
from in3_client.facade import IN3
from in3_client.http import HttpClient

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

CRED = Credentials(
    api_host="https://apiv3.industics.com/service",
    tenant_domain="indx",
    username="corp:zhuzheng@indx",
    encrypted_password="AESCIPHER==",
    alias="zhuzheng",
)
TOKEN = {"access_token": "jwt-abc", "tenant_id": "10030", "tenant_domain": "indx", "user_id": "u-42"}


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
    """按队列返回响应，记录每次 (method, url, headers, params, json)。"""
    responses: list
    calls: list = field(default_factory=list)

    def __call__(self, method, url, headers=None, params=None, **kw):
        self.calls.append({"method": method, "url": url, "headers": headers,
                           "params": params, "json": kw.get("json")})
        return self.responses.pop(0)


def load_fixture(name: str):
    return json.loads((_FIXTURES / name).read_text())


def make_session(token_responses=None) -> Session:
    return Session(CRED, transport=FakeTransport(token_responses or [FakeResponse(200, dict(TOKEN))]))


def make_http(data_responses, token_responses=None):
    """返回 (HttpClient, data_transport, session) —— 给 auth/http 层 step 直接驱动。"""
    sess = make_session(token_responses)
    data_tr = FakeTransport(list(data_responses))
    return HttpClient(sess, transport=data_tr), data_tr, sess


def make_in3(data_responses, token_responses=None):
    """返回 (IN3, data_transport, auth_transport) —— 注入假 transport，不碰真后端。"""
    auth_tr = FakeTransport(token_responses or [FakeResponse(200, dict(TOKEN))])
    data_tr = FakeTransport(list(data_responses))
    in3 = IN3(cred=CRED, auth_transport=auth_tr, transport=data_tr)
    return in3, data_tr, auth_tr
