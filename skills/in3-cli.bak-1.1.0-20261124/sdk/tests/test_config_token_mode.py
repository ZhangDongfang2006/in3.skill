"""token-mode 凭证单测：login --paste-token 写的 credentials.json（auth_mode=token，存 Bearer），
load_credentials 识别为 token 模式（不要求 encrypted_password），IN3(tenant=) 自动走 from_token。
"""
import json
from dataclasses import dataclass, field

import in3_client
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
