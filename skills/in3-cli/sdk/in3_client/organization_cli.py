"""显式公司范围的 SO/PR CLI；通过 SDK 读取，避免旧 npm 分页及租户头问题。"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from . import IN3
from .auth import AuthFailedError
from .config import MissingCredentialsError
from .entities.mm import _PURCHASE_REQUIREMENT_FILTER_KEYS
from .entities.sd import _SALES_ORDER_FILTER_KEYS
from .filters import check_filter_keys
from .http import HttpError
from .organizations import OrganizationDataError


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def parser() -> Parser:
    result = Parser(add_help=False)
    result.add_argument('--workspace', type=Path)
    result.add_argument('--tenant')
    result.add_argument('--company', action='append', required=True)
    result.add_argument('module', choices=('sd', 'mm'))
    result.add_argument('entity', choices=('sales-order', 'purchase-requirement'))
    result.add_argument('verb', choices=('list',))
    result.add_argument('--filter', action='append', default=[])
    result.add_argument('--plant')
    result.add_argument('--status', action='append')
    result.add_argument('--customer')
    result.add_argument('--ordered-by')
    result.add_argument('--include-items', action='store_true')
    result.add_argument('--all', action='store_true')
    result.add_argument('--page', type=int)
    result.add_argument('--size', type=int, default=20)
    result.add_argument('--max', dest='max_items', type=int)
    return result


def filters(args: argparse.Namespace) -> dict:
    """筛选值原样透传；仅后端声明的多值键允许重复。"""
    params = {}
    multi = {'status', 'shipped_status'} if args.module == 'sd' else {
        'status', 'purchase_type', 'approval_statuses'}
    for expression in args.filter:
        key, separator, value = expression.partition('=')
        if not separator or not key or not value:
            raise ValueError('--filter 必须为非空 key=value')
        if key in multi:
            params.setdefault(key, []).append(value)
        elif key in params:
            raise ValueError(f'{key} 不允许重复')
        else:
            params[key] = value
    allowed = _SALES_ORDER_FILTER_KEYS if args.module == 'sd' else _PURCHASE_REQUIREMENT_FILTER_KEYS
    check_filter_keys(args.entity, params, allowed)
    typed = {key: value for key, value in {
        'plant_id': args.plant, 'status': args.status,
        'account_id': args.customer, 'ordered_by': args.ordered_by,
    }.items() if value is not None}
    check_filter_keys(args.entity, typed, allowed)
    return {**typed, **params}


def validate(args: argparse.Namespace) -> None:
    """拒绝不能执行或会被静默忽略的参数组合。"""
    if (args.module, args.entity) not in (('sd', 'sales-order'), ('mm', 'purchase-requirement')):
        raise ValueError('公司范围仅支持 sd sales-order list / mm purchase-requirement list')
    if args.all and args.page is not None:
        raise ValueError('--all 与 --page 互斥')
    if not 1 <= args.size <= 200 or (args.page is not None and args.page < 0):
        raise ValueError('--size 必须为 1..200；--page 必须为非负整数')
    if args.max_items is not None and (not args.all or args.max_items <= 0):
        raise ValueError('--max 必须是 --all 查询的正整数上限')


def error_result(error: Exception) -> tuple[dict, int]:
    status = getattr(error, 'status', None)
    if isinstance(error, OrganizationDataError):
        kind, code = 'SCOPE_MISMATCH', 5
    elif isinstance(error, (AuthFailedError, MissingCredentialsError)):
        kind, code = 'AUTH_FAILED', 2
    elif isinstance(error, ValueError):
        kind, code = 'VALIDATION', 4
    elif isinstance(error, HttpError):
        kind, code = {401: ('AUTH_FAILED', 2), 403: ('FORBIDDEN', 2),
                      404: ('NOT_FOUND', 3)}.get(status, ('SERVER', 5))
    else:
        kind, code = 'NETWORK' if isinstance(error, OSError) else 'UNKNOWN', 5
    return {'error': {'type': kind, 'message': str(error), 'http_status': status}}, code


def main(argv: list[str] | None = None) -> int:
    """执行公司查询；所有失败输出 JSON，不将错误当成空列表。"""
    try:
        args = parser().parse_args(argv)
        validate(args)
        params = filters(args)
        client = IN3(workspace=args.workspace, tenant=args.tenant)
        entity = client.sd.sales_order if args.module == 'sd' else client.mm.purchase_requirement
        page = entity.list(
            company=args.company, filter=params, size=args.size, all=args.all,
            page=args.page or 0, max_items=(args.max_items or 1000) if args.all else None,
            include_items=args.include_items,
        )
        print(json.dumps(asdict(page), ensure_ascii=False))
        return 0
    except Exception as error:  # noqa: BLE001 -- CLI 边界保证所有错误返回 JSON。
        payload, code = error_result(error)
        print(json.dumps(payload, ensure_ascii=False))
        return code


if __name__ == '__main__':
    sys.exit(main())
