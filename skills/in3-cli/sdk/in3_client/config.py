"""凭证与租户布局：只读解析 dispatcher 的 workspace / current-tenant / credentials.json。

与 dispatcher 平级共用同一套凭证文件（不经 subprocess、不写回）。布局：
  ~/.config/in3-cli/workspace.json        → {"path": "<ws>"}        (全局 pointer)
  <ws>/config/current-tenant.json         → {"tenant": "<alias>"}
  <ws>/config/tenants/<alias>/credentials.json

credentials.json 字段：api_host / env_label / tenant_domain / username /
encrypted_password（AES 串，直发不解密）/ modules_onboarded / last_login_at。
**注意**：本文件**没有** user_id —— X-Operator-ID 用的 user_id 来自 token 响应（见 auth）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# mod_key → base_suffix（拼在 api_host 之后；api_host 已含 /service）。
# 与 dispatcher MODULES[mod]["base_suffix"] 同源。
_BASE_SUFFIX = {
    "mm": "/mom/mm",
    "wm": "/mom/wm",
    "md": "/mom/md",
    "pp": "/mom/pp",
    "qm": "/mom/qm",
    "sd": "/mom/sd",
    "cr": "/mom/cr",
    "fn": "/mom/fn",
    "identity": "/mom/bo",
}

_DEFAULT_POINTER = Path.home() / ".config" / "in3-cli" / "workspace.json"

_REQUIRED_FIELDS = ("api_host", "tenant_domain", "username", "encrypted_password")


class MissingCredentialsError(Exception):
    """凭证文件/字段缺失或无法定位当前租户 —— fail-loud，绝不返回空 Session。"""


@dataclass
class Credentials:
    api_host: str
    tenant_domain: str
    username: str
    encrypted_password: str
    alias: str
    env_label: str | None = None
    modules_onboarded: list | None = None
    # fn 双轨 fncc header 的默认来源（facade 透传给 payment-receipt / fapiao；
    # 调用方显式传 extra_headers 则覆盖）。旧凭证缺该字段 → None。
    default_company_code_id: str | None = None
    # token 模式（login --paste-token / 浏览器捕获）：存 Bearer 而非 AES 口令。
    auth_mode: str = "password"
    access_token: str = ""
    refresh_token: str = ""
    tenant_id: str = ""
    user_id: str = ""

    @property
    def uaas_host(self) -> str:
        """token 端点的 host —— 与 api_host 同（dispatcher 里 uaas_host=cred.api_host）。"""
        return self.api_host

    def base_url(self, mod_key: str) -> str:
        """某模块的 REST base：api_host + /mom/<mod>。"""
        if mod_key not in _BASE_SUFFIX:
            raise KeyError(f"unknown module key: {mod_key!r}")
        return self.api_host.rstrip("/") + _BASE_SUFFIX[mod_key]


def resolve_workspace(pointer_path: Path | None = None) -> Path:
    """从全局 pointer（~/.config/in3-cli/workspace.json）读 workspace 路径。"""
    pointer_path = pointer_path or _DEFAULT_POINTER
    if not pointer_path.exists():
        raise MissingCredentialsError(
            f"workspace pointer not found: {pointer_path} —— run `in3_cli.py init` first"
        )
    try:
        data = json.loads(pointer_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise MissingCredentialsError(f"unreadable workspace pointer {pointer_path}: {e}")
    path = data.get("path")
    if not path:
        raise MissingCredentialsError(f"workspace pointer {pointer_path} has no 'path'")
    return Path(path)


def resolve_current_tenant(workspace: Path) -> str:
    """从 <ws>/config/current-tenant.json 读当前租户 alias。"""
    p = workspace / "config" / "current-tenant.json"
    if not p.exists():
        raise MissingCredentialsError(
            f"no current tenant: {p} not found —— run `login` or `use <alias>` first"
        )
    try:
        alias = json.loads(p.read_text()).get("tenant")
    except (OSError, json.JSONDecodeError) as e:
        raise MissingCredentialsError(f"unreadable current-tenant file {p}: {e}")
    if not alias:
        raise MissingCredentialsError(f"current-tenant file {p} has no 'tenant'")
    return alias


def load_credentials(
    workspace: Path | None = None,
    alias: str | None = None,
    pointer_path: Path | None = None,
) -> Credentials:
    """读出某租户的 Credentials；任何缺失（pointer/文件/字段/当前租户）都抛 MissingCredentialsError。"""
    if workspace is None:
        workspace = resolve_workspace(pointer_path)
    if alias is None:
        alias = resolve_current_tenant(workspace)

    cred_path = workspace / "config" / "tenants" / alias / "credentials.json"
    if not cred_path.exists():
        raise MissingCredentialsError(f"credentials.json not found for tenant {alias!r}: {cred_path}")
    try:
        data = json.loads(cred_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise MissingCredentialsError(f"unreadable credentials.json {cred_path}: {e}")

    is_token_mode = data.get("auth_mode") == "token" or bool(data.get("access_token"))
    # token 模式要 access_token；password 模式要 encrypted_password。其余字段两模式共需。
    required = ("api_host", "tenant_domain", "username") + (
        ("access_token",) if is_token_mode else ("encrypted_password",)
    )
    missing = [f for f in required if not data.get(f)]
    if missing:
        raise MissingCredentialsError(
            f"credentials.json {cred_path} missing required field(s): {', '.join(missing)}"
        )

    return Credentials(
        api_host=data["api_host"],
        tenant_domain=data["tenant_domain"],
        username=data["username"],
        encrypted_password=data.get("encrypted_password", ""),
        alias=alias,
        env_label=data.get("env_label"),
        modules_onboarded=data.get("modules_onboarded"),
        default_company_code_id=data.get("default_company_code_id"),
        auth_mode="token" if is_token_mode else "password",
        access_token=data.get("access_token", ""),
        refresh_token=data.get("refresh_token", ""),
        tenant_id=data.get("tenant_id", ""),
        user_id=data.get("user_id", ""),
    )
