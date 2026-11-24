"""M0 基座②单测：HttpClient.extra_headers —— 与 session.headers() 请求级合并下发。

照 test_http.py 的 FakeTransport 桩模式（桩已支持 headers kwarg，不改桩）。
覆盖 AC：
- get_json / get_page / post_page / _request 接受可选 extra_headers，请求时与三头合并。
- 合并语义：extra_headers 叠在 session header 之上（同名 extra_headers 覆盖）。
- 叠加是请求级临时的，不污染 session.headers() 缓存（下一次请求不传则不带）。
- extra_headers=None（默认）时行为与改造前一致：请求只含三头，不含业务 header。
- fncc 误发防护：不传 extra_headers 时请求不含 fncc header。
"""
from dataclasses import dataclass, field

from in3_client.config import Credentials
from in3_client.envelope import Page
from in3_client.http import HttpClient


@dataclass
class FakeResponse:
    status_code: int
    _json: object = None
    content_type: str = "application/json"
    text: str = ""

    @property
    def headers(self):
        return {"content-type": self.content_type}

    def json(self):
        return self._json


@dataclass
class FakeTransport:
    responses: list
    calls: list = field(default_factory=list)

    def __call__(self, method, url, headers=None, params=None, **kw):
        self.calls.append({"method": method, "url": url, "headers": headers, "params": params, "json": kw.get("json")})
        return self.responses.pop(0)


_CRED = Credentials(
    api_host="https://apiv3.industics.com/service",
    tenant_domain="indx",
    username="corp:zhuzheng@indx",
    encrypted_password="AESCIPHER==",
    alias="zhuzheng",
)
_TOKEN_BODY = {"access_token": "jwt-1", "tenant_id": "10030", "tenant_domain": "indx", "user_id": "u-42"}


def _session():
    from in3_client.auth import Session
    return Session(_CRED, transport=FakeTransport([FakeResponse(200, _TOKEN_BODY)]))


def test_get_json_merges_extra_headers_with_session_headers():
    sess = _session()
    data_tr = FakeTransport([FakeResponse(200, {"id": 1})])
    http = HttpClient(sess, transport=data_tr)
    http.get_json("https://h/p", extra_headers={"fncc": "C100"})
    h = data_tr.calls[0]["headers"]
    # 三头照常下发
    assert h["Authorization"] == "Bearer jwt-1"
    assert h["T-CODE"] == "indx"
    assert h["X-Operator-ID"] == "u-42"
    # extra_headers 叠加下发
    assert h["fncc"] == "C100"


def test_get_page_merges_extra_headers():
    sess = _session()
    data_tr = FakeTransport([FakeResponse(200, {"content": [{"a": 1}], "totalElements": 1, "last": True})])
    http = HttpClient(sess, transport=data_tr)
    page = http.get_page("https://h/p", {"page": "0"}, requested_size=20, extra_headers={"fncc": "C200"})
    assert isinstance(page, Page)
    h = data_tr.calls[0]["headers"]
    assert h["Authorization"] == "Bearer jwt-1"
    assert h["fncc"] == "C200"


def test_post_page_merges_extra_headers():
    sess = _session()
    data_tr = FakeTransport([FakeResponse(200, {"content": [{"a": 1}], "last": True})])
    http = HttpClient(sess, transport=data_tr)
    http.post_page("https://h/p", body={"f": 1}, requested_size=20, extra_headers={"fncc": "C300"})
    h = data_tr.calls[0]["headers"]
    assert h["Authorization"] == "Bearer jwt-1"
    assert h["fncc"] == "C300"


def test_extra_headers_overrides_session_header_on_name_collision():
    sess = _session()
    data_tr = FakeTransport([FakeResponse(200, {"id": 1})])
    http = HttpClient(sess, transport=data_tr)
    # 同名 T-CODE：extra_headers 覆盖 session 值
    http.get_json("https://h/p", extra_headers={"T-CODE": "OVERRIDE"})
    h = data_tr.calls[0]["headers"]
    assert h["T-CODE"] == "OVERRIDE"
    assert h["Authorization"] == "Bearer jwt-1"  # 其余三头不受影响


def test_extra_headers_does_not_pollute_session_cache():
    sess = _session()
    data_tr = FakeTransport([FakeResponse(200, {"id": 1}), FakeResponse(200, {"id": 2})])
    http = HttpClient(sess, transport=data_tr)
    # 第一次带 fncc
    http.get_json("https://h/p", extra_headers={"fncc": "C100"})
    # 第二次不带 → 不应残留 fncc（请求级临时叠加，不写回 session）
    http.get_json("https://h/p2")
    assert "fncc" in data_tr.calls[0]["headers"]
    assert "fncc" not in data_tr.calls[1]["headers"]
    # session.headers() 本身未被污染
    assert "fncc" not in sess.headers()


def test_no_extra_headers_request_has_no_company_code_header():
    """fncc 误发防护（前置断言）：不传 extra_headers → 请求不含 fncc。"""
    sess = _session()
    data_tr = FakeTransport([FakeResponse(200, {"content": [], "last": True})])
    http = HttpClient(sess, transport=data_tr)
    http.get_page("https://h/p", requested_size=20)
    h = data_tr.calls[0]["headers"]
    assert "fncc" not in h
    # 基线头集：三认证头 + Accept（对齐 CLI、修 wm /bins/page 内容协商 500）。
    assert set(h.keys()) == {"Authorization", "T-CODE", "X-Operator-ID", "Accept"}


def test_extra_headers_none_is_default_old_behavior():
    """extra_headers 默认 None：请求 header 与改造前完全一致（只含三头）。"""
    sess = _session()
    data_tr = FakeTransport([FakeResponse(200, {"id": 7})])
    http = HttpClient(sess, transport=data_tr)
    http.get_json("https://h/p")  # 不传 extra_headers
    h = data_tr.calls[0]["headers"]
    # 基线头集：三认证头 + Accept（对齐 CLI；extra_headers=None 不额外污染）。
    assert set(h.keys()) == {"Authorization", "T-CODE", "X-Operator-ID", "Accept"}
