"""entity 共享基座：薄。把「拼 tenant URL + 分页 list + 单条 get」下沉，避免每个
entity 重写循环/unwrap（envelope/pagination/header 全复用 #1 骨架）。
"""
from __future__ import annotations

from typing import Callable, Optional

from ..auth import Session
from ..config import Credentials
from ..envelope import Page, coerce_to_page
from ..http import HttpClient
from ..pagination import iterate_all


class PagedEntity:
    """普通 GET 分页 entity 的基座。子类定 MOD + 端点路径模板。"""

    MOD: str = ""

    def __init__(self, cred: Credentials, session: Session, http: HttpClient):
        self._cred = cred
        self._session = session
        self._http = http

    # ---- 子类覆写 ----
    def _list_path(self, tenant_id: str) -> str:
        raise NotImplementedError

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        raise NotImplementedError

    # ---- 共享实现 ----
    def _tenant_id(self) -> str:
        return self._session.token().tenant_id

    def _base(self) -> str:
        return self._cred.base_url(self.MOD)

    def _list(
        self,
        base_params: Optional[dict],
        size: int,
        all_pages: bool,
        transform: Optional[Callable[[list], list]] = None,
    ) -> Page:
        url = self._base() + self._list_path(self._tenant_id())
        base_params = base_params or {}

        def fetch(page_no: int) -> Page:
            params = {**base_params, "page": str(page_no), "size": str(size)}
            page = self._http.get_page(url, params, requested_size=size)
            if transform is not None:
                page.items = transform(page.items)
            return page

        if not all_pages:
            return fetch(0)
        agg = iterate_all(fetch)
        # 封顶早停标到 truncated（不只塞 has_next）——调用方据此知结果不完整。
        return Page(items=agg.items, page=None, total=None, has_next=agg.truncated, truncated=agg.truncated)

    def _get(self, entity_id: str) -> dict:
        url = self._base() + self._get_path(self._tenant_id(), entity_id)
        return self._http.get_json(url)

    def _list_bare(
        self,
        base_params: Optional[dict],
        size: int,
        all_pages: bool,
    ) -> Page:
        """裸数组 / dict-with-items / single tree dict 端点的 list（mm.bom、md.product-level 等）。

        关键（审计实测）：裸 list **不能**走 get_page/get_json/normalize——
          - normalize(裸 list) → _extract_total 调 .get 抛 AttributeError（不是安全吞空）；
          - get_json(空裸 list) → `or {}` 把数据吞成 {}。
        所以这里走 http._request 拿**原值**（resp.json() 原始 list/dict，不 `or {}`），再 coerce_to_page 包形。
        这类端点一次返全量、无分页信封，故 all_pages 不翻页（coerce_to_page 恒 has_next=False）；
        base_params 作 query 透传（端点若支持 filter）。size 形参保留对齐 _list 签名，不参与翻页。
        """
        url = self._base() + self._list_path(self._tenant_id())
        params = dict(base_params or {})
        raw = self._http._request("GET", url, params=params)
        return coerce_to_page(raw)

    def _sub_list(
        self,
        path: str,
        params: Optional[dict] = None,
        size: int = 20,
        all_pages: bool = False,
        max_pages: int = 1000,
    ) -> Page:
        """任意子路径的分页 list 下沉（wm items/lines/details/pending、qm 子 list verb 等复用）。

        path 是 base 之后的完整子路径（含 tenant 段，由调用方拼好）。复用 _list 的翻页骨架：
        靠 has_next（last/启发式）翻页、委托 pagination.iterate_all 终止，**不**重写翻页循环。
        all_pages=False 取单页；all_pages=True 翻全部页（封顶 max_pages 早停 → truncated 标记）。
        """
        url = self._base() + path
        base_params = dict(params or {})

        def fetch(page_no: int) -> Page:
            p = {**base_params, "page": str(page_no), "size": str(size)}
            return self._http.get_page(url, p, requested_size=size)

        if not all_pages:
            return fetch(0)
        agg = iterate_all(fetch, max_pages=max_pages)
        return Page(
            items=agg.items, page=None, total=None, has_next=agg.truncated, truncated=agg.truncated
        )


class PostPagedEntity(PagedEntity):
    """POST-body 分页 entity 的基座。镜像 PagedEntity._list，但底层走 http.post_page。

    filter **进 body**、page/size **进 query**（与 GET 路径「全部进 query」不混）。
    覆盖 pp.production-plan/demand-supply/sales-order、sd.quotation、cr.service-order/fee 这批
    「filter 进 body、分页参进 query」的实体。post_page 已存在（wm.available_stock 已用过样板）。
    子类定 MOD + _list_path，调 _list(base_params=filter, size=, all_pages=)。
    """

    def _list(
        self,
        base_params: Optional[dict],
        size: int,
        all_pages: bool,
        transform: Optional[Callable[[list], list]] = None,
    ) -> Page:
        url = self._base() + self._list_path(self._tenant_id())
        body = dict(base_params or {})

        def fetch(page_no: int) -> Page:
            # filter 在 body、page/size 在 query —— 与 GET 路径机制分离。
            page = self._http.post_page(
                url, body=body, params={"page": str(page_no), "size": str(size)}, requested_size=size
            )
            if transform is not None:
                page.items = transform(page.items)
            return page

        if not all_pages:
            return fetch(0)
        agg = iterate_all(fetch)
        return Page(
            items=agg.items, page=None, total=None, has_next=agg.truncated, truncated=agg.truncated
        )
