"""cmd_exec must forward module output without local price filtering."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import in3_cli


@pytest.fixture
def mock_workspace(tmp_path):
    alias = "test-tenant"
    tenant_dir = tmp_path / "config" / "tenants" / alias
    tenant_dir.mkdir(parents=True)
    (tenant_dir / "credentials.json").write_text(json.dumps({"username": "developer"}))
    bin_dir = tmp_path / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    for mod_info in in3_cli.MODULES.values():
        (bin_dir / mod_info["binary"]).touch()
    return tmp_path, alias


def _args(module, cli_args):
    return SimpleNamespace(
        tenant=None,
        module=module,
        cli_args=cli_args,
    )


@pytest.mark.parametrize(
    ("module", "cli_args"),
    [
        ("fn", ["company-code", "list"]),
        ("mm", ["info-record", "list"]),
        ("mm", ["quotation", "list"]),
        ("sd", ["sd-info-record", "list"]),
        ("sd", ["quotation", "list"]),
        ("cr", ["fee", "list"]),
        ("sd", ["sales-order", "list"]),
    ],
)
def test_price_bearing_commands_are_forwarded_directly(mock_workspace, module, cli_args):
    ws, alias = mock_workspace
    with patch("in3_cli._require_workspace", return_value=ws), \
         patch("in3_cli._require_current_tenant", return_value=alias), \
         patch("subprocess.call", return_value=0) as call:
        rc = in3_cli.cmd_exec(_args(module, cli_args))

    assert rc == 0
    call.assert_called_once()
    forwarded = call.call_args.args[0]
    assert forwarded[1:] == cli_args


def test_exec_source_no_longer_depends_on_price_filter_modules():
    source = Path(in3_cli.__file__).read_text()

    assert "from price_privilege" not in source
    assert "from price_scrubber" not in source
    assert "PRIVILEGE_DENIED_RESPONSE" not in source


def test_sf_exec_uses_sdk_without_npm_and_keeps_tenant_override(mock_workspace):
    ws, alias = mock_workspace
    args = _args("sf", ["sim-issue", "list", "--all"])
    args.tenant = alias
    with patch("in3_cli._load_workspace", return_value=ws), \
         patch("subprocess.call", return_value=0) as call:
        assert in3_cli.cmd_exec(args) == 0
    command = call.call_args.args[0]
    assert command[:3] == [sys.executable, "-m", "in3_client.sf_cli"]
    assert command[3:7] == ["--workspace", str(ws), "--tenant", alias]
    assert command[7:] == args.cli_args
    assert str(in3_cli.SKILL_DIR / "sdk") in call.call_args.kwargs["env"]["PYTHONPATH"]


def test_sf_schema_does_not_require_workspace():
    with patch("in3_cli._load_workspace", side_effect=AssertionError("不应读取 workspace")), \
         patch("subprocess.call", return_value=0) as call:
        assert in3_cli.cmd_exec(_args("sf", ["__schema"])) == 0
    assert call.call_args.args[0][-1] == "__schema"


def test_sf_unknown_tenant_is_rejected(mock_workspace):
    ws, _ = mock_workspace
    args = _args("sf", ["sim-issue", "list"])
    args.tenant = "missing"
    with patch("in3_cli._load_workspace", return_value=ws), \
         patch("subprocess.call") as call:
        assert in3_cli.cmd_exec(args) == 4
    call.assert_not_called()


def test_sf_missing_workspace_returns_json_validation_error(capsys):
    with patch("in3_cli._load_workspace", return_value=None):
        assert in3_cli.cmd_exec(_args("sf", ["sim-issue", "list"])) == 4
    assert json.loads(capsys.readouterr().out)["error"]["type"] == "VALIDATION"


def test_sf_missing_current_tenant_returns_json_validation_error(mock_workspace, capsys):
    ws, _ = mock_workspace
    with patch("in3_cli._load_workspace", return_value=ws), \
         patch("in3_cli._load_current_tenant", return_value=None):
        assert in3_cli.cmd_exec(_args("sf", ["sim-issue", "list"])) == 4
    assert json.loads(capsys.readouterr().out)["error"]["type"] == "VALIDATION"


def test_token_exec_rejects_business_query_without_running_stale_profile(mock_workspace, capsys):
    ws, alias = mock_workspace
    in3_cli.save_master_cred({"auth_mode": "token", "access_token": "AT"}, ws, alias)
    with patch("in3_cli._require_workspace", return_value=ws), \
         patch("in3_cli._require_current_tenant", return_value=alias), \
         patch("subprocess.call") as call:
        assert in3_cli.cmd_exec(_args("md", ["currency", "list"])) != 0
    call.assert_not_called()
    assert json.loads(capsys.readouterr().out)["error"]["type"] == "AUTH"


@pytest.mark.parametrize("cli_args", [["__schema"], ["--capability"], ["--version"], ["--help"]])
def test_token_exec_still_allows_introspection(mock_workspace, cli_args):
    ws, alias = mock_workspace
    in3_cli.save_master_cred({"auth_mode": "token", "access_token": "AT"}, ws, alias)
    with patch("in3_cli._require_workspace", return_value=ws), \
         patch("in3_cli._require_current_tenant", return_value=alias), \
         patch("subprocess.call", return_value=0) as call:
        assert in3_cli.cmd_exec(_args("md", cli_args)) == 0
    call.assert_called_once()


def test_token_smoke_and_sync_do_not_use_password_profiles(mock_workspace):
    ws, alias = mock_workspace
    in3_cli.save_master_cred({"auth_mode": "token", "access_token": "AT"}, ws, alias)
    with patch("subprocess.run") as call:
        assert in3_cli.run_smoke(ws, alias, "md")[0] is False
    call.assert_not_called()
    with patch("in3_cli._require_workspace", return_value=ws), \
         patch("in3_cli.fanout_profile_to_modules") as fanout:
        assert in3_cli.cmd_sync(SimpleNamespace(alias=alias)) != 0
    fanout.assert_not_called()
