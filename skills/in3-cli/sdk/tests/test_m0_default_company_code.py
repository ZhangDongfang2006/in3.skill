"""M0 基座②单测：Credentials.default_company_code_id —— fn 双轨 fncc header 默认来源。

照 test_config.py 的隔离 tmp workspace 模式。覆盖 AC：
- Credentials 新增可选 default_company_code_id 字段。
- load_credentials 解析它；凭证文件有该字段 → 正确读出。
- 凭证文件缺该字段 → None 而非报错（旧凭证向后兼容）。
"""
import json

from in3_client.config import Credentials, load_credentials

_BASE_CRED = {
    "api_host": "https://apiv3.industics.com/service",
    "env_label": "prod",
    "tenant_domain": "indx",
    "username": "corp:zhuzheng@indx",
    "encrypted_password": "AESCIPHERSTRING==",
    "modules_onboarded": ["mm", "fn"],
}


def _make_ws(tmp_path, alias="zhuzheng", cred=None):
    ws = tmp_path / "in3-workspace"
    cfg = ws / "config"
    (cfg / "tenants" / alias).mkdir(parents=True)
    (cfg / "tenants" / alias / "credentials.json").write_text(json.dumps(cred))
    (cfg / "current-tenant.json").write_text(json.dumps({"tenant": alias}))
    return ws


def test_default_company_code_id_field_exists_and_defaults_none():
    """dataclass 字段默认 None（不传也能构造，旧调用方不受影响）。"""
    c = Credentials(
        api_host="h", tenant_domain="d", username="u",
        encrypted_password="p", alias="a",
    )
    assert c.default_company_code_id is None


def test_load_credentials_parses_default_company_code_id(tmp_path):
    cred = dict(_BASE_CRED, default_company_code_id="C-1000")
    ws = _make_ws(tmp_path, cred=cred)
    creds = load_credentials(workspace=ws, alias="zhuzheng")
    assert creds.default_company_code_id == "C-1000"


def test_load_credentials_missing_field_is_none_not_error(tmp_path):
    """旧凭证缺 default_company_code_id → None，不抛。"""
    ws = _make_ws(tmp_path, cred=dict(_BASE_CRED))  # 无 default_company_code_id
    creds = load_credentials(workspace=ws, alias="zhuzheng")
    assert creds.default_company_code_id is None
    # 其余字段照常解析，向后兼容
    assert creds.api_host == "https://apiv3.industics.com/service"
    assert creds.alias == "zhuzheng"
