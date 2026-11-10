"""identity smoke 自限定回归测试。

裸 `roles list` 是「列全租户所有角色」,需后台管理员权限,普通账号被后端 404 拒绝。
smoke 必须自限定成 `roles list --user-id <self>`(查自己角色,每个登录用户都有权)。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import in3_cli  # noqa: E402


def _seed_identity_token(ws: Path, alias: str, user_id: str | None) -> None:
    cfg_dir = in3_cli._tenant_config_dir(ws, alias, "identity")
    cfg_dir.mkdir(parents=True, exist_ok=True)
    entry = {"access_token": "AT", "tenant_domain": alias}
    if user_id is not None:
        entry["user_id"] = user_id
    (cfg_dir / "credentials.json").write_text(json.dumps({alias: entry}))


def test_identity_smoke_injects_self_user_id(tmp_path):
    _seed_identity_token(tmp_path, "indx", "u-self-123")
    cmd = in3_cli._resolve_smoke_cmd(tmp_path, "indx", "identity")
    assert cmd == ["roles", "list", "--user-id", "u-self-123"]


def test_identity_smoke_falls_back_to_bare_without_user_id(tmp_path):
    # token 缓存里没有 user_id（旧格式）→ best-effort 退回裸命令,不注入空 --user-id
    _seed_identity_token(tmp_path, "indx", None)
    cmd = in3_cli._resolve_smoke_cmd(tmp_path, "indx", "identity")
    assert cmd == ["roles", "list"]


def test_identity_smoke_falls_back_when_no_token_cache(tmp_path):
    cmd = in3_cli._resolve_smoke_cmd(tmp_path, "indx", "identity")
    assert cmd == ["roles", "list"]


def test_non_identity_smoke_unchanged(tmp_path):
    # 其它模块不受影响,原样返回 smoke_cmd
    assert in3_cli._resolve_smoke_cmd(tmp_path, "indx", "mm") == ["currency", "list"]
    assert in3_cli._resolve_smoke_cmd(tmp_path, "indx", "fn") == ["company-code", "list"]
