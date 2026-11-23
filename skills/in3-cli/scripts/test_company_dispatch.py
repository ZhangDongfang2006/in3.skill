"""公司参数只路由到支持的 SDK 查询，不运行旧 npm 或改默认租户。"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import in3_cli


def test_explicit_company_uses_sdk_without_npm_and_preserves_alias(tmp_path):
    root = tmp_path / 'config' / 'tenants' / 'customer'
    root.mkdir(parents=True)
    (root / 'credentials.json').write_text('{}')
    args = in3_cli.build_parser().parse_args([
        'exec', '--tenant', 'customer', '--company', 'CO02',
        'mm', 'purchase-requirement', 'list', '--size', '3',
    ])
    with patch('in3_cli._load_workspace', return_value=tmp_path), \
         patch('subprocess.call', return_value=0) as call:
        assert in3_cli.cmd_exec(args) == 0
    command = call.call_args.args[0]
    assert command[:3] == [sys.executable, '-m', 'in3_client.organization_cli']
    assert command[-7:] == ['--company', 'CO02', 'mm', 'purchase-requirement', 'list', '--size', '3']
    assert '--tenant' in command and 'customer' in command
    assert not (tmp_path / 'config' / 'current-tenant.json').exists()


def test_unsupported_company_scope_returns_json_without_querying(capsys):
    args = in3_cli.build_parser().parse_args(['exec', '--company', 'CO02', 'wm', 'stock', 'bin'])
    with patch('subprocess.call') as call:
        assert in3_cli.cmd_exec(args) == 4
    call.assert_not_called()
    assert json.loads(capsys.readouterr().out)['error']['type'] == 'VALIDATION'
