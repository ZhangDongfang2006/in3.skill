"""响应信封归一：把后端五花八门的分页信封归一成单一 Page 形状。

以 wm client 逻辑为基准（最完善）。纯函数、无 I/O，便于单测。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Page:
    items: list
    page: int | None
    total: int | None
    has_next: bool
    truncated: bool = False  # 封顶早停（#6 stock all / 大结果集）时置 True


def _int_or_none(val: object) -> int | None:
    """int 才取（剔除 bool —— Python 里 True/False 是 int 子类，会误判）。"""
    return val if isinstance(val, int) and not isinstance(val, bool) else None


_ITEMS_KEYS = ("content", "records", "items", "list")


def _extract_items(raw: dict) -> list:
    for key in _ITEMS_KEYS:
        if key in raw and isinstance(raw[key], list):
            return raw[key]
    return []


_TOTAL_KEYS = ("totalElements", "total_elements", "total")


def _extract_total(raw: dict, n_items: int) -> int | None:
    """total < len(items)（Spring Slice 等不可信）或缺失 → None，绝不回退 len。"""
    for key in _TOTAL_KEYS:
        val = _int_or_none(raw.get(key))
        if val is not None:
            return val if val >= n_items else None
    return None


def _extract_has_next(raw: dict, n_items: int, requested_size: int | None) -> bool:
    if isinstance(raw.get("last"), bool):
        return not raw["last"]
    # 无 last：启发式——满页(len==请求 size)假定可能还有下页，不满则末页。
    if requested_size is not None:
        return n_items >= requested_size
    return False


def _extract_page(raw: dict) -> int | None:
    pageable = raw.get("pageable")
    if isinstance(pageable, dict):
        for key in ("pageNumber", "page_number"):
            if _int_or_none(pageable.get(key)) is not None:
                return pageable[key]
    for key in ("number", "current", "pageNumber"):
        if _int_or_none(raw.get(key)) is not None:
            return raw[key]
    return None


def normalize(raw: dict, requested_size: int | None = None) -> Page:
    items = _extract_items(raw)
    total = _extract_total(raw, len(items))
    has_next = _extract_has_next(raw, len(items), requested_size)
    page = _extract_page(raw)
    return Page(items=items, page=page, total=total, has_next=has_next)


def coerce_to_page(data: object) -> Page:
    """吃三种非标 list 响应形态，统一包成 Page(items, page=0, total=len, has_next=False)。

    与 normalize 的分工：normalize 只认「dict 信封 + 可信 total/has_next 翻页元数据」；
    coerce_to_page 收「无翻页元数据的非标形」——后端不返分页信封、一次给全量的端点。
      ① bare top-level list（裸数组）   → 原样 items，total=len。
      ② {items:[...]} dict-with-items   → 取 items，total=len。
      ③ single tree dict（非 items 裸 dict）→ dict→[dict] coerce，total=1。
    这条路径**不经** envelope.normalize（裸 list 喂 normalize 会因 _extract_total 调 .get 抛
    AttributeError）、**不经** get_json 的 `or {}`（空裸 list 会被吞成 {}）。三形均 has_next=False、
    page=0（一次全量、无下页）。
    """
    if isinstance(data, list):
        # ① bare top-level array（含空数组 → total=0）。
        return Page(items=data, page=0, total=len(data), has_next=False)
    if isinstance(data, dict):
        if isinstance(data.get("items"), list):
            # ② dict-with-items。
            items = data["items"]
            return Page(items=items, page=0, total=len(items), has_next=False)
        # ③ single tree dict → 单元素 list。
        return Page(items=[data], page=0, total=1, has_next=False)
    # None / 其它标量 → 空页（不炸；上游 _request 返 None 时安全降级）。
    return Page(items=[], page=0, total=0, has_next=False)


def _wrap_items(data: object) -> Page:
    """qm `{items:[...]}` 非分页 verb（get-all / list-options / search-by-lot 等）的薄入口。

    委托 coerce_to_page —— **不**另写一套包形逻辑；coerce_to_page 的 ② 分支即覆盖 `{items}` 形。
    保留独立命名仅为下游 qm 调用点语义清晰（「这是 {items} wrap，不是 bare-list」）。
    """
    return coerce_to_page(data)
