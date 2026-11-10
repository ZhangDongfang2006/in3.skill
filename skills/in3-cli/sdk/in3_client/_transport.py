"""HTTP transport：优先 requests，缺失则用 stdlib urllib 兜底 → SDK **零硬依赖**。

真实用户「什么都没有」也能跑：装好 in3-cli + 登录后，`in3_cli.py run script.py` 把 SDK 目录
注入 PYTHONPATH，纯 stdlib 即可发请求（auth/http/分页/entity/join/sole_source 全可用；
只有 IN3.df 需要 pandas，且已降级）。requests 在时自动用 requests（连接池更优）。

transport 调用约定（与测试里的 FakeTransport 一致）：
  transport(method, url, headers=None, params=None, json=None, **kw) -> resp
  resp 须有 .status_code / .headers(含 content-type) / .json() / .text
params 的 list 值按 doseq 展开成重复 query（material_ids=a&material_ids=b），与后端 List 绑定一致。
"""
from __future__ import annotations

import json as _json
import urllib.error
import urllib.parse
import urllib.request

_DEFAULT_TIMEOUT = 60


class _UrllibResponse:
    def __init__(self, status: int, headers: dict, body: bytes):
        self.status_code = status
        self._headers = headers
        self._body = body

    @property
    def headers(self) -> dict:
        return self._headers

    @property
    def text(self) -> str:
        return self._body.decode("utf-8", errors="replace")

    def json(self):
        return _json.loads(self._body) if self._body else None


def _urllib_transport(method, url, headers=None, params=None, json=None, timeout=_DEFAULT_TIMEOUT, **kw):
    if params:
        query = urllib.parse.urlencode(params, doseq=True)  # list → 重复 query
        url = url + ("&" if "?" in url else "?") + query
    hdrs = dict(headers or {})
    data = None
    if json is not None:
        data = _json.dumps(json).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            h = {k.lower(): v for k, v in r.headers.items()}
            return _UrllibResponse(getattr(r, "status", 200), h, body)
    except urllib.error.HTTPError as e:
        body = e.read() if hasattr(e, "read") else b""
        h = {k.lower(): v for k, v in (e.headers.items() if e.headers else [])}
        return _UrllibResponse(e.code, h, body)


def default_transport():
    """requests 在则用之，否则回退 stdlib urllib。"""
    try:
        import requests  # noqa: PLC0415

        def transport(method, url, headers=None, params=None, json=None, **kw):
            return requests.request(method, url, headers=headers, params=params, json=json, **kw)

        return transport
    except ImportError:
        return _urllib_transport
