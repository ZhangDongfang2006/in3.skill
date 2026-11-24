"""v2 MCP server：把传输无关执行核 in3_run.execute 包成单一 execute_code 工具，
经最小 JSON-RPC 2.0 over stdio 暴露（零依赖，不引入官方 mcp SDK——与 dispatcher
「零依赖启动」一脉相承）。

C→B 哲学延续：
  - handle_request 是**传输无关的请求处理核**（纯函数，可单测）；
  - serve_stdio 是薄 I/O 壳（newline-delimited JSON-RPC over stdin/stdout）；
  - executor 是注入的 (code, timeout)->ExecuteResult 闭包——ctx 装配（凭证/workspace/
    PYTHONPATH）在 dispatcher 的 cmd_mcp 壳里绑定。本模块不碰 dispatcher 的 _require_*，
    也不 import in3_run（result 鸭子类型）。
"""
from __future__ import annotations

import json
import sys
import urllib.parse
from collections import namedtuple
from typing import Callable, Optional

# MCP 协议版本协商（lifecycle spec）：initialize 回声 client 请求的版本（若在 SUPPORTED 内），
# 否则兜底 PROTOCOL_VERSION（SHOULD = latest）。Streamable HTTP transport 自 2025-03-26 引入，
# 现代 MCP host 期望协商出 2025-03-26+；旧 2024-11-05 仍留在 SUPPORTED 供老 client 回声（向后兼容）。
PROTOCOL_VERSION = "2025-06-18"  # 默认/兜底（生态最广的现代 revision）
SUPPORTED_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
SERVER_NAME = "in3-cli"
SERVER_VERSION = "0.1.0"

# JSON-RPC 2.0 标准错误码
_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602
_PARSE_ERROR = -32700

EXECUTE_CODE_TOOL = {
    "name": "execute_code",
    "description": (
        "在隔离子进程跑一段 `import in3_client` 的只读 Python，注入当前租户凭证；"
        "脚本只 print 最终结果——中间数据留在子进程、不回流进上下文。"
        "用于跨 IN3 模块（mm/wm/sd/md/pp/qm/cr/fn）的组合分析。"
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "要执行的 Python 源码（import in3_client 调 SDK）"},
            "timeout": {"type": "number", "description": "超时秒数（默认 300；超时退出码 124）"},
            "tenant": {"type": "string", "description": "目标租户 alias；省略用 server 默认（当前 active tenant）。常驻 server 多租户时每请求显式指定。"},
        },
        "required": ["code"],
    },
}

Executor = Callable[[str, Optional[float], Optional[str]], object]  # (code, timeout, tenant) -> ExecuteResult-like


def resolve_tenant(requested, default, known):
    """v2 多租户路由策略（纯函数，传输/凭证无关）。

    常驻 server 不能靠全局 current-tenant，故每请求显式带 tenant：
      - requested 给定且已知 → 用它；
      - requested 省略 → 回退 server 默认（启动时的 active tenant）；
      - requested 未知 / 无默认可回退 → (None, 错误说明)，由 executor 返错误结果不崩。

    返回 (alias, error)：error 非 None 时 alias 必为 None。
    """
    known = list(known or [])
    if requested:
        if requested in known:
            return requested, None
        return None, f"unknown tenant: {requested!r}（已知: {known}）"
    if default:
        return default, None
    return None, "no tenant: 请在 execute_code 入参指定 tenant，或先 login/use 设当前租户"


def _result(req_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _format_execute_result(r) -> dict:
    """ExecuteResult-like → MCP tools/call result。stdout 为主体，附 exit_code/stderr/truncated。

    isError 取 exit_code != 0（含超时的 124）——让 MCP host 能区分成功/失败。
    """
    text = r.stdout or ""
    extras = []
    if r.exit_code != 0:
        extras.append(f"[exit_code={r.exit_code}]")
    if r.stderr:
        extras.append(f"[stderr]\n{r.stderr}")
    if r.truncated:
        extras.append("[output truncated @64KB]")
    if extras:
        text = (text + "\n" + "\n".join(extras)) if text else "\n".join(extras)
    return {"content": [{"type": "text", "text": text}], "isError": r.exit_code != 0}


def negotiate_protocol_version(requested) -> str:
    """initialize 版本协商（传输无关）：client 请求的版本在 SUPPORTED 内则回声，否则兜底
    PROTOCOL_VERSION（SHOULD latest）。stdio 与 HTTP 共用——版本协商是协议正确性，不属传输层。"""
    return requested if requested in SUPPORTED_PROTOCOL_VERSIONS else PROTOCOL_VERSION


def handle_request(request, executor: Executor) -> Optional[dict]:
    """处理单个 JSON-RPC 2.0 request → response dict；notification（无 id）返回 None（不响应）。

    传输无关：不读 stdin/不写 stdout、不碰凭证装配——执行经注入的 executor。
    """
    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
        rid = request.get("id") if isinstance(request, dict) else None
        return _error(rid, _INVALID_REQUEST, "invalid JSON-RPC 2.0 request")

    req_id = request.get("id")
    method = request.get("method")
    is_notification = "id" not in request

    if method == "initialize":
        requested = (request.get("params") or {}).get("protocolVersion")
        return _result(req_id, {
            "protocolVersion": negotiate_protocol_version(requested),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return _result(req_id, {"tools": [EXECUTE_CODE_TOOL]})

    if method == "tools/call":
        params = request.get("params") or {}
        name = params.get("name")
        if name != "execute_code":
            return _error(req_id, _INVALID_PARAMS, f"unknown tool: {name!r}")
        arguments = params.get("arguments") or {}
        code = arguments.get("code")
        if not isinstance(code, str) or not code:
            return _error(req_id, _INVALID_PARAMS, "execute_code requires non-empty 'code' (string)")
        timeout = arguments.get("timeout")
        tenant = arguments.get("tenant")  # v2：每请求显式路由目标租户（None=用 server 默认）
        result = executor(code, timeout, tenant)
        return _result(req_id, _format_execute_result(result))

    # 未知 method：notification 静默丢，request 回 method not found
    if is_notification:
        return None
    return _error(req_id, _METHOD_NOT_FOUND, f"method not found: {method!r}")


def _write_message(stdout, msg: dict) -> None:
    stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    stdout.flush()


def serve_stdio(executor: Executor, stdin=None, stdout=None) -> None:
    """最小 JSON-RPC over stdio 主循环：逐行读 request → handle_request → 写 response。

    newline-delimited JSON（MCP stdio transport：每条 message 一行、无内嵌换行）。
    notification（handle_request 返 None）不写响应；解析失败回 parse error、不崩。
    """
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            _write_message(stdout, _error(None, _PARSE_ERROR, "parse error"))
            continue
        response = handle_request(request, executor)
        if response is not None:
            _write_message(stdout, response)


# ---------- 门禁 A：Streamable HTTP transport（MCP spec 2025-03-26+，零依赖 stdlib）----------
#
# 单 endpoint /mcp：POST request→200 application/json、POST notification→202 无 body、
# 坏 JSON→400；GET/DELETE→405（不提供 SSE / 不允许 client 终止 session）；Origin 非法→403。
# handle_http 是 handle_request 的薄 HTTP 适配（纯函数，可单测）——只换 framing，协议核不动。

HttpResponse = namedtuple("HttpResponse", "status content_type body")

_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


def _get_header(headers, name: str):
    """大小写不敏感取 header（http.server 的 Message 与普通 dict 都适配）。"""
    v = headers.get(name)
    if v is not None:
        return v
    low = name.lower()
    for k in headers:
        if k.lower() == low:
            return headers[k]
    return None


def _origin_allowed(origin, allowed_origins) -> bool:
    """Origin 校验（DNS rebinding 防护，spec MUST）。无 Origin（非浏览器直连）放行；
    allowed_origins=None 时默认放行 localhost/127.0.0.1/::1（任意 scheme/port）。"""
    if not origin:
        return True
    if allowed_origins is not None:
        return origin in allowed_origins
    return urllib.parse.urlparse(origin).hostname in _LOCAL_HOSTS


def handle_http(method, path, headers, body, executor: Executor,
                *, mcp_path: str = "/mcp", allowed_origins=None) -> HttpResponse:
    """传输无关协议核 handle_request 的薄 HTTP 适配（纯函数，可单测）。

    返回 HttpResponse(status, content_type, body_bytes)：
      POST mcp_path → request 返 200 application/json；notification 返 202 无 body；坏 JSON 返 400。
      GET/DELETE mcp_path → 405；其它 path → 404；Origin 非法 → 403。
    """
    if path != mcp_path:
        return HttpResponse(404, "text/plain; charset=utf-8", b"not found")
    if method == "POST":
        if not _origin_allowed(_get_header(headers, "Origin"), allowed_origins):
            return HttpResponse(403, "text/plain; charset=utf-8", b"forbidden: invalid Origin")
        try:
            request = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            err = _error(None, _PARSE_ERROR, "parse error")
            return HttpResponse(400, "application/json", json.dumps(err, ensure_ascii=False).encode("utf-8"))
        response = handle_request(request, executor)
        if response is None:  # notification → 202 Accepted, no body（MCP spec MUST）
            return HttpResponse(202, None, b"")
        return HttpResponse(200, "application/json", json.dumps(response, ensure_ascii=False).encode("utf-8"))
    # GET / DELETE / 其它 method 命中 MCP endpoint：不提供 → 405（spec 显式合法选项）
    return HttpResponse(405, "text/plain; charset=utf-8", b"method not allowed")


def make_http_server(executor: Executor, host: str = "127.0.0.1", port: int = 0,
                     mcp_path: str = "/mcp", allowed_origins=None):
    """构造（不启动）Streamable HTTP MCP server，返回 ThreadingHTTPServer。

    调用方 serve_forever()/shutdown()/server_close()。默认绑 127.0.0.1（spec SHOULD：
    本地只绑 localhost，配合 Origin 校验防 DNS rebinding）。http.server lazy import——
    stdio 路径不付出 http 代价（延续模块零依赖启动）。
    """
    import http.server  # noqa: PLC0415

    class _Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"  # keep-alive；每个响应均设 Content-Length（见下）

        def _dispatch(self, method: str) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            payload = self.rfile.read(length) if length else b""
            resp = handle_http(method, self.path, self.headers, payload, executor,
                               mcp_path=mcp_path, allowed_origins=allowed_origins)
            self.send_response(resp.status)
            if resp.status == 405:
                self.send_header("Allow", "POST")
            if resp.content_type:
                self.send_header("Content-Type", resp.content_type)
            self.send_header("Content-Length", str(len(resp.body)))
            self.end_headers()
            if resp.body:
                self.wfile.write(resp.body)

        def do_POST(self):  # noqa: N802
            self._dispatch("POST")

        def do_GET(self):  # noqa: N802
            self._dispatch("GET")

        def do_DELETE(self):  # noqa: N802
            self._dispatch("DELETE")

        def log_message(self, *a):  # 静音（别污染 stdout/stderr）
            pass

    return http.server.ThreadingHTTPServer((host, port), _Handler)


def parse_http_addr(s, default_host: str = "127.0.0.1", default_port: int = 8765):
    """解析 --http 地址串 → (host, port)。接受 'HOST:PORT' / ':PORT' / 'PORT' / 'HOST' / 空。"""
    s = (s or "").strip()
    if not s:
        return default_host, default_port
    if ":" in s:
        h, _, p = s.rpartition(":")
        return (h or default_host), (int(p) if p else default_port)
    if s.isdigit():
        return default_host, int(s)
    return s, default_port


def serve_http(executor: Executor, host: str = "127.0.0.1", port: int = 8765,
               mcp_path: str = "/mcp", allowed_origins=None) -> None:
    """阻塞启动 Streamable HTTP MCP server（dispatcher cmd_mcp --http 用）。

    ⚠ 单用户、本地凭证：executor 仍由 dispatcher 绑本机 workspace 凭证。多用户/凭证移服务端
    （门禁 B）、托管网关（C）、sandbox（D）是跨团队，不在本传输层。"""
    httpd = make_http_server(executor, host=host, port=port,
                             mcp_path=mcp_path, allowed_origins=allowed_origins)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
