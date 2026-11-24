"""门禁 A：Streamable HTTP transport 单测（handle_http 纯函数 + 真 socket 冒烟）。

延续 C→B：handle_http 是传输无关请求处理核 handle_request 的薄 HTTP 适配（纯函数可单测），
真 socket 仅冒烟。协议核 handle_request 一行不改——本测试证实「换 framing 不动协议核」。
依据 MCP Streamable HTTP spec（2025-03-26 引入）：单 endpoint /mcp，POST→200 application/json
或 202（notification），GET/DELETE→405，绑 127.0.0.1，Origin 校验→403。
"""
import json
import sys
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import in3_mcp  # noqa: E402
from in3_mcp import handle_http, make_http_server  # noqa: E402


@dataclass
class FakeResult:
    stdout: str = "RESULT-OK"
    stderr: str = ""
    exit_code: int = 0
    duration_s: float = 0.1
    truncated: bool = False


def _executor(captured=None):
    def ex(code, timeout, tenant=None):
        if captured is not None:
            captured.append((code, timeout, tenant))
        return FakeResult()
    return ex


def _init_body():
    return json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}).encode()


# ---------- POST 主路：request → 200 application/json ----------

def test_post_initialize_returns_200_json():
    r = handle_http("POST", "/mcp", {}, _init_body(), _executor())
    assert r.status == 200
    assert r.content_type == "application/json"
    msg = json.loads(r.body)
    assert msg["result"]["serverInfo"]["name"]
    assert msg["result"]["protocolVersion"]


def test_post_tools_call_invokes_executor_and_returns_content():
    captured = []
    body = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                       "params": {"name": "execute_code",
                                  "arguments": {"code": "print(1)", "tenant": "indx"}}}).encode()
    r = handle_http("POST", "/mcp", {}, body, _executor(captured))
    assert r.status == 200
    assert json.loads(r.body)["result"]["content"][0]["text"] == "RESULT-OK"
    assert captured == [("print(1)", None, "indx")]


# ---------- POST notification → 202 no body（MCP spec MUST）----------

def test_post_notification_returns_202_no_body():
    body = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode()
    r = handle_http("POST", "/mcp", {}, body, _executor())
    assert r.status == 202
    assert r.body == b""


# ---------- 坏 JSON → 400（body MAY 带 parse error）----------

def test_post_bad_json_returns_400_parse_error():
    r = handle_http("POST", "/mcp", {}, b"not-json{", _executor())
    assert r.status == 400
    assert b"-32700" in r.body


# ---------- GET / DELETE → 405（不提供 SSE / 不允许 client 终止 session）----------

def test_get_returns_405():
    assert handle_http("GET", "/mcp", {}, b"", _executor()).status == 405


def test_delete_returns_405():
    assert handle_http("DELETE", "/mcp", {}, b"", _executor()).status == 405


# ---------- 错误 path → 404 ----------

def test_wrong_path_returns_404():
    assert handle_http("POST", "/wrong", {}, _init_body(), _executor()).status == 404


# ---------- Origin 校验（DNS rebinding 防护，spec MUST）----------

def test_invalid_origin_returns_403():
    r = handle_http("POST", "/mcp", {"Origin": "http://evil.example.com"}, _init_body(), _executor())
    assert r.status == 403


def test_localhost_origin_allowed():
    for o in ("http://localhost:9000", "http://127.0.0.1:5173"):
        r = handle_http("POST", "/mcp", {"Origin": o}, _init_body(), _executor())
        assert r.status == 200


def test_missing_origin_allowed():
    # 非浏览器发起（无 Origin，如 Claude Desktop 本地直连）→ 放行
    assert handle_http("POST", "/mcp", {}, _init_body(), _executor()).status == 200


def test_origin_header_case_insensitive():
    # HTTP header 名大小写不敏感：小写 origin 也要拦
    r = handle_http("POST", "/mcp", {"origin": "http://evil.example.com"}, _init_body(), _executor())
    assert r.status == 403


# ---------- 真 socket 端到端冒烟（make_http_server）----------

def test_parse_http_addr_variants():
    from in3_mcp import parse_http_addr
    assert parse_http_addr(None) == ("127.0.0.1", 8765)
    assert parse_http_addr("") == ("127.0.0.1", 8765)
    assert parse_http_addr("9000") == ("127.0.0.1", 9000)
    assert parse_http_addr(":9000") == ("127.0.0.1", 9000)
    assert parse_http_addr("127.0.0.1:9000") == ("127.0.0.1", 9000)
    assert parse_http_addr("0.0.0.0:8080") == ("0.0.0.0", 8080)
    assert parse_http_addr("myhost") == ("myhost", 8765)


def test_server_binds_localhost_only():
    httpd = make_http_server(_executor(), host="127.0.0.1", port=0)
    try:
        assert httpd.server_address[0] == "127.0.0.1"
    finally:
        httpd.server_close()


def test_real_socket_post_and_get():
    httpd = make_http_server(_executor(), host="127.0.0.1", port=0)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/mcp", data=_init_body(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
            assert resp.headers.get("Content-Type") == "application/json"
            assert json.loads(resp.read())["result"]["protocolVersion"]
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/mcp", timeout=5)
            assert False, "GET 应 405"
        except urllib.error.HTTPError as e:
            assert e.code == 405
    finally:
        httpd.shutdown()
        httpd.server_close()
