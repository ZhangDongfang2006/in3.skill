"""公司范围 CLI 复用 SDK，正确输出总数、上限和 JSON 错误。"""
import json
from types import SimpleNamespace

from in3_client import organization_cli
from in3_client.entities.mm import PurchaseRequirementEntity
from test_company_scope import wire


def test_cli_pr_company_filter_maps_to_plant_and_reports_snake_case_total(monkeypatch, capsys):
    entity, backend = wire(PurchaseRequirementEntity)
    backend.plants = [{'id': 'p2', 'company_id': 'c2'}]
    backend.rows['p2'] = [{'id': 'pr', 'company_id': 'c2', 'plant_id': 'p2'}]
    client = SimpleNamespace(mm=SimpleNamespace(purchase_requirement=entity))
    monkeypatch.setattr(organization_cli, 'IN3', lambda **kwargs: client)
    rc = organization_cli.main(['--company', 'CO02', 'mm', 'purchase-requirement', 'list'])
    result = json.loads(capsys.readouterr().out)
    assert rc == 0 and result['total'] == 1
    assert result['items'][0]['company_id'] == 'c2'


def test_cli_unknown_filter_and_invalid_options_return_json(monkeypatch, capsys):
    monkeypatch.setattr(organization_cli, 'IN3', lambda **kwargs: (_ for _ in ()).throw(
        AssertionError('参数错误不应读取凭证')))
    for options in (['--all', '--page', '0'], ['--size', '0'], ['--filter', 'bad'],
                    ['--filter', 'with_data_role=false'], ['--max', '1']):
        rc = organization_cli.main(['--company', 'CO02', 'sd', 'sales-order', 'list', *options])
        assert rc == 4
        assert json.loads(capsys.readouterr().out)['error']['type'] == 'VALIDATION'


def test_cli_scope_error_does_not_output_partial_results(monkeypatch, capsys):
    entity, backend = wire(PurchaseRequirementEntity)
    backend.plants = [{'id': 'p2', 'company_id': 'c2'}, {'id': 'p3', 'company_id': 'c2'}]
    backend.rows = {'p2': [{'id': 'good', 'company_id': 'c2', 'plant_id': 'p2'}],
                    'p3': [{'id': 'wrong', 'company_id': 'c1', 'plant_id': 'p3'}]}
    monkeypatch.setattr(organization_cli, 'IN3', lambda **kwargs: SimpleNamespace(
        mm=SimpleNamespace(purchase_requirement=entity)))
    rc = organization_cli.main(['--company', 'CO02', 'mm', 'purchase-requirement', 'list', '--all'])
    result = json.loads(capsys.readouterr().out)
    assert rc == 5 and result['error']['type'] == 'SCOPE_MISMATCH'
    assert 'items' not in result
