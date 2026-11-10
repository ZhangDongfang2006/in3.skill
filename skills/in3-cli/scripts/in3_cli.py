#!/usr/bin/env python3
"""in3_cli — IN3 多模块 CLI 调度器 + workspace-scoped, multi-tenant onboarding.

子命令分两层:

  ## 安装/拆装/诊断
  init            创建独立 workspace (本地装 9 个 CLI,不污染全局)
  doctor          检测 workspace + legacy global install + Node + registry 健康
  migrate         一键把 legacy 全局安装 + ~/.ibrain-* config 迁到 workspace
  uninstall       删 workspace + pointer (干净卸载)
  where           print workspace 路径
  install <mod>   在已有 workspace 装/重装单个模块
  install-all     用 lock 重装 workspace 全套 (npm ci)
  upgrade <mod>   升单个模块到 latest (会脱离 lock baseline)
  upgrade-all     升所有已装模块到 latest
  pack-vendor     (维护者) npm pack 所有模块到 vendor/

  ## 凭证 + 租户 (workspace 内)
  login [alias]   交互式收 env/tenant/user/password,加密落到 <ws>/config/tenants/<alias>/
  sync [alias]    用主凭证重新 fanout 该 tenant 的 9 模块 profile
  logout <alias>  删指定 tenant 的 cred + profile (强制 tenant 参数)
  use <alias>     切当前 active tenant
  tenants         列出所有 tenant + 标当前
  status          JSON 输出 workspace / current_tenant / 9 模块状态
  test <mod>      跑单个模块 smoke
  test-all        跑所有模块 smoke
  help            quick start

设计要点:
- 所有 module CLI 安装 + config + cred 限定在 workspace dir 内
- 多租户: workspace 下按 <tenant alias> 物理分目录,9 个 IBRAIN_<MOD>_CONFIG_DIR
  env var 每次都全设(避免漏一个导致互调串配置)
- 切租户 = 改 <ws>/config/current-tenant.json 一行 → 下次任何 CLI 调用拿到的就是另一套
- 明文密码不落盘。AES-128-ECB (跟 in3.industics.com 网页同款),委托同目录 aes_encrypt.mjs

退出码:
  0  成功
  1  通用错误
  2  参数错
  4  workspace / tenant 缺失 / 用户中止
  5  网络 / CLI 调用失败
  13 鉴权失败 (smoke 返回 AUTH_FAILED)
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------- Constants -----------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
AES_SCRIPT = SCRIPT_DIR / "aes_encrypt.mjs"
TEMPLATES_DIR = SKILL_DIR / "templates"
VENDOR_DIR = SKILL_DIR / "vendor"
VENDOR_MANIFEST = VENDOR_DIR / "MANIFEST.json"
VENDOR_PYTHON_DIR = VENDOR_DIR / "python"  # Python wheelhouse（in3_client + requests + pandas/numpy）

CONFIG_DIR = Path.home() / ".config" / "in3-cli"
WORKSPACE_POINTER = CONFIG_DIR / "workspace.json"
VERSION_CACHE_FILE = CONFIG_DIR / "version_cache.json"
VERSION_CACHE_TTL_SECONDS = 2 * 3600  # 2h: 网络一次, 后续 status 都吃缓存

DEFAULT_WORKSPACE = Path.home() / "in3-workspace"

# dispatcher 自身版本（区分新旧 skill：1.1.0 起含 SDK + run 执行壳 + 登录三档 + audit；
# 1.1.1 identity smoke 自限定 --user-id，修复普通账号 roles list 404；
# 1.1.2 版本刷新 npm view 显式 --registry，修复全局缺 @industics scope 映射时 latest 全 null；
# 1.2.0 v2 纯读 MCP server（stdio JSON-RPC 单一 execute_code 工具）+ 多租户 session-scoped
#       路由（execute_code tenant 入参，省略回退当前 active tenant，未知报错不崩））。
# 1.3.0 移除调度器本地价格过滤；module CLI 返回什么就原样输出什么。
DISPATCHER_VERSION = "1.3.0"
DISPATCHER_FEATURES = ["run", "audit", "login-paste-token", "login-browser", "sdk:in3_client",
                       "mcp", "mcp:tenant-routing", "price-fields-pass-through"]

ENV_HOSTS = {
    "prod": "https://apiv3.industics.com/service",
    "qa": "https://apiv3-qa.industics.com/service",
}

# mod_key → env var name. 9 个 CLI 都支持这个 env var override 自己的 config dir。
# 任何调 module CLI 的 subprocess 都必须 9 个全设, 避免漏一个串配置(防御性)。
MODULE_ENV_VARS: dict[str, str] = {
    "mm": "IBRAIN_MM_CONFIG_DIR",
    "wm": "IBRAIN_WM_CONFIG_DIR",
    "md": "IN_MOM_MD_CONFIG_DIR",
    "pp": "IBRAIN_PP_CONFIG_DIR",
    "qm": "IBRAIN_QM_CONFIG_DIR",
    "sd": "IBRAIN_SD_CONFIG_DIR",
    "cr": "IN_MOM_CR_CONFIG_DIR",
    "fn": "IBRAIN_MOM_FN_CONFIG_DIR",
    "identity": "IBRAIN_IDENTITY_CONFIG_DIR",
}

# 各模块注册表。config_dir 已移除——现按 tenant 动态计算
# (<ws>/config/tenants/<alias>/.<binary-without-cli>/)。
MODULES: dict[str, dict] = {
    "mm": {
        "npm_package": "@industics/ibrain-mm-cli",
        "binary": "ibrain-mm-cli",
        "base_suffix": "/mom/mm",
        "smoke_cmd": ["currency", "list"],
        "smoke_desc": "列出本租户启用的币种(最轻量的全租户只读)",
        "supports_plaintext_password": True,
        "min_version_auto_use_context": None,
    },
    "wm": {
        "npm_package": "@industics/ibrain-wm-cli",
        "binary": "ibrain-wm-cli",
        "base_suffix": "/mom/wm",
        "smoke_cmd": ["rd-category", "list"],
        "smoke_desc": "列出本租户的收发类别字典(最轻量的全租户只读)",
        "supports_plaintext_password": True,
        "min_version_auto_use_context": None,
    },
    "md": {
        "npm_package": "@industics/in-mom-md-cli",
        "binary": "in-mom-md-cli",
        "base_suffix": "/mom/md",
        "smoke_cmd": ["currency", "list"],
        "smoke_desc": "列出本租户启用的币种(最轻量的全租户只读)",
        "supports_plaintext_password": True,
        "min_version_auto_use_context": None,
    },
    "pp": {
        "npm_package": "@industics/ibrain-pp-cli",
        "binary": "ibrain-pp-cli",
        "base_suffix": "/mom/pp",
        "smoke_cmd": ["production-plan", "list", "--size", "1"],
        "smoke_desc": "列 1 条工单验证 PP CLI 已正确登录并能查询 ProductionPlan",
        "supports_plaintext_password": True,
        "min_version_auto_use_context": None,
    },
    "qm": {
        "npm_package": "@industics/in-mom-qm-cli",
        "binary": "ibrain-qm-cli",
        "base_suffix": "/mom/qm",
        "smoke_cmd": ["inspection-lot", "list", "--size", "1"],
        "smoke_desc": "列 1 条检验批验证 QM CLI 已正确登录并能查询 InspectionLot",
        "supports_plaintext_password": True,
        "min_version_auto_use_context": "0.1.0",
    },
    "sd": {
        "npm_package": "@industics/ibrain-sd-cli",
        "binary": "ibrain-sd-cli",
        "base_suffix": "/mom/sd",
        "smoke_cmd": ["sales-order", "list", "--size", "1"],
        "smoke_desc": "列 1 条销售订单验证 SD CLI 已正确登录并能查询 SalesOrder",
        "supports_plaintext_password": True,
        "min_version_auto_use_context": "0.2.1",
    },
    "cr": {
        "npm_package": "@industics/in-mom-cr-cli",
        "binary": "in-mom-cr-cli",
        "base_suffix": "/mom/cr",
        "smoke_cmd": ["work-log-category", "list"],
        "smoke_desc": "列出本租户的服务记录类别(最轻量的全租户只读)",
        "supports_plaintext_password": True,
        "min_version_auto_use_context": None,
    },
    "fn": {
        "npm_package": "@industics/ibrain-mom-fn-cli",
        "binary": "ibrain-mom-fn-cli",
        "base_suffix": "/mom/fn",
        "smoke_cmd": ["company-code", "list"],
        "smoke_desc": "列出本租户授权的公司代码(最轻量的全租户只读)",
        "supports_plaintext_password": True,
        "min_version_auto_use_context": "0.1.0",
    },
    "identity": {
        "npm_package": "@industics/ibrain-identity-cli",
        "binary": "ibrain-identity-cli",
        "base_suffix": "/mom/bo",
        "smoke_cmd": ["roles", "list"],
        "smoke_desc": "查当前登录用户自己的角色(验证 UAAS 连通性,自动注入 --user-id)",
        "supports_plaintext_password": True,
        "min_version_auto_use_context": None,
    },
}


# ---------- Utilities -----------------------------------------------------------

def eprint(*args, **kwargs) -> None:
    print(*args, file=sys.stderr, **kwargs)


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(CONFIG_DIR, 0o700)
    except OSError:
        pass


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def is_system_binary_installed(name: str) -> bool:
    """For host-level binaries (npm, node). Uses PATH lookup."""
    return shutil.which(name) is not None


# ---------- Workspace pointer ---------------------------------------------------

def _load_workspace() -> Path | None:
    """读 ~/.config/in3-cli/workspace.json,返回 Path 或 None(未 init / 路径丢了)。"""
    if not WORKSPACE_POINTER.exists():
        return None
    try:
        data = json.loads(WORKSPACE_POINTER.read_text())
        p = Path(data["path"])
        return p if p.exists() else None
    except (OSError, json.JSONDecodeError, KeyError):
        return None


def _save_workspace(path: Path) -> None:
    ensure_config_dir()
    WORKSPACE_POINTER.write_text(json.dumps({"path": str(path.resolve())}, indent=2))
    try:
        os.chmod(WORKSPACE_POINTER, 0o600)
    except OSError:
        pass


def _clear_workspace_pointer() -> None:
    if WORKSPACE_POINTER.exists():
        WORKSPACE_POINTER.unlink()


def _require_workspace() -> Path:
    """For subcommands that need workspace. Eprint + sys.exit(4) if missing."""
    ws = _load_workspace()
    if ws is None:
        eprint("[in3-cli] no workspace found; run `python3 in3_cli.py init` first")
        sys.exit(4)
    return ws


# ---------- Tenant helpers ------------------------------------------------------

def _current_tenant_path(ws: Path) -> Path:
    return ws / "config" / "current-tenant.json"


def _load_current_tenant(ws: Path) -> str | None:
    p = _current_tenant_path(ws)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text()).get("tenant")
    except (OSError, json.JSONDecodeError):
        return None


def _save_current_tenant(ws: Path, alias: str) -> None:
    p = _current_tenant_path(ws)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"tenant": alias}, indent=2))
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def _clear_current_tenant(ws: Path) -> None:
    p = _current_tenant_path(ws)
    if p.exists():
        p.unlink()


def _list_tenants(ws: Path) -> list[str]:
    td = ws / "config" / "tenants"
    if not td.is_dir():
        return []
    return sorted(p.name for p in td.iterdir() if p.is_dir())


def _tenant_dir(ws: Path, alias: str) -> Path:
    return ws / "config" / "tenants" / alias


def _tenant_cred_path(ws: Path, alias: str) -> Path:
    return _tenant_dir(ws, alias) / "credentials.json"


def _tenant_config_dir(ws: Path, alias: str, mod_key: str) -> Path:
    """<ws>/config/tenants/<alias>/.ibrain-<mod>/ (basename derived from binary name)"""
    binary = MODULES[mod_key]["binary"]
    # ibrain-mm-cli → .ibrain-mm; in-mom-md-cli → .in-mom-md
    dir_name = "." + (binary[:-4] if binary.endswith("-cli") else binary)
    return _tenant_dir(ws, alias) / dir_name


def _identity_self_user_id(ws: Path, alias: str) -> str | None:
    """从 identity CLI 的 token 缓存里取当前登录用户自己的 user_id。

    用于把 identity smoke 自限定成「查自己的角色」(roles list --user-id <self>)——
    任何登录用户都有权查自己的角色,而裸 `roles list` 是「列全租户所有角色」,
    需要后台管理员权限,普通账号会被后端以 404 拒绝。
    """
    cred_path = _tenant_config_dir(ws, alias, "identity") / "credentials.json"
    if not cred_path.exists():
        return None
    try:
        cred = json.loads(cred_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    entry = cred.get(alias)
    if isinstance(entry, dict) and entry.get("user_id"):
        return str(entry["user_id"])
    return None


def _require_current_tenant(ws: Path) -> str:
    alias = _load_current_tenant(ws)
    if alias is None:
        eprint("[in3-cli] no current tenant; run `login` or `use <alias>` first")
        sys.exit(4)
    return alias


# ---------- Binary resolution + subprocess env ----------------------------------

def _resolve_binary(ws: Path, mod_key: str) -> Path:
    return ws / "node_modules" / ".bin" / MODULES[mod_key]["binary"]


def is_module_binary_installed(mod_key: str, ws: Path | None = None) -> bool:
    if ws is None:
        ws = _load_workspace()
    if ws is None:
        return False
    return _resolve_binary(ws, mod_key).exists()


def _module_env(ws: Path, alias: str) -> dict[str, str]:
    """9 个 IBRAIN_<MOD>_CONFIG_DIR env var (基于 tenant alias)。

    全设 9 个,即使我们只调一个 CLI——防御性:某些 CLI 内部可能调用其他 CLI,
    漏设一个就串配置。
    """
    return {var: str(_tenant_config_dir(ws, alias, k)) for k, var in MODULE_ENV_VARS.items()}


def _build_env(ws: Path, alias: str) -> dict[str, str]:
    """os.environ + 9 个 IBRAIN_<MOD>_CONFIG_DIR overrides。"""
    env = os.environ.copy()
    env.update(_module_env(ws, alias))
    return env


# ---------- Master credentials (tenant-aware) -----------------------------------

def load_master_cred(ws: Path, alias: str) -> dict | None:
    p = _tenant_cred_path(ws, alias)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def save_master_cred(cred: dict, ws: Path, alias: str) -> None:
    p = _tenant_cred_path(ws, alias)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p.parent, 0o700)
    except OSError:
        pass
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cred, indent=2))
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(p)


# ---------- Version cache (unchanged from previous design) ----------------------

def load_version_cache() -> dict:
    if not VERSION_CACHE_FILE.exists():
        return {}
    try:
        return json.loads(VERSION_CACHE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save_version_cache(cache: dict) -> None:
    ensure_config_dir()
    VERSION_CACHE_FILE.write_text(json.dumps(cache, indent=2))
    try:
        os.chmod(VERSION_CACHE_FILE, 0o600)
    except OSError:
        pass


def invalidate_version_cache(npm_package: str) -> None:
    cache = load_version_cache()
    if cache.pop(npm_package, None) is not None:
        save_version_cache(cache)


# ---------- Installed / latest version ------------------------------------------

def get_installed_version(npm_package: str, ws: Path | None = None) -> str | None:
    """从 workspace 的 node_modules/<pkg>/package.json 读 version。

    无 workspace 或包未装返 None。**不再走 `npm ls -g`**——避免误识别全局污染。
    """
    if ws is None:
        ws = _load_workspace()
    if ws is None:
        return None
    pkg_json = ws / "node_modules" / npm_package / "package.json"
    if not pkg_json.exists():
        return None
    try:
        return json.loads(pkg_json.read_text()).get("version")
    except (OSError, json.JSONDecodeError):
        return None


def get_latest_version(npm_package: str, refresh: bool = False) -> str | None:
    """从 npm 注册表拿 latest version。2h 本地缓存。"""
    cache = load_version_cache()
    entry = cache.get(npm_package)
    if not refresh and entry:
        checked_at = entry.get("checked_at", 0)
        if time.time() - checked_at < VERSION_CACHE_TTL_SECONDS:
            return entry.get("latest")
    try:
        proc = subprocess.run(
            # 显式 --registry：不依赖 ambient ~/.npmrc 的 @industics:registry 映射。
            # 该 scope 映射只写在 workspace 的 .npmrc 里，而本命令从脚本 cwd 跑、读的是
            # 全局 ~/.npmrc。全局缺映射时（全新用户 / 干净 env）npm view 会落到公网
            # registry → @industics/* 私有包 404 → latest 全 null。--fetch-retries=1 +
            # timeout 让 registry 慢/挂时快速失败、优雅退回缓存而非 hang 住整轮刷新。
            ["npm", "view", npm_package, "version",
             "--registry", "http://npm.industics.cn", "--fetch-retries=1"],
            capture_output=True, text=True, check=False, timeout=20,
        )
    except (subprocess.TimeoutExpired, OSError):
        return entry.get("latest") if entry else None
    if proc.returncode != 0:
        return entry.get("latest") if entry else None
    latest = proc.stdout.strip()
    if not latest:
        return entry.get("latest") if entry else None
    cache[npm_package] = {"latest": latest, "checked_at": int(time.time())}
    save_version_cache(cache)
    return latest


def get_legacy_global_installed() -> dict[str, str]:
    """检测全局是否有 @industics/* 残留 (用于 doctor / migrate)。

    返 {npm_package: version}。无残留返 {}。
    """
    if not is_system_binary_installed("npm"):
        return {}
    proc = subprocess.run(
        ["npm", "ls", "-g", "--json", "--depth=0"],
        capture_output=True, text=True, check=False,
    )
    if not proc.stdout:
        return {}
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}
    out = {}
    for name, info in (data.get("dependencies") or {}).items():
        if name.startswith("@industics/"):
            out[name] = info.get("version", "?")
    return out


# ---------- AES encrypt ---------------------------------------------------------

def aes_encrypt(plaintext: str) -> str:
    """调 aes_encrypt.mjs。明文走 stdin,密文从 stdout 拿。"""
    if not AES_SCRIPT.exists():
        raise RuntimeError(f"missing helper: {AES_SCRIPT}")
    if not is_system_binary_installed("node"):
        raise RuntimeError("node not in PATH; install Node.js >= 20")
    proc = subprocess.run(
        ["node", str(AES_SCRIPT)],
        input=plaintext,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"aes_encrypt.mjs failed: {proc.stderr}")
    return proc.stdout.strip()


# ---------- Module path / profile helpers (tenant-aware) -----------------------

def module_base_url(mod_key: str, api_host: str) -> str:
    return api_host.rstrip("/") + MODULES[mod_key]["base_suffix"]


def module_profile_path(ws: Path, alias: str, mod_key: str) -> Path:
    return _tenant_config_dir(ws, alias, mod_key) / "config.json"


def module_profile_exists(ws: Path, alias: str, mod_key: str, profile: str | None = None) -> bool:
    if profile is None:
        profile = alias
    p = module_profile_path(ws, alias, mod_key)
    if not p.exists():
        return False
    try:
        cfg = json.loads(p.read_text())
        return any(prof.get("name") == profile for prof in cfg.get("profiles", []))
    except (OSError, json.JSONDecodeError):
        return False


def module_current_context(ws: Path, alias: str, mod_key: str) -> str | None:
    p = module_profile_path(ws, alias, mod_key)
    if not p.exists():
        return None
    try:
        cfg = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return cfg.get("current_context")


def _parse_semver(v: str | None) -> tuple[int, int, int] | None:
    if not v:
        return None
    parts = v.split(".")
    if len(parts) != 3:
        return None
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None


def module_supports_auto_use_context(mod_key: str, ws: Path | None = None) -> bool:
    spec = MODULES[mod_key]
    min_v = _parse_semver(spec.get("min_version_auto_use_context"))
    if min_v is None:
        return False
    installed = _parse_semver(get_installed_version(spec["npm_package"], ws=ws))
    return installed is not None and installed >= min_v


def _try_cli_upsert(ws: Path, alias: str, mod_key: str, profile: dict) -> bool:
    """跑 <binary> config add-profile 写 profile,return True 表示成功且 current_context 已切。"""
    binary = _resolve_binary(ws, mod_key)
    if not binary.exists():
        return False
    cmd = [
        str(binary), "config", "add-profile", profile["name"],
        "--uaas-host", profile["uaas_host"],
        "--base-url", profile["base_url"],
        "--tenant-domain", profile["tenant_domain"],
        "--username", profile["username"],
        "--encrypted-password", profile["encrypted_password"],
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, check=False,
        env=_build_env(ws, alias),
    )
    if proc.returncode != 0:
        return False
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return False
    return out.get("current_context") == profile["name"]


def write_module_profile(ws: Path, alias: str, mod_key: str, profile: dict) -> str:
    """upsert profile + 切 current_context。返 'cli' / 'direct' 表明走的路径。"""
    if module_supports_auto_use_context(mod_key, ws=ws) and _try_cli_upsert(ws, alias, mod_key, profile):
        return "cli"

    cfg_dir = _tenant_config_dir(ws, alias, mod_key)
    cfg_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(cfg_dir, 0o700)
    except OSError:
        pass
    cfg_path = cfg_dir / "config.json"
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text())
        except (OSError, json.JSONDecodeError):
            cfg = {"current_context": None, "profiles": []}
    else:
        cfg = {"current_context": None, "profiles": []}

    profiles = [p for p in cfg.get("profiles", []) if p.get("name") != profile["name"]]
    profiles.append(profile)
    cfg["profiles"] = profiles
    cfg["current_context"] = profile["name"]

    tmp = cfg_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2))
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(cfg_path)
    return "direct"


def remove_module_profile(ws: Path, alias: str, mod_key: str, profile: str | None = None) -> bool:
    if profile is None:
        profile = alias
    cfg_path = module_profile_path(ws, alias, mod_key)
    if not cfg_path.exists():
        return False
    try:
        cfg = json.loads(cfg_path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    before = len(cfg.get("profiles", []))
    cfg["profiles"] = [p for p in cfg.get("profiles", []) if p.get("name") != profile]
    if cfg.get("current_context") == profile:
        cfg["current_context"] = cfg["profiles"][0]["name"] if cfg["profiles"] else None
    if len(cfg["profiles"]) == before:
        return False
    cfg_path.write_text(json.dumps(cfg, indent=2))
    return True


# ---------- Vendor (offline tarball bundle) ------------------------------------

class VendorIntegrityError(RuntimeError):
    """vendor tarball sha256 不匹配。强制中止,不静默退回 registry。"""


def _load_vendor_manifest() -> dict:
    if not VENDOR_MANIFEST.is_file():
        return {}
    try:
        data = json.loads(VENDOR_MANIFEST.read_text())
    except (json.JSONDecodeError, OSError) as e:
        eprint(f"[in3-cli] vendor MANIFEST.json 损坏,忽略 vendor 走 registry: {e}")
        return {}
    return data.get("modules", {})


def _vendor_resolve(mod_key: str) -> Path | None:
    manifest = _load_vendor_manifest()
    if mod_key not in manifest:
        return None
    entry = manifest[mod_key]
    tarball = VENDOR_DIR / entry["tarball"]
    if not tarball.is_file():
        eprint(f"[in3-cli] {mod_key}: MANIFEST 指向 {entry['tarball']} 但文件缺失,退回 registry")
        return None
    actual = _sha256_of(tarball)
    if actual != entry["sha256"]:
        raise VendorIntegrityError(
            f"{mod_key}: vendor/{entry['tarball']} sha256 失配\n"
            f"           expected: {entry['sha256']}\n"
            f"           actual:   {actual}\n"
            f"  → 让维护者跑 `pack-vendor` 重打,或手动删该 tgz。"
        )
    return tarball


# ---------- NPM install / upgrade (workspace-scoped) ---------------------------

def _npm_install_to_workspace(ws: Path, target: str) -> int:
    """`npm i --prefix <ws> <target>` 简单包装。target 可以是 npm spec 或本地 tgz 路径。"""
    if not is_system_binary_installed("npm"):
        eprint("[in3-cli] npm not in PATH; install Node.js >= 20 first")
        return 5
    eprint(f"[in3-cli] npm i --prefix {ws} {target}")
    return subprocess.call(["npm", "i", "--prefix", str(ws), target])


def npm_install_module(ws: Path, mod_key: str) -> int:
    """装/升级 workspace 内的单个 module。vendor 命中走本地 tgz,否则 registry。"""
    npm_pkg = MODULES[mod_key]["npm_package"]
    try:
        tarball = _vendor_resolve(mod_key)
    except VendorIntegrityError as e:
        eprint(f"[in3-cli] {e}")
        return 5
    if tarball:
        entry = _load_vendor_manifest()[mod_key]
        eprint(f"[in3-cli] {mod_key}: using vendor tarball v{entry['version']} (offline)")
        return _npm_install_to_workspace(ws, str(tarball))
    return _npm_install_to_workspace(ws, npm_pkg)


def npm_upgrade_module(ws: Path, mod_key: str) -> int:
    """`npm i --prefix <ws> @industics/<pkg>@latest`,会脱离 lock baseline。"""
    npm_pkg = MODULES[mod_key]["npm_package"]
    eprint(f"[in3-cli] {mod_key}: upgrade 走 npm registry 拉 latest,将脱离 lock baseline")
    rc = _npm_install_to_workspace(ws, f"{npm_pkg}@latest")
    if rc == 0:
        invalidate_version_cache(npm_pkg)
    return rc


# ---------- cmd: status --------------------------------------------------------

def cmd_status(args) -> int:
    ws = _load_workspace()
    vendor_manifest = _load_vendor_manifest()
    out: dict = {
        "dispatcher_version": DISPATCHER_VERSION,
        "dispatcher_features": DISPATCHER_FEATURES,
        "workspace_path": str(ws) if ws else None,
        "workspace_exists": ws is not None,
        "current_tenant": _load_current_tenant(ws) if ws else None,
        "tenants": _list_tenants(ws) if ws else [],
        "vendor_present": bool(vendor_manifest),
        "modules": {},
    }
    current_alias = out["current_tenant"]
    if ws and current_alias:
        cred = load_master_cred(ws, current_alias)
        if cred:
            out["current_tenant_meta"] = {
                "api_host": cred.get("api_host"),
                "env_label": cred.get("env_label"),
                "tenant_domain": cred.get("tenant_domain"),
                "username": cred.get("username"),
                "last_login_at": cred.get("last_login_at"),
            }
    refresh = getattr(args, "refresh_versions", False)
    for key, spec in MODULES.items():
        installed = is_module_binary_installed(key, ws=ws)
        installed_ver = get_installed_version(spec["npm_package"], ws=ws) if installed else None
        latest_ver = get_latest_version(spec["npm_package"], refresh=refresh)
        update_available = bool(
            installed_ver and latest_ver and installed_ver != latest_ver
        )
        if ws and current_alias:
            has_profile = module_profile_exists(ws, current_alias, key)
            cur_ctx = module_current_context(ws, current_alias, key)
        else:
            has_profile, cur_ctx = False, None
        if not has_profile:
            profile_state = "absent"
        elif cur_ctx == current_alias:
            profile_state = "present"
        else:
            profile_state = "present_but_not_active"
        vendor_entry = vendor_manifest.get(key)
        out["modules"][key] = {
            "binary": spec["binary"],
            "installed": installed,
            "installed_version": installed_ver,
            "latest_version": latest_ver,
            "update_available": update_available,
            "profile_for_current_tenant": profile_state,
            "current_context": cur_ctx,
            "vendor_tarball_version": vendor_entry["version"] if vendor_entry else None,
        }
    legacy = get_legacy_global_installed()
    if legacy:
        out["legacy_global_install"] = legacy
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


# ---------- cmd: install / install-all -----------------------------------------

def cmd_install(args) -> int:
    mod = args.module
    if mod not in MODULES:
        eprint(f"[in3-cli] unknown module '{mod}'; known: {list(MODULES)}")
        return 2
    ws = _require_workspace()
    return npm_install_module(ws, mod)


def cmd_install_all(args) -> int:
    """workspace 内重装全套。如果有 lock 走 npm ci(可复现);
    否则按 MODULES 逐个 install(走 vendor 或 registry)。"""
    ws = _require_workspace()
    lock = ws / "package-lock.json"
    pkg_json = ws / "package.json"
    if lock.exists() and pkg_json.exists() and _load_vendor_manifest() == {}:
        # 走 npm ci,严格按 lock
        eprint(f"[in3-cli] npm ci --prefix {ws}")
        return subprocess.call(["npm", "ci", "--prefix", str(ws)])
    # 否则按 MODULES 逐个 install (vendor 优先)
    rc = 0
    for key in MODULES:
        sub_rc = npm_install_module(ws, key)
        if sub_rc != 0:
            rc = sub_rc
    return rc


def cmd_upgrade(args) -> int:
    mod = args.module
    if mod not in MODULES:
        eprint(f"[in3-cli] unknown module '{mod}'; known: {list(MODULES)}")
        return 2
    ws = _require_workspace()
    return npm_upgrade_module(ws, mod)


def cmd_upgrade_all(args) -> int:
    ws = _require_workspace()
    rc = 0
    for key in MODULES:
        if not is_module_binary_installed(key, ws=ws):
            eprint(f"[in3-cli] {MODULES[key]['binary']} 未装,跳过")
            continue
        sub_rc = npm_upgrade_module(ws, key)
        if sub_rc != 0:
            rc = sub_rc
    return rc


# ---------- cmd: pack-vendor (maintainer-only) --------------------------------

def cmd_pack_vendor(args) -> int:
    if not is_system_binary_installed("npm"):
        eprint("[in3-cli] npm not in PATH")
        return 5

    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    for old in VENDOR_DIR.glob("*.tgz"):
        old.unlink()

    registry = args.registry
    manifest: dict = {
        "schema_version": 1,
        "packed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "packed_by": "in3_cli.py pack-vendor",
        "registry_source": registry,
        "note": (
            "Offline install bundle. cmd_init will prefer these local tarballs "
            "over the npm registry. Maintainer refreshes via `pack-vendor`."
        ),
        "modules": {},
    }

    rc = 0
    for key, spec in MODULES.items():
        npm_pkg = spec["npm_package"]
        version = get_latest_version(npm_pkg, refresh=True)
        if not version:
            eprint(f"[in3-cli] {key}: 拿不到 latest version,跳过")
            rc = 5
            continue
        spec_str = f"{npm_pkg}@{version}"
        eprint(f"[in3-cli] npm pack {spec_str}")
        proc = subprocess.run(
            ["npm", "pack", spec_str, "--registry", registry],
            cwd=str(VENDOR_DIR), capture_output=True, text=True,
        )
        if proc.returncode != 0:
            eprint(f"[in3-cli] {key}: npm pack 失败 → {proc.stderr.strip()}")
            rc = 5
            continue
        tarball_name = proc.stdout.strip().splitlines()[-1].strip()
        tarball_path = VENDOR_DIR / tarball_name
        if not tarball_path.is_file():
            eprint(f"[in3-cli] {key}: 预期 {tarball_path} 不存在")
            rc = 5
            continue
        manifest["modules"][key] = {
            "npm_package": npm_pkg,
            "version": version,
            "tarball": tarball_name,
            "sha256": _sha256_of(tarball_path),
        }
        eprint(f"[in3-cli]   → {tarball_name} ({tarball_path.stat().st_size // 1024} KB)")

    VENDOR_MANIFEST.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    )
    eprint(f"[in3-cli] wrote {VENDOR_MANIFEST} with {len(manifest['modules'])} modules")
    return rc


# ---------- SDK wheel 离线装（vendoring）---------------------------------------

def _pip_install_to_target(pkgs: list[str], find_links: Path, target: Path):
    """离线装 wheel 到 target（pip --no-index --find-links；pip 自动按当前解释器平台×py 选 wheel）。

    返回 subprocess.CompletedProcess（caller 判 returncode）。捕获输出避免刷屏 + 便于测试。
    """
    return subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-index",
         "--find-links", str(find_links), "--target", str(target),
         "--disable-pip-version-check", "--no-warn-script-location", *pkgs],
        capture_output=True, text=True,
    )


def _install_sdk_wheels(ws: Path, *, find_links: Path | None = None) -> dict:
    """npm 之后一次性把 SDK 离线装进 <ws>/python-packages/（issue #2/#7）：

    - 硬装层 in3_client + requests（纯 py wheel，任意平台/py 都有）；失败也不阻断 init
      （run 另有 SKILL_DIR/sdk 兜底）。
    - 软装层 pandas（缺当前平台/py 二进制 wheel → 跳过不硬失败，df/join 运行时 stdlib 降级）。

    pip 的 --find-links 自动按 sys.platform×machine×py 选匹配 wheel；缺 wheelhouse 整步跳过。
    返回 {"installed": [...], "skipped": [...]} 供调用方/测试断言。
    """
    find_links = find_links or VENDOR_PYTHON_DIR
    pkg_dir = ws / "python-packages"
    result: dict = {"installed": [], "skipped": []}

    wheels = sorted(find_links.glob("*.whl")) if find_links.is_dir() else []
    if not wheels:
        eprint(f"[in3-cli] ⚠ wheelhouse 空/缺 ({find_links})，跳过 SDK 离线装；"
               "run 仍可用 SKILL_DIR/sdk 兜底（pandas 走运行时降级）")
        result["skipped"] = ["in3_client", "requests", "pandas"]
        return result

    plat = f"{sys.platform}/{platform.machine()} py{sys.version_info.major}.{sys.version_info.minor}"
    eprint(f"[in3-cli] 离线装 SDK wheel → {pkg_dir}（平台 {plat}，wheelhouse {len(wheels)} wheels）")

    hard = _pip_install_to_target(["in3_client", "requests"], find_links, pkg_dir)
    if hard.returncode == 0:
        result["installed"] += ["in3_client", "requests"]
        eprint("[in3-cli]   ✓ in3_client + requests")
    else:
        result["skipped"] += ["in3_client", "requests"]
        eprint(f"[in3-cli]   ⚠ in3_client/requests 离线装失败（rc={hard.returncode}）；"
               f"run 仍可用 SKILL_DIR/sdk 兜底。pip: {(hard.stderr or '').strip()[-300:]}")

    soft = _pip_install_to_target(["pandas"], find_links, pkg_dir)
    if soft.returncode == 0:
        result["installed"].append("pandas")
        eprint("[in3-cli]   ✓ pandas（df/join 聚合可用）")
    else:
        result["skipped"].append("pandas")
        eprint("[in3-cli]   ⚠ 当前平台/py 无 pandas wheel，跳过（df/join 运行时 stdlib 降级，不影响 run）")

    return result


# ---------- cmd: init ----------------------------------------------------------

def cmd_init(args) -> int:
    """创建独立 workspace,本地装 9 个 CLI,不污染全局。"""
    path = Path(args.path).expanduser() if args.path else DEFAULT_WORKSPACE
    path = path.resolve()

    # legacy check — 全局有 @industics/* 时,init 仍然能跑,但提醒
    legacy = get_legacy_global_installed()
    if legacy and not args.allow_legacy:
        eprint(f"[in3-cli] ⚠ detected legacy global install: {list(legacy)}")
        eprint("[in3-cli] 这会让你的 shell PATH 优先解析全局 binary,与 workspace 隔离冲突。")
        eprint("[in3-cli] 建议先跑 `migrate` 一键迁移;或加 --allow-legacy 跳过此检查。")
        return 5

    if path.exists():
        if not args.force:
            eprint(f"[in3-cli] workspace exists at {path}; pass --force to wipe and reinit")
            return 5
        eprint(f"[in3-cli] --force: removing existing workspace at {path}")
        shutil.rmtree(path)

    # path 检查 — 空格 / 非 ASCII 在 npm bin shim 里偶尔出怪;不阻塞,只 warn
    if " " in str(path) or not str(path).isascii():
        eprint(f"[in3-cli] ⚠ workspace path 含空格或非 ASCII 字符: {path}")
        eprint("[in3-cli]   npm bin shim 多数 OK,但偶尔有边缘 bug;有问题换 ASCII 路径")

    # check templates 完整性
    if not TEMPLATES_DIR.is_dir():
        eprint(f"[in3-cli] templates dir 缺失: {TEMPLATES_DIR}")
        return 5
    required_templates = ["package.json", "package-lock.json", ".nvmrc", ".npmrc"]
    missing = [f for f in required_templates if not (TEMPLATES_DIR / f).is_file()]
    if missing:
        eprint(f"[in3-cli] templates 缺文件: {missing}")
        return 5

    # 1. mkdir + cp templates
    path.mkdir(parents=True)
    for f in required_templates:
        shutil.copy2(TEMPLATES_DIR / f, path / f)
    (path / "config").mkdir()
    (path / "config" / "tenants").mkdir()
    eprint(f"[in3-cli] workspace 框架就位 at {path}")

    # 2. npm install
    vendor_manifest = _load_vendor_manifest()
    rc = 0
    if vendor_manifest:
        eprint(f"[in3-cli] detected vendor manifest with {len(vendor_manifest)} modules,使用离线 tgz")
        for key in MODULES:
            if key not in vendor_manifest:
                eprint(f"[in3-cli] {key}: vendor 没覆盖此 module,fallback to registry")
                sub_rc = _npm_install_to_workspace(path, MODULES[key]["npm_package"])
            else:
                try:
                    tarball = _vendor_resolve(key)
                except VendorIntegrityError as e:
                    eprint(f"[in3-cli] {e}")
                    return 5
                if tarball is None:
                    sub_rc = _npm_install_to_workspace(path, MODULES[key]["npm_package"])
                else:
                    eprint(f"[in3-cli] {key}: vendor tarball (offline)")
                    sub_rc = _npm_install_to_workspace(path, str(tarball))
            if sub_rc != 0:
                rc = sub_rc
    else:
        eprint(f"[in3-cli] npm ci --prefix {path} (按 package-lock.json 严格安装)")
        rc = subprocess.call(["npm", "ci", "--prefix", str(path)])

    # 2b. SDK 离线装：in3_client + requests（硬）+ pandas（best-effort）→ <ws>/python-packages/。
    #     独立于 npm（即便上面 npm 装 CLI 失败，SDK/run 仍可单独用）。
    _install_sdk_wheels(path)

    if rc != 0:
        eprint(f"[in3-cli] npm install 失败 (rc={rc})。workspace 已创建但未装齐,可重试 `install-all`")
        # 仍写 pointer,允许 doctor / install-all 后续修
        _save_workspace(path)
        return rc

    # 3. workspace pointer
    _save_workspace(path)
    eprint(f"[in3-cli] workspace pointer 写入 {WORKSPACE_POINTER}")

    # 4. status
    eprint("[in3-cli] init 完成。下一步: `python3 in3_cli.py login` 配租户凭证")
    return cmd_status(argparse.Namespace(refresh_versions=False))


# ---------- cmd: doctor --------------------------------------------------------

def _print_check(label: str, ok: bool | None, detail: str = "") -> None:
    sigil = {True: "[ ok ]", False: "[FAIL]", None: "[warn]"}[ok]
    line = f"  {sigil} {label}"
    if detail:
        line += f" — {detail}"
    print(line)


def cmd_doctor(args) -> int:
    """检查 workspace + legacy + Node + .npmrc + registry + binary + tenant 完整性。"""
    print("=== in3-cli doctor ===\n")

    fails = 0
    warns = 0

    # 1. workspace
    ws = _load_workspace()
    if ws is None:
        _print_check("workspace pointer", False, f"{WORKSPACE_POINTER} not found,run init first")
        fails += 1
    else:
        _print_check("workspace pointer", True, str(ws))
        node_modules = ws / "node_modules"
        if not node_modules.is_dir():
            _print_check("workspace node_modules", False, "missing,run install-all")
            fails += 1
        else:
            _print_check("workspace node_modules", True)
        lock = ws / "package-lock.json"
        if lock.exists() and node_modules.is_dir():
            # 简单 drift 检查: 看 lock 里的 9 个 @industics/<pkg> 版本 vs node_modules 里实际
            try:
                lock_data = json.loads(lock.read_text())
            except (OSError, json.JSONDecodeError):
                lock_data = {}
            drift = []
            for key, spec in MODULES.items():
                npm_pkg = spec["npm_package"]
                lock_entry = (lock_data.get("packages") or {}).get(f"node_modules/{npm_pkg}", {})
                lock_v = lock_entry.get("version")
                installed_v = get_installed_version(npm_pkg, ws=ws)
                if lock_v and installed_v and lock_v != installed_v:
                    drift.append(f"{key}: lock={lock_v} installed={installed_v}")
            if drift:
                _print_check("lock vs node_modules drift", None, "; ".join(drift))
                warns += 1
            else:
                _print_check("lock vs node_modules drift", True)

    # 2. legacy global install
    legacy = get_legacy_global_installed()
    if legacy:
        _print_check("no legacy global install", False, f"{len(legacy)} 个: {list(legacy)} — 跑 `migrate`")
        fails += 1
    else:
        _print_check("no legacy global install", True)

    # 3. Node version
    if is_system_binary_installed("node"):
        proc = subprocess.run(["node", "--version"], capture_output=True, text=True, check=False)
        ver = proc.stdout.strip()
        # parse vXX.YY.ZZ
        if ver.startswith("v"):
            major = ver[1:].split(".")[0]
            try:
                major_int = int(major)
                if major_int >= 20:
                    _print_check("Node version", True, ver)
                else:
                    _print_check("Node version", None, f"{ver} — workspace 要求 >= 20")
                    warns += 1
            except ValueError:
                _print_check("Node version", None, ver)
                warns += 1
        else:
            _print_check("Node version", None, "无法解析")
            warns += 1
    else:
        _print_check("Node binary", False, "node not in PATH")
        fails += 1

    # 4. global .npmrc _auth 冲突
    global_npmrc = Path.home() / ".npmrc"
    if global_npmrc.exists():
        try:
            content = global_npmrc.read_text()
        except OSError:
            content = ""
        if "industics" in content and "_auth=" in content:
            _print_check("~/.npmrc clean", None, "含 _auth — registry 匿名可读,该字段可删")
            warns += 1
        else:
            _print_check("~/.npmrc clean", True)
    else:
        _print_check("~/.npmrc clean", True, "(file absent)")

    # 5. registry connectivity (anonymous probe)
    proc = subprocess.run(
        ["npm", "view", "@industics/ibrain-mm-cli", "version",
         "--registry=http://npm.industics.cn", "--userconfig=/dev/null"],
        capture_output=True, text=True, check=False, timeout=10,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        _print_check("registry anonymous reachable", True, proc.stdout.strip())
    else:
        _print_check("registry anonymous reachable", None,
                     "无网/内网未连;离线安装仍可用")
        warns += 1

    # 6. each module binary --version
    if ws:
        for key in MODULES:
            binary = _resolve_binary(ws, key)
            if not binary.exists():
                _print_check(f"module {key} binary", False, "not installed")
                fails += 1
                continue
            proc = subprocess.run(
                [str(binary), "--version"],
                capture_output=True, text=True, check=False, timeout=5,
            )
            if proc.returncode == 0:
                _print_check(f"module {key} --version", True, proc.stdout.strip().splitlines()[-1] if proc.stdout else "")
            else:
                _print_check(f"module {key} --version", False, proc.stderr.strip()[:80])
                fails += 1

    # 7. tenant 完整性
    if ws:
        tenants = _list_tenants(ws)
        if not tenants:
            _print_check("tenants configured", None, "0 个,跑 `login` 配第一个")
            warns += 1
        else:
            for alias in tenants:
                td = _tenant_dir(ws, alias)
                cred_p = _tenant_cred_path(ws, alias)
                if not cred_p.exists():
                    _print_check(f"tenant {alias} cred", False, "missing credentials.json")
                    fails += 1
                else:
                    _print_check(f"tenant {alias} cred", True)
                # 9 模块 profile
                missing = [k for k in MODULES if not module_profile_exists(ws, alias, k)]
                if missing:
                    _print_check(f"tenant {alias} module profiles", None, f"missing: {missing}")
                    warns += 1
                else:
                    _print_check(f"tenant {alias} module profiles", True, "8/8")
            cur = _load_current_tenant(ws)
            if cur not in tenants:
                _print_check("current-tenant valid", False, f"{cur!r} not in {tenants}")
                fails += 1
            else:
                _print_check("current-tenant valid", True, cur)

    print()
    if fails:
        print(f"❌ {fails} FAIL, {warns} WARN")
        return 5
    if warns:
        print(f"⚠️  {warns} WARN, 0 FAIL")
        return 0
    print("✅ all checks passed")
    return 0


# ---------- cmd: migrate -------------------------------------------------------

LEGACY_CRED_FILE = CONFIG_DIR / "credentials.json"
LEGACY_HOME_CONFIG_DIRS = {
    "mm": Path.home() / ".ibrain-mm",
    "wm": Path.home() / ".ibrain-wm",
    "md": Path.home() / ".in-mom-md",
    "pp": Path.home() / ".ibrain-pp",
    "qm": Path.home() / ".ibrain-qm",
    "sd": Path.home() / ".ibrain-sd",
    "cr": Path.home() / ".in-mom-cr",
    "fn": Path.home() / ".ibrain-mom-fn",
}


def cmd_migrate(args) -> int:
    """legacy → workspace 一键迁移:rm -g 全局包 + 拷 ~/.ibrain-* + 拷主 cred + 改 .bak。"""
    legacy = get_legacy_global_installed()
    legacy_cred = LEGACY_CRED_FILE.exists()
    legacy_configs = {k: d for k, d in LEGACY_HOME_CONFIG_DIRS.items() if d.is_dir()}

    if not legacy and not legacy_cred and not legacy_configs:
        eprint("[in3-cli] nothing to migrate (无全局包,无 ~/.ibrain-*,无主 cred)")
        return 0

    # 读旧主 cred 拿 tenant_domain 作 alias
    alias = None
    old_cred_data = None
    if legacy_cred:
        try:
            old_cred_data = json.loads(LEGACY_CRED_FILE.read_text())
            alias = old_cred_data.get("tenant_domain")
        except (OSError, json.JSONDecodeError):
            pass
    if not alias:
        alias = input("tenant alias (旧 cred 没法自动识别,你手输 — 例 indx): ").strip()
        if not alias:
            eprint("[in3-cli] alias 不能空")
            return 2

    print("=== migrate plan ===")
    print(f"  alias: {alias}")
    if legacy:
        print(f"  npm rm -g: {list(legacy)}")
    if legacy_cred:
        print(f"  copy {LEGACY_CRED_FILE} → workspace 内 tenants/{alias}/credentials.json")
    for k, d in legacy_configs.items():
        print(f"  copy {d}/ → workspace tenants/{alias}/{d.name}/ + 原 → {d}.bak")
    confirm = input("\nproceed? [y/N]: ").strip().lower()
    if confirm != "y":
        eprint("[in3-cli] aborted by user")
        return 4

    # 1. 确保 workspace 存在
    ws = _load_workspace()
    if ws is None:
        eprint("[in3-cli] workspace 不存在,先跑 init")
        path = DEFAULT_WORKSPACE
        # 暂时跳过 legacy check (我们正在 migrate)
        init_args = argparse.Namespace(path=str(path), force=False, allow_legacy=True)
        rc = cmd_init(init_args)
        if rc != 0:
            eprint("[in3-cli] init 失败,migrate 中止")
            return rc
        ws = _require_workspace()

    # 2. mkdir tenant + 拷 cred
    _tenant_dir(ws, alias).mkdir(parents=True, exist_ok=True)
    if legacy_cred and old_cred_data:
        save_master_cred(old_cred_data, ws, alias)
        eprint(f"[in3-cli] migrated master cred → tenants/{alias}/credentials.json")

    # 3. 拷 ~/.ibrain-*/config.json + rename .bak
    for k, d in legacy_configs.items():
        src = d / "config.json"
        if src.exists():
            dst_dir = _tenant_config_dir(ws, alias, k)
            dst_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst_dir / "config.json")
            eprint(f"[in3-cli] migrated {d.name}/config.json → tenants/{alias}/{d.name}/")
        # rename to .bak (后悔药)
        bak = d.with_suffix(d.suffix + ".bak") if d.suffix else Path(str(d) + ".bak")
        try:
            d.rename(bak)
            eprint(f"[in3-cli] renamed {d} → {bak}")
        except OSError as e:
            eprint(f"[in3-cli] rename {d} 失败: {e}")

    # 4. 设 current-tenant
    _save_current_tenant(ws, alias)

    # 5. npm rm -g
    for pkg in legacy:
        eprint(f"[in3-cli] npm rm -g {pkg}")
        subprocess.call(["npm", "rm", "-g", pkg])

    # 6. 删旧主 cred (留 .bak)
    if legacy_cred:
        bak = LEGACY_CRED_FILE.with_suffix(".json.bak")
        try:
            LEGACY_CRED_FILE.rename(bak)
            eprint(f"[in3-cli] renamed {LEGACY_CRED_FILE} → {bak}")
        except OSError as e:
            eprint(f"[in3-cli] rename {LEGACY_CRED_FILE} 失败: {e}")

    print("\n=== migrate done ===")
    return cmd_status(argparse.Namespace(refresh_versions=False))


# ---------- cmd: uninstall -----------------------------------------------------

def cmd_uninstall(args) -> int:
    ws = _load_workspace()
    if ws is None:
        eprint("[in3-cli] no workspace,nothing to uninstall")
        return 0
    print(f"This will delete {ws} (including all 9 module CLIs + all tenant credentials).")
    print("(~/.ibrain-*.bak from previous migrate will NOT be touched)")
    confirm = input("proceed? [y/N]: ").strip().lower()
    if confirm != "y":
        eprint("[in3-cli] aborted")
        return 4
    shutil.rmtree(ws)
    _clear_workspace_pointer()
    eprint(f"[in3-cli] removed {ws}")
    eprint(f"[in3-cli] removed {WORKSPACE_POINTER}")
    return 0


# ---------- cmd: where ---------------------------------------------------------

def cmd_where(args) -> int:
    ws = _load_workspace()
    if ws is None:
        eprint("no workspace; run `init` first")
        return 4
    print(ws)
    return 0


# ---------- cmd: use -----------------------------------------------------------

def cmd_use(args) -> int:
    ws = _require_workspace()
    alias = args.alias
    tenants = _list_tenants(ws)
    if alias not in tenants:
        eprint(f"[in3-cli] tenant '{alias}' not found. Available: {tenants}")
        return 2
    _save_current_tenant(ws, alias)
    eprint(f"[in3-cli] switched to tenant '{alias}'")
    return cmd_status(argparse.Namespace(refresh_versions=False))


# ---------- cmd: tenants -------------------------------------------------------

def cmd_tenants(args) -> int:
    ws = _require_workspace()
    cur = _load_current_tenant(ws)
    tenants = _list_tenants(ws)
    if not tenants:
        print("(no tenants configured yet; run `login` to create one)")
        return 0
    print(f"{'':2s}{'alias':20s}{'env':8s}{'tenant_domain':20s}{'last_login':22s}user")
    for alias in tenants:
        mark = "*" if alias == cur else " "
        cred = load_master_cred(ws, alias) or {}
        env = cred.get("env_label", "?")
        td = cred.get("tenant_domain", "?")
        last = cred.get("last_login_at", "?")[:19]
        user = cred.get("username", "?")
        print(f"{mark} {alias:20s}{env:8s}{td:20s}{last:22s}{user}")
    return 0


# ---------- login --------------------------------------------------------------

def prompt_env() -> tuple[str, str]:
    print("环境:")
    print("  1) prod  — https://apiv3.industics.com/service")
    print("  2) qa    — https://apiv3-qa.industics.com/service")
    print("  3) custom (手输 https://<host>/service)")
    choice = input("选 [1/2/3, 默认 1]: ").strip() or "1"
    if choice == "1":
        return "prod", ENV_HOSTS["prod"]
    if choice == "2":
        return "qa", ENV_HOSTS["qa"]
    if choice == "3":
        host = input("api_host (含 /service): ").strip()
        if not host.startswith("http"):
            raise ValueError("api_host 必须以 http:// 或 https:// 起头")
        return "custom", host
    raise ValueError(f"unknown choice: {choice}")


def fanout_profile_to_modules(ws: Path, alias: str, cred: dict) -> list[str]:
    """对每个已装模块写入 profile (name=alias)。返回成功 onboard 的 mod_key 列表。"""
    onboarded: list[str] = []
    for key, spec in MODULES.items():
        if not is_module_binary_installed(key, ws=ws):
            eprint(f"[in3-cli] {spec['binary']} 未安装,跳过 (用 install 子命令补装)")
            continue
        profile = {
            "name": alias,
            "uaas_host": cred["api_host"],
            "base_url": module_base_url(key, cred["api_host"]),
            "tenant_domain": cred["tenant_domain"],
            "username": cred["username"],
            "encrypted_password": cred["encrypted_password"],
        }
        path = write_module_profile(ws, alias, key, profile)
        path_hint = "via cli add-profile" if path == "cli" else "via direct write"
        eprint(f"[in3-cli] {spec['binary']} ← profile '{alias}' 已落盘 ({path_hint})")
        onboarded.append(key)
    return onboarded


def _decode_jwt_claims(token: str) -> dict:
    """解 JWT payload（不验签，只取身份字段）。失败抛 ValueError。"""
    import base64
    parts = token.split(".")
    if len(parts) < 2:
        raise ValueError("不是合法 JWT（缺 payload 段）")
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload))
    except (ValueError, json.JSONDecodeError) as e:
        raise ValueError(f"JWT payload 解码失败: {e}")


def _now_iso() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def _token_response_fields(body: dict, token: str | None = None) -> dict:
    """从 /uaas/oauth/token 响应 JSON（或显式 token）提取落凭证所需字段。纯函数，便于测。"""
    token = token or body.get("access_token", "")
    fields = {
        "token": token,
        "refresh_token": body.get("refresh_token", ""),
        "username": body.get("sub") or body.get("user_name"),
        "tenant_domain": body.get("tenant_domain"),
        "tenant_id": body.get("tenant_id", ""),
        "user_id": body.get("user_id", ""),
        "fullname": body.get("fullname"),
        "exp": None,
    }
    # 缺的字段从 JWT 补（sub/tenant_domain/exp 等）。
    if token and (not fields["tenant_domain"] or not fields["username"] or fields["exp"] is None):
        try:
            claims = _decode_jwt_claims(token)
        except ValueError:
            claims = {}
        fields["username"] = fields["username"] or claims.get("sub") or claims.get("user_name")
        fields["tenant_domain"] = fields["tenant_domain"] or claims.get("tenant_domain")
        fields["tenant_id"] = fields["tenant_id"] or claims.get("tenant_id", "")
        fields["user_id"] = fields["user_id"] or claims.get("user_id", "")
        fields["fullname"] = fields["fullname"] or claims.get("fullname")
        fields["exp"] = claims.get("exp")
    return fields


def _write_token_login(ws: Path, args, fields: dict, refresh_override: str | None = None) -> int:
    """共享：把提取好的 token 字段落成 token-mode credentials.json + 设当前租户。"""
    token = fields.get("token")
    tenant_domain = fields.get("tenant_domain")
    username = fields.get("username")
    if not token:
        eprint("[in3-cli] 未拿到 access_token")
        return 2
    if not tenant_domain or not username:
        eprint(f"[in3-cli] token 缺 tenant_domain/username，无法落凭证（拿到: {sorted(k for k,v in fields.items() if v)}）")
        return 2

    api_host = getattr(args, "api_host", None)
    env_label = getattr(args, "env", None) or "prod"
    if not api_host:
        api_host = ENV_HOSTS.get(env_label, ENV_HOSTS["prod"])
        env_label = env_label if env_label in ENV_HOSTS else "prod"

    alias = args.alias or tenant_domain
    if alias in _list_tenants(ws) and not getattr(args, "force", False):
        eprint(f"[in3-cli] 租户 '{alias}' 已存在；加 --force 覆盖")
        return 2

    cred = {
        "api_host": api_host,
        "env_label": env_label,
        "tenant_domain": tenant_domain,
        "username": username,
        "auth_mode": "token",
        "access_token": token,
        "refresh_token": refresh_override or fields.get("refresh_token", "") or "",
        "tenant_id": fields.get("tenant_id", ""),
        "user_id": fields.get("user_id", ""),
        "last_login_at": _now_iso(),
    }
    save_master_cred(cred, ws, alias)
    _save_current_tenant(ws, alias)

    exp = fields.get("exp")
    exp_hint = ""
    if isinstance(exp, int):
        import datetime
        exp_dt = datetime.datetime.fromtimestamp(exp, datetime.timezone.utc)
        exp_hint = f"；access token 约于 {exp_dt.isoformat()} 过期（过期后重登或带 refresh_token）"
    print(f"[in3-cli] token 登录成功：{fields.get('fullname') or username} @ {tenant_domain} "
          f"(alias={alias}){exp_hint}")
    print(f"[in3-cli] 现在可 `python3 in3_cli.py run <script.py>`（SDK 用此 token）；"
          f"注意 token 模式不写 8 个模块 CLI 的 profile，`exec`/parity 仍需 password 登录。")
    return 0


def _login_paste_token(ws: Path, args) -> int:
    """token 兜底登录：粘贴浏览器/devtools 抓的 Bearer，解 JWT 落 token-mode 凭证（零安装）。

    适用 SSO/MFA 租户（password-grant 进不去）或不想把口令交给 CLI 的场景。
    """
    if getattr(args, "token_stdin", False):
        raw = sys.stdin.read().strip()
    else:
        raw = input("粘贴 Bearer token（可含 'Bearer ' 前缀）: ").strip()
    token = raw.split(None, 1)[1].strip() if raw.lower().startswith("bearer ") else raw
    if not token:
        eprint("[in3-cli] 未提供 token")
        return 2
    try:
        _decode_jwt_claims(token)  # 早失败：非法 JWT 直接报错
    except ValueError as e:
        eprint(f"[in3-cli] {e}")
        return 2
    fields = _token_response_fields({}, token=token)
    return _write_token_login(ws, args, fields, refresh_override=getattr(args, "refresh_token", None))


_LOGIN_URL_DEFAULT = "https://in3.industics.com"


def _login_browser(ws: Path, args) -> int:
    """③ 自动捕获：起浏览器到登录页，用户登录后从 /uaas/oauth/token 响应抓 token，落 token 凭证。

    Playwright 是重依赖、**lazy import**；缺失则引导安装 + 指回 --paste-token（零安装兜底）。
    """
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
    except ImportError:
        eprint("[in3-cli] 未装 Python Playwright（自动捕获需要）。两条路：")
        eprint("  · 装一次：pip install playwright && python3 -m playwright install chromium")
        eprint("  · 或零安装兜底：python3 in3_cli.py login --paste-token   （自己浏览器登录后粘贴 Bearer）")
        return 6

    url = getattr(args, "url", None) or _LOGIN_URL_DEFAULT
    captured: dict = {}
    timeout_s = int(getattr(args, "timeout", None) or 180)

    def on_response(resp):
        try:
            if "/uaas/oauth/token" in resp.url and resp.status == 200 and "json" in (resp.headers.get("content-type", "")):
                body = resp.json()
                if isinstance(body, dict) and body.get("access_token"):
                    captured.update(body)
        except Exception:
            pass  # 单个响应解析失败不影响整体

    print(f"[in3-cli] 打开浏览器到 {url} …请用【账号密码】在 {timeout_s}s 内完成登录。")
    print("[in3-cli] ⚠ 本模式只抓 password-grant 的 /uaas/oauth/token 响应；飞书扫码 SSO 的 token 端点不同，抓不到 —— 扫码请改 login --paste-token。")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.on("response", on_response)
        try:
            page.goto(url)
        except Exception as e:
            eprint(f"[in3-cli] 打开页面失败：{e}")
            browser.close()
            return 5
        waited = 0
        while not captured.get("access_token") and waited < timeout_s:
            page.wait_for_timeout(1000)
            waited += 1
        browser.close()

    if not captured.get("access_token"):
        eprint(f"[in3-cli] {timeout_s}s 内未捕获到 token。常见原因：① 没在时限内用账号密码登完；② 用了飞书扫码 SSO（本模式只抓 password-grant 的 /uaas/oauth/token，扫码 token 端点不同）。")
        eprint("[in3-cli] 解决：重跑并用【账号密码】登录，或改 login --paste-token（浏览器登录后从 devtools 抓 Bearer 粘贴）。")
        return 5
    fields = _token_response_fields(captured)
    print(f"[in3-cli] 已从登录流捕获 token（含 refresh: {'是' if fields.get('refresh_token') else '否'}）。")
    return _write_token_login(ws, args, fields)


def cmd_login(args) -> int:
    ws = _require_workspace()

    if getattr(args, "browser", False):
        return _login_browser(ws, args)
    if getattr(args, "paste_token", False):
        return _login_paste_token(ws, args)

    # 非交互 flag 解析
    nonint_env = getattr(args, "env", None)
    nonint_api_host = getattr(args, "api_host", None)
    nonint_tenant = getattr(args, "tenant", None)
    nonint_user = getattr(args, "user", None)
    nonint_password = getattr(args, "password", None)
    nonint_password_stdin = getattr(args, "password_stdin", False)
    nonint_force = getattr(args, "force", False)

    if nonint_password is not None and nonint_password_stdin:
        eprint("[in3-cli] --password 与 --password-stdin 互斥")
        return 2

    pwd_provided = nonint_password is not None or nonint_password_stdin
    fully_noninteractive = bool(nonint_env and nonint_tenant and nonint_user and pwd_provided)

    # 早报: stdin 不是 TTY 且必填 flag 缺 → 不要 hang
    if not fully_noninteractive and not sys.stdin.isatty():
        missing = []
        if not nonint_env: missing.append("--env")
        if not nonint_tenant: missing.append("--tenant")
        if not nonint_user: missing.append("--user")
        if not pwd_provided: missing.append("--password / --password-stdin")
        eprint(f"[in3-cli] stdin 不是 TTY (sandbox/pipe?)，且缺 flag: {' '.join(missing)}")
        eprint("[in3-cli] 请补齐 args 跑非交互模式,例:")
        eprint("[in3-cli]   printf '%s' 'PASS' | python3 ... login <alias> --env prod --tenant X --user Y --password-stdin")
        return 2

    print("=== in3-cli login ===")
    if fully_noninteractive:
        print("(non-interactive mode: 用 args 喂凭证)")
    else:
        print("将一次性收 env/tenant/account/password,加密后落到 workspace 内对应 tenant 目录")
        print("明文密码不会被存,只在内存里走一遍加密就丢弃。\n")

    # 解析 env_label + api_host
    if nonint_env:
        env_label = nonint_env
        if nonint_env == "prod":
            api_host = ENV_HOSTS["prod"]
        elif nonint_env == "qa":
            api_host = ENV_HOSTS["qa"]
        elif nonint_env == "custom":
            if not nonint_api_host or not nonint_api_host.startswith("http"):
                eprint("[in3-cli] --env custom 需要 --api-host=https://.../service")
                return 2
            api_host = nonint_api_host
        else:
            eprint(f"[in3-cli] 未知 --env: {nonint_env}")
            return 2
    else:
        try:
            env_label, api_host = prompt_env()
        except ValueError as e:
            eprint(f"[in3-cli] {e}")
            return 2

    tenant = nonint_tenant.strip() if nonint_tenant else input("tenant_domain: ").strip()
    if not tenant:
        eprint("[in3-cli] tenant_domain 不能空")
        return 2

    alias = args.alias or tenant

    # alias 已存在 → 非交互/--force 自动覆盖,交互模式问 y/N
    if alias in _list_tenants(ws):
        if fully_noninteractive or nonint_force:
            eprint(f"[in3-cli] tenant '{alias}' 已存在,按非交互/--force 自动覆盖")
        else:
            ans = input(f"tenant '{alias}' 已配置,override existing? [y/N]: ").strip().lower()
            if ans != "y":
                eprint("[in3-cli] aborted")
                return 4

    user_short = nonint_user.strip() if nonint_user else input(f"username (短形式,会自动拼成 corp:<user>@{tenant}): ").strip()
    if not user_short:
        eprint("[in3-cli] username 不能空")
        return 2
    username_full = user_short if user_short.startswith("corp:") else f"corp:{user_short}@{tenant}"

    if nonint_password is not None:
        plaintext = nonint_password
    elif nonint_password_stdin:
        plaintext = sys.stdin.readline().rstrip("\r\n")
    else:
        plaintext = getpass.getpass("password (明文,不会被存储): ")
    if not plaintext:
        eprint("[in3-cli] password 不能空")
        return 2

    try:
        cipher = aes_encrypt(plaintext)
    except RuntimeError as e:
        eprint(f"[in3-cli] 加密失败: {e}")
        return 1
    finally:
        plaintext = ""

    cred = {
        "api_host": api_host,
        "env_label": env_label,
        "tenant_domain": tenant,
        "username": username_full,
        "encrypted_password": cipher,
        "modules_onboarded": [],
        "last_login_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    onboarded = fanout_profile_to_modules(ws, alias, cred)
    cred["modules_onboarded"] = onboarded
    save_master_cred(cred, ws, alias)
    _save_current_tenant(ws, alias)

    if not onboarded:
        eprint("\n[in3-cli] ⚠ 没有任何模块被 onboard (binary 都未装)。跑 `install-all` 装齐后再 login。")
        return 0

    print("\n=== auto smoke test ===")
    return run_test_all(ws, alias)


# ---------- sync ---------------------------------------------------------------

def cmd_sync(args) -> int:
    ws = _require_workspace()
    alias = args.alias or _require_current_tenant(ws)
    cred = load_master_cred(ws, alias)
    if not cred:
        eprint(f"[in3-cli] tenant '{alias}' 没有 master cred,先跑 `login {alias}`")
        return 4
    onboarded = fanout_profile_to_modules(ws, alias, cred)
    cred["modules_onboarded"] = onboarded
    save_master_cred(cred, ws, alias)
    if not onboarded:
        eprint("[in3-cli] ⚠ 没有已装模块,先 `install-all`")
        return 0
    eprint(f"[in3-cli] 同步完成,tenant={alias},onboarded={onboarded}")
    return run_test_all(ws, alias)


# ---------- logout (强制 tenant 参数,避免误删) ----------------------------------

def cmd_logout(args) -> int:
    ws = _require_workspace()
    alias = args.alias
    tenants = _list_tenants(ws)
    if alias not in tenants:
        eprint(f"[in3-cli] tenant '{alias}' not found. Available: {tenants}")
        return 2
    cred_p = _tenant_cred_path(ws, alias)
    removed = []
    if cred_p.exists():
        cred_p.unlink()
        removed.append(str(cred_p))
    for key in MODULES:
        if remove_module_profile(ws, alias, key):
            removed.append(f"{MODULES[key]['binary']} profile '{alias}'")
    # 删掉空目录(每个 .ibrain-<mod>/config.json 已没了)
    for key in MODULES:
        d = _tenant_config_dir(ws, alias, key)
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    td = _tenant_dir(ws, alias)
    if td.is_dir() and not any(td.iterdir()):
        td.rmdir()
        removed.append(str(td))
    # 如果删的是 current,切到剩余 tenant 中的第一个,或清空
    if _load_current_tenant(ws) == alias:
        remaining = _list_tenants(ws)
        if remaining:
            _save_current_tenant(ws, remaining[0])
            eprint(f"[in3-cli] current-tenant 自动切到 '{remaining[0]}'")
        else:
            _clear_current_tenant(ws)
            eprint("[in3-cli] no tenants left, current-tenant cleared")
    for r in removed:
        eprint(f"[in3-cli] removed {r}")
    if not removed:
        eprint(f"[in3-cli] tenant '{alias}' 已经无 cred/profile")
    return 0


# ---------- test ---------------------------------------------------------------

def _resolve_smoke_cmd(ws: Path, alias: str, mod_key: str) -> list[str]:
    """返回该模块 smoke 实际要跑的 argv(不含 binary)。

    identity 特殊处理:把 `roles list` 自限定成 `roles list --user-id <self>`,
    使 smoke 验证「当前用户能查自己的角色」(每个登录用户都有权),而不是
    「列全租户所有角色」(需后台管理员权限,普通账号 404)。拿不到 user_id
    时退回裸命令,best-effort。
    """
    spec = MODULES[mod_key]
    cmd = list(spec["smoke_cmd"])
    if mod_key == "identity":
        user_id = _identity_self_user_id(ws, alias)
        if user_id and "--user-id" not in cmd:
            cmd += ["--user-id", user_id]
    return cmd


def run_smoke(ws: Path, alias: str, mod_key: str) -> tuple[bool, str]:
    spec = MODULES[mod_key]
    binary = _resolve_binary(ws, mod_key)
    if not binary.exists():
        return False, f"{spec['binary']} not installed"
    cmd = [str(binary), *_resolve_smoke_cmd(ws, alias, mod_key)]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, check=False,
        env=_build_env(ws, alias),
    )
    raw = (proc.stdout or proc.stderr or "").strip()
    sample = raw[:200]
    if proc.returncode != 0:
        return False, sample
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and "error" in parsed:
            return False, sample
    except json.JSONDecodeError:
        pass
    return True, sample


def run_test_all(ws: Path, alias: str) -> int:
    overall_ok = True
    for key, spec in MODULES.items():
        if not is_module_binary_installed(key, ws=ws) or not module_profile_exists(ws, alias, key):
            print(f"  {key}: SKIP (not installed or no '{alias}' profile)")
            continue
        ok, sample = run_smoke(ws, alias, key)
        if ok:
            print(f"  {key}: PASS — {spec['smoke_desc']}")
        else:
            print(f"  {key}: FAIL — {spec['smoke_desc']}")
            print(f"        sample: {sample}")
            overall_ok = False
    return 0 if overall_ok else 13


def cmd_test(args) -> int:
    mod = args.module
    if mod not in MODULES:
        eprint(f"[in3-cli] unknown module '{mod}'; known: {list(MODULES)}")
        return 2
    ws = _require_workspace()
    alias = _require_current_tenant(ws)
    spec = MODULES[mod]
    ok, sample = run_smoke(ws, alias, mod)
    result = {
        "module": mod,
        "tenant": alias,
        "smoke_cmd": f"{spec['binary']} {' '.join(_resolve_smoke_cmd(ws, alias, mod))}",
        "smoke_desc": spec["smoke_desc"],
        "ok": ok,
        "sample": sample,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if ok else 13


def cmd_test_all(args) -> int:
    ws = _require_workspace()
    alias = _require_current_tenant(ws)
    return run_test_all(ws, alias)


# ---------- cmd: exec ----------------------------------------------------------

def cmd_exec(args) -> int:
    """转发一条命令给指定 module CLI,自动注入 workspace binary + 当前 tenant 的 9 个 env var。

    用法: in3_cli.py exec [--tenant <alias>] <mod> <cli_args...>
    示例: in3_cli.py exec mm purchase-order list --max 5
       == <ws>/node_modules/.bin/ibrain-mm-cli purchase-order list --max 5
          (env IBRAIN_MM_CONFIG_DIR=... + 8 个其他 module env)

    --tenant 为可选的**单次**租户覆盖(须置于 module 之前),不写当前 current-tenant.json
    全局状态——用于跨租户对照(如 parity 双侧锁同一 tenant)。缺省时沿用 current-tenant。

    Agent 在调任何 module CLI 时都该走这个入口,不要直接调裸 binary
    (PATH 里没有,且没设 env 会读到错 tenant)。
    """
    ws = _require_workspace()
    alias = getattr(args, "tenant", None) or _require_current_tenant(ws)
    if getattr(args, "tenant", None) and not _tenant_cred_path(ws, alias).exists():
        eprint(f"[in3-cli] tenant '{alias}' not found in workspace; run `tenants` to list")
        return 4
    mod = args.module
    if mod not in MODULES:
        eprint(f"[in3-cli] unknown module '{mod}'; known: {list(MODULES)}")
        return 2
    binary = _resolve_binary(ws, mod)
    if not binary.exists():
        eprint(f"[in3-cli] {MODULES[mod]['binary']} not installed in workspace; run `install-all` or `install {mod}`")
        return 5

    cmd = [str(binary), *args.cli_args]
    return subprocess.call(cmd, env=_build_env(ws, alias))


# ---------- cmd: run (C 执行壳) ------------------------------------------------

def cmd_run(args) -> int:
    """在子进程跑一段 `import in3_client` 的 Python，注入当前租户凭证/env + SDK 到 PYTHONPATH。

    用法: in3_cli.py run <script.py> [--timeout N] [-- 透传给脚本的参数]
       or: in3_cli.py run --code "import in3_client; ..."
    坑层/超时/截断/审计全在传输无关执行核 in3_run.execute 里（C→B 零返工）。
    """
    import in3_run  # lazy: dispatcher 本体不依赖它

    ws = _require_workspace()
    alias = _require_current_tenant(ws)

    script = getattr(args, "script", None)
    code = getattr(args, "code", None)
    if not script and not code:
        eprint("[in3-cli] run: 需要 <script.py> 或 --code")
        return 2
    if script and code:
        eprint("[in3-cli] run: <script> 与 --code 互斥")
        return 2

    # 透传给脚本的参数：REMAINDER 里去掉可选的前导 '--'
    script_args = list(getattr(args, "args", None) or [])
    if script_args and script_args[0] == "--":
        script_args = script_args[1:]

    # PYTHONPATH 前置：① skill 自带的 SDK 包目录（纯 Python，无需安装）② workspace 的 python-packages
    sdk_dir = SKILL_DIR / "sdk"
    pkg_dir = ws / "python-packages"

    ctx = in3_run.ExecuteContext(
        workspace=ws,
        tenant_alias=alias,
        env=_build_env(ws, alias),
        pythonpath=[str(sdk_dir), str(pkg_dir)],
        timeout_s=getattr(args, "timeout", in3_run.DEFAULT_TIMEOUT_S),
        script_args=script_args,
    )
    result = in3_run.execute(script, code, ctx)

    if result.stdout:
        sys.stdout.write(result.stdout)
        if not result.stdout.endswith("\n"):
            sys.stdout.write("\n")
    if result.stderr:
        sys.stderr.write(result.stderr)
        if not result.stderr.endswith("\n"):
            sys.stderr.write("\n")
    return result.exit_code


# ---------- cmd: audit ---------------------------------------------------------

def cmd_audit(args) -> int:
    """列出最近 N 条 run 审计记录的摘要（不含脚本源全文，避免刷屏）。"""
    ws = _require_workspace()
    audit_dir = ws / "audit"
    if not audit_dir.is_dir():
        print("(还没有审计记录；先 `run` 一个脚本)")
        return 0
    files = sorted(audit_dir.glob("*.json"), reverse=True)[: args.limit]
    if not files:
        print("(audit 目录为空)")
        return 0
    rows = []
    for f in files:
        try:
            d = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        src = (d.get("script_source") or "").strip().replace("\n", " ")
        rows.append({
            "file": f.name,
            "tenant": d.get("tenant"),
            "exit_code": d.get("exit_code"),
            "timed_out": d.get("timed_out"),
            "truncated": d.get("output_truncated"),
            "duration_s": d.get("duration_s"),
            "script_head": (src[:48] + "…") if len(src) > 48 else src,
        })
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


# ---------- help ---------------------------------------------------------------

HELP_TEXT = """\
in3-cli — IN3 产品族 workspace-scoped 多租户 CLI 调度器

第一次使用
----------
  python3 .../in3_cli.py init      # 创建 ~/in3-workspace, 本地装 9 个 CLI
  python3 .../in3_cli.py login     # 交互输 env/tenant/user/password
  python3 .../in3_cli.py status    # 验证 8 个模块都 OK

切租户
------
  python3 .../in3_cli.py login acme    # 加 'acme' 租户(交互输)
  python3 .../in3_cli.py tenants       # 列所有租户
  python3 .../in3_cli.py use indx      # 切回 indx

诊断 / 卸载
-----------
  python3 .../in3_cli.py doctor        # 体检
  python3 .../in3_cli.py migrate       # legacy 全局安装 → workspace
  python3 .../in3_cli.py uninstall     # 删 workspace (~/.bak 不动)
  python3 .../in3_cli.py where         # print workspace path

支持的模块
----------
  mm  ibrain-mm-cli      物料管理: PO/PR/合同/BOM/供应商
  wm  ibrain-wm-cli      仓储管理: 库存/收发/盘点
  md  in-mom-md-cli      主数据: 物料/类目/单位/工厂
  pp  ibrain-pp-cli      生产计划: 工单/MRP/排产
  qm  ibrain-qm-cli      质量管理: 检验批/检验计划
  sd  ibrain-sd-cli      销售: SO/合同/出货
  cr  in-mom-cr-cli      客户关系: 服务记录
  fn  ibrain-mom-fn-cli  财务: 公司代码/科目
  identity  ibrain-identity-cli  身份: 用户/角色/权限/组织

自然语言查询
------------
直接问 Claude/Codex 业务问题。skill 会判断走哪个模块、调对应 CLI、聚合结果。
"""


# ---------- cmd: mcp (v2 MCP server, stdio JSON-RPC) ---------------------------

def cmd_mcp(args) -> int:
    """启动 MCP server（stdio JSON-RPC），对外暴露单一 execute_code 工具（v2）。

    把传输无关执行核 in3_run.execute 绑成 executor 闭包（复用 cmd_run 同款 ctx 装配：
    租户凭证 + 9 env + SDK PYTHONPATH），经 in3_mcp.serve_stdio 服务。护栏（超时/
    64KB 截断/审计）全在执行核里，与 run 一致。

    多租户 session-scoped 路由（v2）：常驻 server 不靠全局 current-tenant，execute_code
    每请求可带 tenant 入参 → in3_mcp.resolve_tenant 解析（省略回退启动时的 active tenant，
    未知/无默认返错误结果不崩）→ 按解析出的 tenant 装配 ctx（各自的凭证 + 9 env 隔离）。
    """
    from types import SimpleNamespace
    import in3_run   # lazy: dispatcher 本体零依赖启动
    import in3_mcp   # lazy

    ws = _require_workspace()
    default_alias = _load_current_tenant(ws)  # 可 None：纯靠每请求 tenant 入参也行
    sdk_dir = SKILL_DIR / "sdk"
    pkg_dir = ws / "python-packages"

    def executor(code, timeout, tenant=None):
        alias, err = in3_mcp.resolve_tenant(tenant, default_alias, _list_tenants(ws))
        if err:
            # 路由失败：返回 ExecuteResult 鸭子类型的错误结果（isError 由 exit_code 决定），不崩 server
            return SimpleNamespace(stdout="", stderr=f"[in3-cli mcp] {err}",
                                   exit_code=2, truncated=False, duration_s=0.0)
        ctx = in3_run.ExecuteContext(
            workspace=ws,
            tenant_alias=alias,
            env=_build_env(ws, alias),
            pythonpath=[str(sdk_dir), str(pkg_dir)],
            timeout_s=int(timeout) if timeout else in3_run.DEFAULT_TIMEOUT_S,
        )
        return in3_run.execute(None, code, ctx)

    if getattr(args, "http", None):
        host, port = in3_mcp.parse_http_addr(args.http)
        print(f"[in3-cli mcp] Streamable HTTP transport: http://{host}:{port}/mcp"
              f"（单用户/本地凭证；多用户托管见 REMOTE-HOSTING-DESIGN 门禁 B/C/D）", file=sys.stderr)
        in3_mcp.serve_http(executor, host=host, port=port)
    else:
        in3_mcp.serve_stdio(executor)
    return 0


def cmd_help(args) -> int:
    print(HELP_TEXT)
    return 0


def cmd_version(args) -> int:
    print(json.dumps({"dispatcher_version": DISPATCHER_VERSION, "features": DISPATCHER_FEATURES},
                     ensure_ascii=False))
    return 0


# ---------- main ---------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="in3_cli", description="IN3 workspace-scoped 多租户 CLI 调度器")
    sub = p.add_subparsers(dest="cmd", required=True)

    # status
    st = sub.add_parser("status", help="JSON 输出 workspace/tenant/9 模块状态")
    st.add_argument("--refresh-versions", action="store_true", help="强制刷新版本缓存")
    st.set_defaults(func=cmd_status)

    # init
    init = sub.add_parser("init", help="创建独立 workspace,本地装 9 个 CLI")
    init.add_argument("--path", help=f"workspace 路径 (默认 {DEFAULT_WORKSPACE})", default=None)
    init.add_argument("--force", action="store_true", help="如已存在则强制删重建")
    init.add_argument("--allow-legacy", action="store_true",
                      help="即使检测到全局 @industics/* 也强行 init (一般不需要)")
    init.set_defaults(func=cmd_init)

    # doctor
    sub.add_parser("doctor", help="检查 workspace + legacy + Node + registry 健康").set_defaults(func=cmd_doctor)

    # migrate
    sub.add_parser("migrate", help="legacy 全局安装 → workspace 一键迁移").set_defaults(func=cmd_migrate)

    # uninstall
    sub.add_parser("uninstall", help="删 workspace + pointer (二次确认)").set_defaults(func=cmd_uninstall)

    # where
    sub.add_parser("where", help="print workspace 路径").set_defaults(func=cmd_where)

    # use
    use = sub.add_parser("use", help="切当前 active tenant")
    use.add_argument("alias", help="tenant alias (如 indx)")
    use.set_defaults(func=cmd_use)

    # tenants
    sub.add_parser("tenants", help="列出所有租户 + 标当前").set_defaults(func=cmd_tenants)

    # login / sync / logout
    lg = sub.add_parser("login", help="onboarding (env/tenant/user/password); 落地后跑 smoke. 全部 flag 齐 → 非交互; 缺则交互")
    lg.add_argument("alias", nargs="?", default=None, help="可选 tenant alias (默认用 tenant_domain)")
    lg.add_argument("--env", choices=["prod", "qa", "custom"], default=None, help="环境标签 (非交互)")
    lg.add_argument("--api-host", default=None, help="--env custom 时的 https://.../service")
    lg.add_argument("--tenant", default=None, help="tenant_domain (非交互)")
    lg.add_argument("--user", default=None, help="username 短形式或 corp:X@Y (非交互)")
    lg.add_argument("--password", default=None, help="明文密码 (非交互, 进 ps/history 不推荐)")
    lg.add_argument("--password-stdin", action="store_true", help="从 stdin 读密码 (非交互, 推荐)")
    lg.add_argument("--force", action="store_true", help="alias 已存在时自动覆盖")
    lg.add_argument("--paste-token", action="store_true",
                    help="token 兜底：粘贴浏览器抓的 Bearer（SSO/MFA 租户用），解 JWT 落 token 模式凭证")
    lg.add_argument("--token-stdin", action="store_true", help="--paste-token 时从 stdin 读 token（非交互）")
    lg.add_argument("--refresh-token", default=None, help="--paste-token 时可选带 refresh token（续期用）")
    lg.add_argument("--browser", action="store_true",
                    help="自动捕获：起浏览器到登录页，登录后从网络流抓 token（需 Python Playwright）")
    lg.add_argument("--url", default=None, help="--browser 的登录页 URL（默认 https://in3.industics.com）")
    lg.add_argument("--timeout", type=int, default=None, help="--browser 等待登录的秒数（默认 180）")
    lg.set_defaults(func=cmd_login)

    sy = sub.add_parser("sync", help="复用主凭证给该 tenant 重新 fanout 9 模块 profile")
    sy.add_argument("alias", nargs="?", default=None, help="可选 tenant alias (默认 current)")
    sy.set_defaults(func=cmd_sync)

    lo = sub.add_parser("logout", help="删指定 tenant 的 cred + profile (必须传 alias)")
    lo.add_argument("alias", help="tenant alias")
    lo.set_defaults(func=cmd_logout)

    # install / install-all / upgrade / upgrade-all
    inst = sub.add_parser("install", help="装单个模块 (workspace 内)")
    inst.add_argument("module", help="模块 key (例 mm)")
    inst.set_defaults(func=cmd_install)

    sub.add_parser("install-all", help="按 lock 重装 workspace 全套 (npm ci)").set_defaults(func=cmd_install_all)

    up = sub.add_parser("upgrade", help="升级单个模块到 latest (脱离 lock baseline)")
    up.add_argument("module", help="模块 key")
    up.set_defaults(func=cmd_upgrade)

    sub.add_parser("upgrade-all", help="升级所有已装模块到 latest").set_defaults(func=cmd_upgrade_all)

    # pack-vendor (maintainer)
    pv = sub.add_parser("pack-vendor", help="(维护者) 把所有模块 latest 重新 npm pack 到 vendor/")
    pv.add_argument("--registry", default="http://npm.industics.cn", help="npm registry URL")
    pv.set_defaults(func=cmd_pack_vendor)

    # test
    t = sub.add_parser("test", help="跑单个模块的 smoke")
    t.add_argument("module", help="模块 key")
    t.set_defaults(func=cmd_test)

    sub.add_parser("test-all", help="跑所有模块的 smoke (当前 tenant)").set_defaults(func=cmd_test_all)

    ex = sub.add_parser("exec", help="跑某模块 CLI 命令(自动注入 workspace binary + 当前 tenant env)")
    ex.add_argument("--tenant", default=None,
                    help="单次租户覆盖 alias(须置于 module 之前;不改 current-tenant 全局状态)")
    ex.add_argument("module", help="模块 key (例 mm)")
    ex.add_argument("cli_args", nargs=argparse.REMAINDER, help="转发给 binary 的所有参数")
    ex.set_defaults(func=cmd_exec)

    # run (C 执行壳)
    rn = sub.add_parser("run", help="跑一段 import in3_client 的 Python 脚本(注入凭证/env + SDK)")
    rn.add_argument("script", nargs="?", default=None, help="脚本路径 (与 --code 互斥)")
    rn.add_argument("--code", default=None, help="内联代码 (与 script 互斥)")
    rn.add_argument("--timeout", type=int, default=300, help="子进程超时秒数 (默认 300, 超时→退出码 124)")
    rn.add_argument("args", nargs=argparse.REMAINDER, help="透传给脚本的参数 (前置 -- 分隔)")
    rn.set_defaults(func=cmd_run)

    # audit
    au = sub.add_parser("audit", help="列出最近的 run 审计记录摘要")
    au.add_argument("--limit", type=int, default=5, help="显示最近几条 (默认 5)")
    au.set_defaults(func=cmd_audit)

    _mcp = sub.add_parser("mcp", help="启动 MCP server (JSON-RPC, 暴露 execute_code; v2)")
    _mcp.add_argument("--http", nargs="?", const="127.0.0.1:8765", default=None, metavar="HOST:PORT",
                      help="改用 Streamable HTTP transport (默认 127.0.0.1:8765/mcp; 省略走 stdio)。单用户/本地凭证")
    _mcp.set_defaults(func=cmd_mcp)
    sub.add_parser("help", help="用户向 quick start").set_defaults(func=cmd_help)
    sub.add_parser("version", help="print dispatcher 版本 + 新能力清单（区分新旧 skill）").set_defaults(func=cmd_version)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        eprint("\n[in3-cli] 用户中止")
        return 4


if __name__ == "__main__":
    sys.exit(main())
