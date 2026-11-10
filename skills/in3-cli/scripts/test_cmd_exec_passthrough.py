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
