"""SO/PR 的显式公司范围；不修改会话默认值，不接受范围外的数据。"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

from .auth import Session
from .config import Credentials
from .entities.md import CompanyCodeEntity, PlantEntity
from .envelope import Page
from .http import HttpClient
from .pagination import iterate_all

CompanySelection = Union[str, int, Sequence[Union[str, int]]]  # noqa: UP007 -- 运行时别名兼容 Python 3.9。


def take_company(params: dict, company: CompanySelection | None) -> CompanySelection | None:
    """接收旧 company_id 筛选别名，禁止与显式公司参数冲突。"""
    if 'company_id' in params:
        if company is not None:
            raise OrganizationScopeError('company 与 filter.company_id 不能同时指定')
        if params['company_id'] is None:
            raise OrganizationScopeError('company_id 不能为空')
        return params.pop('company_id')
    return company


class OrganizationScopeError(ValueError):
    """请求的公司或工厂范围无法解析。"""


class OrganizationDataError(RuntimeError):
    """服务端返回了无法归属到请求范围的数据。"""


class CompanyQuery:
    def __init__(self, cred: Credentials, session: Session, http: HttpClient):
        self.cred, self.session, self.http = cred, session, http

    def resolve(self, company: CompanySelection) -> list[dict]:
        """公司代码或 ID 精确解析；星号代表当前账号可见的公司。"""
        values = [company] if isinstance(company, (str, int)) else list(company)
        if not values or any(isinstance(v, bool) or not str(v).strip() for v in values):
            raise OrganizationScopeError('公司范围不能为空')
        rows = CompanyCodeEntity(self.cred, self.session, self.http).list().items
        if values == ['*']:
            if not rows:
                raise OrganizationScopeError('当前账号没有可访问的公司')
            return rows
        selected = {}
        for value in values:
            matches = [r for r in rows if str(value).casefold() in (
                str(r['id']).casefold(), str(r['company_code']).casefold()
            )]
            if len(matches) != 1:
                raise OrganizationScopeError(f'公司 {value!r} 不存在、不可访问或标识不唯一')
            selected[str(matches[0]['id'])] = matches[0]
        return list(selected.values())

    def scopes(self, entity: str, companies: list[dict], params: dict) -> list[tuple]:
        """SO 按公司；PR 映射该公司的全部工厂，拒绝冲突的工厂参数。"""
        if 'company_id' in params:
            raise OrganizationScopeError('company 与 filter.company_id 不能同时指定')
        if entity == 'sales_order':
            return [(c, {'company_id': c['id']}) for c in companies]
        plants = PlantEntity(self.cred, self.session, self.http).list(all=True)
        if plants.truncated:
            raise OrganizationScopeError('工厂目录未取全，无法确定完整公司范围')
        result = []
        for company in companies:
            owned = [p for p in plants.items if str(p.get('company_id')) == str(company['id'])]
            if 'plant_id' in params:
                owned = [p for p in owned if str(p['id']) == str(params['plant_id'])]
            if not owned:
                raise OrganizationScopeError(f"公司 {company['company_code']} 无匹配的可访问工厂")
            result.extend((company, {'plant_id': p['id']}) for p in owned)
        return result

    def list(self, entity: str, *, company: CompanySelection, params: dict,
             size: int, all: bool, page: int = 0, max_items: int | None = None) -> Page:
        if type(size) is not int or not 1 <= size <= 200 or type(page) is not int or page < 0:
            raise OrganizationScopeError('size 必须为 1..200 的整数，page 必须为非负整数')
        if (all and page) or (max_items is not None and (
            not all or type(max_items) is not int or max_items <= 0
        )):
            raise OrganizationScopeError('全量查询不能指定 page；max_items 必须为全量查询的正整数上限')
        companies = self.resolve(company)
        scopes = self.scopes(entity, companies, params)
        mod, path = ('sd', '/sales-orders/page') if entity == 'sales_order' else (
            'mm', '/spm/purchase-requirents/pages')
        url = self.cred.base_url(mod) + f'/v2/api/tenants/{self.session.token().tenant_id}' + path
        pages, count = [], 0
        for selected, scope in scopes:
            remaining = None if max_items is None else max_items - count
            if remaining == 0:
                return Page([r for p in pages for r in p.items], None, None, True, True)
            result = self.fetch_scope(url, selected, {**params, **scope}, scope,
                                      size=size, all=all, page=page, max_items=remaining)
            pages.append(result)
            count += len(result.items)
            if result.truncated:
                return Page([r for p in pages for r in p.items], None, None, True, True)
        totals = [p.total for p in pages]
        return Page([row for p in pages for row in p.items], None if all else page,
                    sum(totals) if all_total_known(totals) else None,
                    any(p.has_next for p in pages), any(p.truncated for p in pages))

    def fetch_scope(self, url: str, company: dict, params: dict, scope: dict, *,
                    size: int, all: bool, page: int, max_items: int | None) -> Page:
        first_total = None
        kept, capped = 0, False

        def fetch(page_no: int) -> Page:
            nonlocal first_total, kept, capped
            result = self.http.get_page(
                url, {**params, 'page': str(page_no), 'size': str(size)}, requested_size=size,
            )
            if page_no == 0:
                first_total = result.total
            for row in result.items:
                self.validate_row(row, company, scope)
            if max_items is not None:
                remaining = max_items - kept
                capped = len(result.items) > remaining or (
                    len(result.items) == remaining and result.has_next
                )
                result.items = result.items[:remaining]
                kept += len(result.items)
                if capped:
                    result.has_next = False
            return result

        if not all:
            return fetch(page)
        result = iterate_all(fetch)
        total = first_total if first_total is None or first_total >= len(result.items) else None
        truncated = result.truncated or capped
        return Page(result.items, None, total, truncated, truncated)

    @staticmethod
    def validate_row(row: dict, company: dict, scope: dict) -> None:
        """校验每页数据；缺少公司身份或服务端忽略筛选时拒绝返回。"""
        company_id, code = row.get('company_id'), row.get('company_code')
        if company_id is None and code is None:
            raise OrganizationDataError('返回数据缺少公司字段，无法验证组织范围')
        if company_id is not None and str(company_id) != str(company['id']):
            raise OrganizationDataError('返回数据超出请求的公司范围')
        if code is not None and str(code) != str(company['company_code']):
            raise OrganizationDataError('返回数据超出请求的公司范围')
        if 'plant_id' in scope and str(row.get('plant_id')) != str(scope['plant_id']):
            raise OrganizationDataError('返回数据超出请求的工厂范围')


def all_total_known(totals: list) -> bool:
    return all(value is not None for value in totals)
