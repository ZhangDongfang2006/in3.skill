"""数据请求层：带三头发 GET、401 重试一次、非 JSON 200 判认证失败，再交 envelope 归一。

参照真 CLI src/http/client.ts 的 requestJson 管线（send → 401 则 onUnauthorized 刷新重试一次
→ 非 ok 抛 HttpError）。额外加：200 但非 JSON（网关 HTML）视为认证失败（issue #1 硬要求）。
"""
from __future__ import annotations

from typing import Callable, Optional

from ._transport import default_transport
from .auth import AuthFailedError, Session, _is_json
from .envelope import Page, normalize


class HttpError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class HttpClient:
    """薄数据请求客户端，绑定一个 auth.Session（取头 + 401 刷新）。"""

    def __init__(self, session: Session, transport: Optional[Callable] = None):
        self._session = session
        self._transport = transport or default_transport()

    @property
    def session(self) -> Session:
        return self._session

    def get_page(
        self,
        url: str,
        params: Optional[dict] = None,
        requested_size: Optional[int] = None,
        extra_headers: Optional[dict] = None,
    ) -> Page:
        raw = self.get_json(url, params, extra_headers=extra_headers)
        return normalize(raw, requested_size=requested_size)

    def get_json(self, url: str, params: Optional[dict] = None, extra_headers: Optional[dict] = None) -> dict:
        """单条记录 GET（不归一信封）——给 entity 的 .get(id) 用。非 200 抛错。"""
        return self._request("GET", url, params=params, extra_headers=extra_headers) or {}

    def post_json(self, url: str, body: Optional[dict] = None, params: Optional[dict] = None):
        """POST 返原始 JSON（list 或 dict）——给 bulk-get-by-po 这类返扁平数组的端点用。"""
        return self._request("POST", url, params=params, json=body or {})

    def post_page(
        self,
        url: str,
        body: Optional[dict] = None,
        params: Optional[dict] = None,
        requested_size: Optional[int] = None,
        extra_headers: Optional[dict] = None,
    ) -> Page:
        """POST 分页（wm available-stock：filter 在 body、page/size 在 query），再归一。"""
        raw = self._request("POST", url, params=params, json=body or {}, extra_headers=extra_headers)
        return normalize(raw or {}, requested_size=requested_size)

    def _request(
        self,
        method: str,
        url: str,
        params: Optional[dict] = None,
        json: Optional[dict] = None,
        extra_headers: Optional[dict] = None,
    ):
        """GET/POST 共享管线：三头 + 401 清 token 重试一次 + 非 JSON 200 判认证失败。

        返回 resp.json() 原值（可能是 list/dict/None）——调用方按需 coerce（list 端点不能 `or {}`）。

        extra_headers 请求级临时叠在 session.headers() 之上（同名 extra_headers 覆盖），
        每次 send() 重新合并 —— 不写回 session，不污染 token 刷新后的下一次请求。
        """
        def send():
            headers = dict(self._session.headers())
            if extra_headers:
                headers.update(extra_headers)
            kw = {"headers": headers, "params": params}
            if json is not None:
                kw["json"] = json
            return self._transport(method, url, **kw)

        resp = send()
        if resp.status_code == 401:
            # 优先用 refresh_token 静默刷新（不重发口令）；刷新不可用/失败 → 回退重新换 token。仅重试一次。
            if not self._session.refresh():
                self._session.clear()
                self._session.token()
            resp = send()
        if resp.status_code == 200 and not _is_json(resp):
            raise AuthFailedError(
                f"{method} {url} returned 200 but non-JSON (gateway HTML?) —— treated as auth failure"
            )
        if resp.status_code != 200:
            raise HttpError(resp.status_code, f"{method} {url} → {resp.status_code}")
        return resp.json()
