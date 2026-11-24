"""config 单测：只读解析 dispatcher 的 workspace / current-tenant / credentials.json。

用隔离 tmp workspace（不碰真实凭证），照 dispatcher 的目录布局：
  <ws>/config/current-tenant.json        → {"tenant": alias}
  <ws>/config/tenants/<alias>/credentials.json
全局 pointer: <pointer>/workspace.json    → {"path": "<ws>"}
"""
import json

import pytest

from in3_client.config import (
    Credentials,
    MissingCredentialsError,
    load_credentials,
    resolve_current_tenant,
    resolve_workspace,
)

_FULL_CRED = {
    "api_host": "https://apiv3.industics.com/service",
    "env_label": "prod",
    "tenant_domain": "indx",
    "username": "corp:zhuzheng@indx",
    "encrypted_password": "AESCIPHERSTRING==",
    "modules_onboarded": ["mm", "wm", "md", "sd"],
    "last_login_at": "2026-05-25T12:40:15+00:00",
}


def _make_ws(tmp_path, alias="zhuzheng", cred=None, current=True):
    ws = tmp_path / "in3-workspace"
    cfg = ws / "config"
    (cfg / "tenants" / alias).mkdir(parents=True)
    if cred is not None:
        (cfg / "tenants" / alias / "credentials.json").write_text(json.dumps(cred))
    if current:
        (cfg / "current-tenant.json").write_text(json.dumps({"tenant": alias}))
    return ws


def test_loads_full_credentials(tmp_path):
    ws = _make_ws(tmp_path, cred=_FULL_CRED)
    creds = load_credentials(workspace=ws, alias="zhuzheng")
    assert isinstance(creds, Credentials)
    assert creds.api_host == "https://apiv3.industics.com/service"
    assert creds.tenant_domain == "indx"
    assert creds.username == "corp:zhuzheng@indx"
    assert creds.encrypted_password == "AESCIPHERSTRING=="
    assert creds.alias == "zhuzheng"


def test_base_url_appends_mom_mod_suffix(tmp_path):
    ws = _make_ws(tmp_path, cred=_FULL_CRED)
    creds = load_credentials(workspace=ws, alias="zhuzheng")
    assert creds.base_url("md") == "https://apiv3.industics.com/service/mom/md"
    assert creds.base_url("mm") == "https://apiv3.industics.com/service/mom/mm"


def test_uaas_host_equals_api_host(tmp_path):
    ws = _make_ws(tmp_path, cred=_FULL_CRED)
    creds = load_credentials(workspace=ws, alias="zhuzheng")
    assert creds.uaas_host == "https://apiv3.industics.com/service"


def test_alias_defaults_to_current_tenant(tmp_path):
    ws = _make_ws(tmp_path, cred=_FULL_CRED)
    creds = load_credentials(workspace=ws)  # 不传 alias → 从 current-tenant.json 取
    assert creds.alias == "zhuzheng"


def test_resolve_current_tenant(tmp_path):
    ws = _make_ws(tmp_path, cred=_FULL_CRED)
    assert resolve_current_tenant(ws) == "zhuzheng"


def test_resolve_workspace_from_pointer(tmp_path):
    ws = _make_ws(tmp_path, cred=_FULL_CRED)
    pointer_dir = tmp_path / "pointer"
    pointer_dir.mkdir()
    (pointer_dir / "workspace.json").write_text(json.dumps({"path": str(ws)}))
    assert resolve_workspace(pointer_dir / "workspace.json") == ws


def test_missing_credentials_file_fails_loud(tmp_path):
    ws = _make_ws(tmp_path, cred=None)  # 目录在但无 credentials.json
    with pytest.raises(MissingCredentialsError):
        load_credentials(workspace=ws, alias="zhuzheng")


def test_missing_required_field_fails_loud(tmp_path):
    bad = dict(_FULL_CRED)
    del bad["encrypted_password"]
    ws = _make_ws(tmp_path, cred=bad)
    with pytest.raises(MissingCredentialsError) as exc:
        load_credentials(workspace=ws, alias="zhuzheng")
    assert "encrypted_password" in str(exc.value)


def test_no_current_tenant_fails_loud(tmp_path):
    ws = _make_ws(tmp_path, cred=_FULL_CRED, current=False)
    with pytest.raises(MissingCredentialsError):
        load_credentials(workspace=ws)  # 没 current-tenant.json 又没传 alias
