"""分页迭代：靠 Page.has_next 判停翻全部页，绝不按 total 计算循环次数。

total 可能为 None（Spring Slice 无可信 total），所以停的依据只有 has_next；
封顶 max_pages 防后端 has_next 恒 True 时无限翻页。纯函数、无 I/O。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .envelope import Page


@dataclass
class AllPages:
    items: list
    pages_fetched: int
    truncated: bool


def iterate_all(fetch_page: Callable[[int], Page], max_pages: int = 1000) -> AllPages:
    """从第 0 页起反复调 fetch_page(page_no)，累积 items，直到某页 has_next=False。

    达到 max_pages 仍 has_next=True → 早停并标 truncated（不无限翻页）。
    """
    items: list = []
    page_no = 0
    truncated = False
    while True:
        page = fetch_page(page_no)
        items.extend(page.items)
        page_no += 1
        if not page.has_next:
            break
        if page_no >= max_pages:
            truncated = True
            break
    return AllPages(items=items, pages_fetched=page_no, truncated=truncated)
