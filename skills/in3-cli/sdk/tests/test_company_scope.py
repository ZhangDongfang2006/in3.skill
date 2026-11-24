"""SO/PR 通过真实 SDK 接口验证公司解析、工厂映射和组织隔离。"""
from dataclasses import dataclass, field

import pytest
from in3_client.auth import Session
from in3_client.config import Credentials
from in3_client.entities.mm import PurchaseRequirementEntity
from in3_client.entities.sd import SalesOrderEntity
from in3_client.http import HttpClient


@dataclass
class Response:
    data: object
    status_code: int = 200
    headers: dict = field(default_factory=lambda: {"content-type": "application/json"})

    def json(self):
        return self.data


class Backend:
    def __init__(self):
        self.calls = []
        self.companies = [{"id": "c1", "company_code": "CO01"},
                          {"id": "c2", "company_code": "CO02"}]
        self.plants = []
        self.rows = {}
        self.details = {}

    def __call__(self, method, url, **kwargs):
        assert method == "GET"
        params = kwargs.get("params") or {}
        self.calls.append((url, params, kwargs.get("headers")))
        if url.rsplit('/', 1)[-1] in self.details:
            return Response(self.details[url.rsplit('/', 1)[-1]])
        if url.endswith('/company-codes/list'):
            return Response(self.companies)
        if url.endswith('/plants/page'):
            return Response({"content": self.plants, "last": True})
        scope = params.get('plant_id') or params.get('company_id')
        rows = self.rows.get(scope, [])
        page, size = int(params['page']), int(params['size'])
        return Response({"content": rows[page * size:(page + 1) * size],
                         "total_elements": len(rows), "number": page,
                         "last": (page + 1) * size >= len(rows)})


def wire(entity_type):
    backend = Backend()
    cred = Credentials(api_host='https://api.test/service', tenant_domain='tenant',
                       username='user', encrypted_password='fixture', alias='test')
    session = Session.from_token(cred, access_token='fixture-token', tenant_id='t1',
                                 tenant_domain='TENANT', user_id='u1')
    return entity_type(cred, session, HttpClient(session, backend)), backend


def test_sales_order_resolves_company_code_and_preserves_total():
    entity, backend = wire(SalesOrderEntity)
    backend.rows['c2'] = [{'id': 'so2', 'company_id': 'c2', 'company_code': 'CO02'}]
    result = entity.list(company='CO02', all=False)
    assert result.items[0]['id'] == 'so2'
    assert result.total == 1
    url, params, headers = backend.calls[-1]
    assert '/mom/sd/' in url and params['company_id'] == 'c2'
    assert headers['T-CODE'] == 'TENANT'


def test_purchase_requirement_queries_every_plant_in_selected_company():
    entity, backend = wire(PurchaseRequirementEntity)
    backend.plants = [{'id': 'p1', 'company_id': 'c1'},
                      {'id': 'p2', 'company_id': 'c2'},
                      {'id': 'p3', 'company_id': 'c2'}]
    backend.rows = {p: [{'id': p, 'company_id': 'c2', 'plant_id': p}]
                    for p in ('p2', 'p3')}
    result = entity.list(company='CO02', size=1, all=True)
    assert {row['id'] for row in result.items} == {'p2', 'p3'}
    queries = [params for url, params, _ in backend.calls if 'purchase-requirents' in url]
    assert {p['plant_id'] for p in queries} == {'p2', 'p3'}
    assert all('company_id' not in p for p in queries)
    assert not result.truncated


@pytest.mark.parametrize('kind', ['wrong_company', 'missing_company', 'wrong_plant'])
def test_unverifiable_organization_data_fails_instead_of_returning_rows(kind):
    entity, backend = wire(PurchaseRequirementEntity)
    backend.plants = [{'id': 'p2', 'company_id': 'c2'}]
    row = {'id': 'pr', 'company_id': 'c2', 'plant_id': 'p2'}
    if kind == 'wrong_company':
        row['company_id'] = 'c1'
    elif kind == 'missing_company':
        row.pop('company_id')
    else:
        row['plant_id'] = 'p1'
    backend.rows['p2'] = [row]
    with pytest.raises(RuntimeError, match='范围'):
        entity.list(company='CO02')


@pytest.mark.parametrize('selection', [['CO01', 'CO02', 'CO02'], '*'])
def test_multiple_companies_merge_all_pages_without_duplicate_scopes(selection):
    entity, backend = wire(SalesOrderEntity)
    backend.rows = {f'c{i}': [{'id': f'so{i}-{j}', 'company_id': f'c{i}'}
                              for j in range(3)] for i in (1, 2)}
    result = entity.list(company=selection, size=2)
    assert len(result.items) == 6
    assert {row['company_id'] for row in result.items} == {'c1', 'c2'}
    assert result.total == 6 and not result.has_next
    assert len([url for url, _, _ in backend.calls if url.endswith('/sales-orders/page')]) == 4


@pytest.mark.parametrize('problem', ['unknown_company', 'no_plant', 'wrong_plant', 'conflict'])
def test_invalid_selection_never_falls_back_to_default_organization(problem):
    entity, backend = wire(PurchaseRequirementEntity)
    backend.plants = [{'id': 'p1', 'company_id': 'c1'}]
    kwargs = {'company': 'MISSING' if problem == 'unknown_company' else 'CO02'}
    if problem == 'wrong_plant':
        kwargs['plant'] = 'p1'
    if problem == 'conflict':
        kwargs['filter'] = {'company_id': 'c1'}
    with pytest.raises(ValueError):
        entity.list(**kwargs)
    assert not any('purchase-requirents' in url for url, _, _ in backend.calls)


def test_scoped_pagination_supports_page_and_marks_global_cap():
    entity, backend = wire(SalesOrderEntity)
    backend.rows = {f'c{i}': [{'id': f'so{i}-{j}', 'company_id': f'c{i}'}
                              for j in range(3)] for i in (1, 2)}
    page = entity.list(company='CO02', size=1, page=1, all=False)
    assert [r['id'] for r in page.items] == ['so2-1']
    assert page.page == 1 and page.total == 3
    capped = entity.list(company='*', size=2, max_items=4)
    assert len(capped.items) == 4 and capped.truncated and capped.has_next
    assert not any(r['id'] == 'so2-2' for r in capped.items)


@pytest.mark.parametrize('entity_type', [SalesOrderEntity, PurchaseRequirementEntity])
def test_company_id_filter_uses_same_safe_scope_mapping(entity_type):
    entity, backend = wire(entity_type)
    backend.plants = [{'id': 'p2', 'company_id': 'c2'}]
    key = 'c2' if entity_type is SalesOrderEntity else 'p2'
    backend.rows[key] = [{'id': 'r2', 'company_id': 'c2', 'plant_id': 'p2'}]
    result = entity.list(filter={'company_id': 'c2'}, all=False)
    assert result.total == 1
    assert result.items[0]['company_id'] == 'c2'
    if entity_type is PurchaseRequirementEntity:
        assert backend.calls[-1][1]['plant_id'] == 'p2'
        assert 'company_id' not in backend.calls[-1][1]


def test_scoped_sales_order_items_come_from_the_matching_order_detail():
    entity, backend = wire(SalesOrderEntity)
    backend.rows['c2'] = [{'id': 'so2', 'company_id': 'c2'}]
    backend.details['so2'] = {'id': 'so2', 'company_id': 'c2',
                              'products': [{'id': 'line2', 'so_id': 'so2'}]}
    result = entity.list(company='CO02', include_items=True)
    assert result.items[0]['items'] == [{'id': 'line2', 'so_id': 'so2'}]


@pytest.mark.parametrize('selection', ['', [], True])
def test_empty_or_boolean_company_is_rejected_without_business_query(selection):
    entity, backend = wire(SalesOrderEntity)
    with pytest.raises(ValueError):
        entity.list(company=selection)
    assert not any('sales-orders' in url for url, _, _ in backend.calls)


def test_existing_plant_filter_is_preserved_within_company():
    entity, backend = wire(PurchaseRequirementEntity)
    backend.plants = [{'id': 'p2', 'company_id': 'c2'}, {'id': 'p3', 'company_id': 'c2'}]
    backend.rows['p3'] = [{'id': 'pr3', 'company_id': 'c2', 'plant_id': 'p3'}]
    result = entity.list(company='CO02', filter={'plant_id': 'p3', 'status': ['A']}, all=False)
    assert [row['id'] for row in result.items] == ['pr3']
    assert backend.calls[-1][1]['status'] == ['A']


def test_null_company_id_filter_does_not_silently_use_default_company():
    entity, backend = wire(SalesOrderEntity)
    with pytest.raises(ValueError):
        entity.list(filter={'company_id': None})
    assert backend.calls == []
