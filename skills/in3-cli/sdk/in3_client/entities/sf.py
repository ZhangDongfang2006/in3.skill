"""慧现场 SIM 只读查询：POST 请求体分页，列表和详情均完整保留服务端字段。"""
from __future__ import annotations

import math
from datetime import date, datetime
from typing import Callable
from urllib.parse import quote

from .base import PagedEntity
from ..envelope import Page, normalize
from ..filters import check_filter_keys
from ..pagination import iterate_all
from ..sf_schema import SF_FILTERS, SORT_FIELDS


def _validate_scalar(value: object, kind: str, name: str) -> None:
    valid = isinstance(value, str)
    if kind == "boolean":
        valid = isinstance(value, bool)
    elif kind == "integer":
        valid = isinstance(value, int) and not isinstance(value, bool)
    elif kind in ("date", "datetime") and valid:
        try:
            (date if kind == "date" else datetime).fromisoformat(value)
        except ValueError:
            valid = False
    if not valid:
        raise ValueError(f"{name} 必须为 {kind}")


def validate_filters(filters: dict) -> dict:
    """拒绝未知条件及错误类型，保护服务端免受无效排序表达式影响。"""
    check_filter_keys("sf.sim_issue", filters, SF_FILTERS)
    body = dict(filters)
    for name, value in body.items():
        if value is None:
            continue
        spec = SF_FILTERS[name]
        if spec["multi"] and not isinstance(value, list):
            raise ValueError(f"{name} 必须为数组")
        for item in value if spec["multi"] else [value]:
            _validate_scalar(item, spec["type"], name)
    orders = []
    for order in body.get("sort") or ["id,asc"]:
        parts = order.split(",")
        name = parts[0].removeprefix("si.")
        if len(parts) != 2 or name not in SORT_FIELDS or parts[1] not in ("asc", "desc"):
            raise ValueError("sort 必须为已声明的字段,asc 或 字段,desc")
        orders.append(f"si.{name},{parts[1]}")
    if not any(order.startswith("si.id,") for order in orders):
        orders.append("si.id,asc")
    body["sort"] = orders
    return body


class SimIssueEntity(PagedEntity):
    MOD = "sf"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/ld/sime/issues/page"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/ld/sime/issues/{quote(entity_id, safe='')}"

    def get(self, entity_id: str) -> dict:
        """按 ID 获取全部详情，包括行动、日志、图片、根因及关联单据。"""
        if not isinstance(entity_id, str) or not entity_id or entity_id in (".", ".."):
            raise ValueError("SIM 问题 id 不能为空")
        detail = self._get(entity_id)
        if not isinstance(detail, dict) or not detail.get("id"):
            raise ValueError("SIM 详情响应缺少 id")
        return detail

    def list(self, *, filter: dict | None = None, size: int = 100, all: bool = True,
             page: int = 0, max_items: int | None = None, max_pages: int = 1000,
             include_details: bool = False) -> Page:
        """默认翻全部页；封顶时明确标记 truncated，详情读取失败直接报错。"""
        for name, number, minimum in (("page", page, 0), ("size", size, 1),
                                      ("max_pages", max_pages, 1),
                                      ("max_items", max_items if max_items is not None else 1, 1)):
            if not isinstance(number, int) or isinstance(number, bool) or number < minimum:
                raise ValueError(f"{name} 必须为 >= {minimum} 的整数")
        body = validate_filters(filter or {})
        url = self._base() + self._list_path(self._tenant_id())

        def fetch(offset: int) -> Page:
            raw = self._http.post_json(url, body={**body, "page": page + offset, "size": size})
            if not isinstance(raw, dict) or not isinstance(raw.get("content"), list):
                raise ValueError("SIM 列表响应缺少 content 数组")
            result = normalize(raw, requested_size=size)
            if result.page is None:
                result.page = page + offset
            if result.page != page + offset:
                raise ValueError("SIM 服务端未按请求 page 返回分页，无法确认全量结果")
            if result.has_next and not result.items:
                raise ValueError("SIM 服务端返回非末页空数据，无法继续分页")
            return result

        result = self._collect(fetch, all, size, max_items, max_pages)
        if include_details:
            result.items = [self._with_detail(row) for row in result.items]
        return result

    @staticmethod
    def _collect(fetch: Callable[[int], Page], all_pages: bool, size: int,
                 max_items: int | None, max_pages: int) -> Page:
        if all_pages:
            limit = min(max_pages, math.ceil(max_items / size)) if max_items else max_pages
            aggregate = iterate_all(fetch, max_pages=limit)
            result = Page(aggregate.items, None, None, aggregate.truncated, aggregate.truncated)
        else:
            result = fetch(0)
        if max_items is not None and len(result.items) > max_items:
            result.items = result.items[:max_items]
            result.has_next = result.truncated = True
        return result

    def _with_detail(self, row: dict) -> dict:
        if not isinstance(row, dict) or not row.get("id"):
            raise ValueError("SIM 列表记录缺少 id，无法获取详情")
        detail = self.get(row["id"])
        merged = {**row, **{key: value for key, value in detail.items()
                            if value is not None or key not in row}}
        merged["detail"] = detail
        return merged
