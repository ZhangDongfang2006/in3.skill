"""filter_key 校验（PRD §A · :50）：实体只接受 __schema 声明的 filter key，未声明 key fail-loud。

后端对未声明的 query key **静默忽略**（不报错、返全量）——agent 以为筛过了、其实拿到全表，
范围还自以为对（modules.md 已知坑「key 不在 filter_keys 里时后端静默忽略」；PRD §A ¥111K 类
静默错的同源）。SDK 在 list() 入口对**有 exhaustive filter_keys** 的实体做白名单校验：传未声明
key → raise FilterKeyError，而非放任后端静默吞。

覆盖边界（忠实，不假装能校验拿不到声明的实体）：
- md.material / mm.supplier / mm.purchase_order / sd.sales_order_item —— `<cli> __schema` 给出
  exhaustive `filter_keys` 数组，做严格白名单 + 扩展字段 pattern（field_a..av / column_a..u）。
- wm.stock / wm.available_stock —— CLI 用通用 `--filter` 透传、__schema 不声明 filter_keys
  （typed-flag 只是便捷入口、非穷举），无权威白名单可依，故与 CLI 一致透传、不强校（各 entity
  docstring 标注）。给 wm 硬编一份无法从 schema 验证的白名单只会制造假性 fail-loud，反而更坏。
- md.currency —— 无 filter dict（keyword/enabled 具名参数），签名即校验。
"""
from __future__ import annotations

from typing import Iterable, Pattern, Sequence


class FilterKeyError(ValueError):
    """传了实体未声明的 filter key —— 后端会静默忽略（看似筛过其实返全量）。"""

    def __init__(self, entity: str, unknown: Iterable[str], allowed: Iterable[str]):
        self.entity = entity
        self.unknown = sorted(unknown)
        self.allowed = sorted(allowed)
        super().__init__(
            f"{entity}: 未声明的 filter key {self.unknown} —— 后端会静默忽略"
            f"（看似筛过其实返全量）。可用 key（见 `<cli> __schema` 的 filter_keys）: {self.allowed}"
        )


def check_filter_keys(
    entity: str,
    filter: dict | None,
    allowed: Iterable[str],
    *,
    patterns: Sequence[Pattern] = (),
) -> None:
    """filter 里出现 allowed/patterns 之外的 key → raise FilterKeyError。空 filter 直接放行。

    必须在任何网络调用之前调用（list() 入口），让坏 key 不打到后端就 fail-loud。
    """
    if not filter:
        return
    unknown = [
        k for k in filter
        if k not in allowed and not any(p.match(k) for p in patterns)
    ]
    if unknown:
        raise FilterKeyError(entity, unknown, allowed)
