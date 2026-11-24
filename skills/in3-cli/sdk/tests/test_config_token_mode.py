"""token-mode 凭证单测：login --paste-token 写的 credentials.json（auth_mode=token，存 Bearer），
load_credentials 识别为 token 模式（不要求 encrypted_password），IN3(tenant=) 自动走 from_token。
"""
import json
import os
from dataclasses import dataclass, field

import in3_client
import pytest
from in3_client.auth import AuthFailedError
from in3_client.config import MissingCredentialsError, load_credentials


@dataclass
class FakeResponse:
    status_code: int
    _json: object = None
    content_type: str = "application/json"

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
        self.calls.append({"headers": headers, "params": params})
        return self.responses.pop(0)


_TOKEN_CRED = {
    "api_host": "https://apiv3.industics.com/service",
    "env_label": "prod",
    "tenant_domain": "indx",
    "username": "corp:shenchenjian@indx",
    "auth_mode": "token",
    "access_token": "JWT-AT",
    "refresh_token": "JWT-RT",
    "tenant_id": "99979",
    "user_id": "u-98a",
    "last_login_at": "2026-06-02T10:00:00+00:00",
}


def _make_ws(tmp_path, cred, alias="shenchenjian"):
    ws = tmp_path / "in3-workspace"
    (ws / "config" / "tenants" / alias).mkdir(parents=True)
    (ws / "config" / "tenants" / alias / "credentials.json").write_text(json.dumps(cred))
    (ws / "config" / "current-tenant.json").write_text(json.dumps({"tenant": alias}))
    return ws


def test_token_mode_loads_without_encrypted_password(tmp_path):
    ws = _make_ws(tmp_path, _TOKEN_CRED)
    creds = load_credentials(workspace=ws, alias="shenchenjian")
    assert creds.auth_mode == "token"
    assert creds.access_token == "JWT-AT"
    assert creds.refresh_token == "JWT-RT"
    assert creds.tenant_id == "99979"
    assert creds.user_id == "u-98a"


def test_token_mode_missing_access_token_fails_loud(tmp_path):
    bad = dict(_TOKEN_CRED)
    del bad["access_token"]
    ws = _make_ws(tmp_path, bad)
    with __import__("pytest").raises(MissingCredentialsError):
        load_credentials(workspace=ws, alias="shenchenjian")


def test_in3_uses_pasted_token_no_password_grant(tmp_path):
    ws = _make_ws(tmp_path, _TOKEN_CRED)
    data = FakeTransport([FakeResponse(200, {"content": [{"currency_code": "CNY"}], "last": True})])
    in3 = in3_client.IN3(tenant="shenchenjian", workspace=ws, transport=data)
    page = in3.md.currency.list()
    assert page.items == [{"currency_code": "CNY"}]
    # 用的是粘贴的 token，没换过 token
    assert data.calls[0]["headers"]["Authorization"] == "Bearer JWT-AT"
    assert data.calls[0]["headers"]["X-Operator-ID"] == "u-98a"


def test_rotated_tokens_are_saved_and_reused_by_next_client(tmp_path):
    ws = _make_ws(tmp_path, _TOKEN_CRED)
    path = ws / "config/tenants/shenchenjian/credentials.json"
    auth = FakeTransport([FakeResponse(200, {"access_token": "AT2", "refresh_token": "RT2"})])
    data = FakeTransport([FakeResponse(401), FakeResponse(200, {"content": [], "last": True})])
    client = in3_client.IN3(workspace=ws, auth_transport=auth, transport=data)
    client.md.currency.list()
    stored = json.loads(path.read_text())
    assert stored["access_token"] == "AT2" and stored["refresh_token"] == "RT2"
    assert stored["user_id"] == _TOKEN_CRED["user_id"]
    assert stored["last_login_at"] == _TOKEN_CRED["last_login_at"]
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600
    next_client = in3_client.IN3(workspace=ws, auth_transport=FakeTransport([]))
    assert next_client.session.headers()["Authorization"] == "Bearer AT2"


def test_stale_client_reuses_refresh_completed_by_another_client(tmp_path):
    ws = _make_ws(tmp_path, _TOKEN_CRED)
    auth = FakeTransport([FakeResponse(200, {"access_token": "AT2", "refresh_token": "RT2"})])
    first = in3_client.IN3(workspace=ws, auth_transport=auth)
    second = in3_client.IN3(workspace=ws, auth_transport=FakeTransport([]))
    assert first.session.refresh()
    assert second.session.refresh()
    assert second.session.token().access_token == "AT2"
    assert second.session.token().refresh_token == "RT2"
    assert len(auth.calls) == 1


def test_refresh_does_not_overwrite_a_new_login(tmp_path):
    ws = _make_ws(tmp_path, _TOKEN_CRED)
    path = ws / "config/tenants/shenchenjian/credentials.json"

    def relogin(*args, **kwargs):
        path.write_text(json.dumps(dict(_TOKEN_CRED, username="corp:other@indx", access_token="OTHER")))
        return FakeResponse(200, {"access_token": "AT2", "refresh_token": "RT2"})

    client = in3_client.IN3(workspace=ws, auth_transport=relogin)
    with pytest.raises(AuthFailedError):
        client.session.refresh()
    assert json.loads(path.read_text())["access_token"] == "OTHER"


def test_failed_refresh_leaves_stored_credentials_unchanged(tmp_path):
    ws = _make_ws(tmp_path, _TOKEN_CRED)
    path = ws / "config/tenants/shenchenjian/credentials.json"
    before = path.read_bytes()
    client = in3_client.IN3(workspace=ws, auth_transport=FakeTransport([FakeResponse(400)]))
    assert client.session.refresh() is False
    assert path.read_bytes() == before
