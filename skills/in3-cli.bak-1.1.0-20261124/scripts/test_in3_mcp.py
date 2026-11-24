"""v2 MCP server (in3_mcp) 单测：handle_request 协议核 + serve_stdio 薄壳。

executor 注入桩（不真跑子进程），聚焦 JSON-RPC 2.0 协议 + execute_code 工具语义。
in3_mcp 不 import in3_run——result 鸭子类型，核传输无关（C→B 哲学延续）。
"""
import io
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import in3_mcp  # noqa: E402
from in3_mcp import handle_request, serve_stdio  # noqa: E402


@dataclass
class FakeResult:
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    duration_s: float = 0.1
    truncated: bool = False


def _executor(captured, result=None):
    """返回一个记录调用 + 回传固定 result 的 executor 桩。

    executor 签名 (code, timeout, tenant)：tenant 为 v2 多租户 session-scoped 路由的
    每请求目标租户 alias（省略时 None，由 dispatcher 侧回退当前 active tenant）。
    """
    def ex(code, timeout, tenant=None):
        captured.append((code, timeout, tenant))
        return result or FakeResult(stdout="RESULT-OK")
    return ex


# ---------- initialize ----------

def test_initialize_returns_server_info():
    resp = handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, _executor([]))
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    assert resp["result"]["serverInfo"]["name"] == "in3-cli"
    assert "tools" in resp["result"]["capabilities"]
    assert resp["result"]["protocolVersion"]


# ---------- initialize 版本协商（门禁 A：HTTP host 期望现代 revision，传输无关）----------

def test_initialize_default_protocol_version_is_modern_not_2024():
    # 不带 protocolVersion → 兜底现代版（SHOULD latest），不再报死的旧 2024-11-05
    resp = handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, _executor([]))
    pv = resp["result"]["protocolVersion"]
    assert pv != "2024-11-05"
    assert pv >= "2025-03-26"  # Streamable HTTP 引入版本，ISO 串可字典序比较


def test_initialize_echoes_requested_supported_version():
    resp = handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-03-26"}}, _executor([]))
    assert resp["result"]["protocolVersion"] == "2025-03-26"


def test_initialize_unknown_version_falls_back_to_default():
    resp = handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "1999-01-01"}}, _executor([]))
    assert resp["result"]["protocolVersion"] == in3_mcp.PROTOCOL_VERSION


def test_initialize_explicit_legacy_version_still_echoed_for_compat():
    # 老 client 显式要 2024-11-05 → 回声（向后兼容，仍在 SUPPORTED 集内）
    resp = handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05"}}, _executor([]))
    assert resp["result"]["protocolVersion"] == "2024-11-05"


# ---------- tools/list ----------

def test_tools_list_exposes_single_execute_code():
    resp = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, _executor([]))
    tools = resp["result"]["tools"]
    assert len(tools) == 1
    t = tools[0]
    assert t["name"] == "execute_code"
    assert t["inputSchema"]["required"] == ["code"]
    assert "code" in t["inputSchema"]["properties"]
    assert "timeout" in t["inputSchema"]["properties"]
    # v2 多租户：tenant 是可选入参（不在 required），schema 显式声明便于 host 端发现
    assert "tenant" in t["inputSchema"]["properties"]
    assert "tenant" not in t["inputSchema"]["required"]


# ---------- tools/call: execute_code ----------

def test_tools_call_invokes_executor_with_code_and_timeout():
    captured = []
    resp = handle_request(
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "execute_code", "arguments": {"code": "print(1)", "timeout": 60}}},
        _executor(captured))
    assert captured == [("print(1)", 60, None)]
    assert resp["result"]["content"][0]["type"] == "text"
    assert resp["result"]["content"][0]["text"] == "RESULT-OK"
    assert resp["result"]["isError"] is False


def test_tools_call_timeout_optional_passes_none():
    captured = []
    handle_request(
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "execute_code", "arguments": {"code": "print(1)"}}},
        _executor(captured))
    assert captured == [("print(1)", None, None)]


def test_tools_call_passes_tenant_to_executor():
    # v2 多租户：arguments.tenant 透传给 executor（每请求显式路由目标租户）
    captured = []
    handle_request(
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "execute_code",
                    "arguments": {"code": "print(1)", "tenant": "zhuzheng"}}},
        _executor(captured))
    assert captured == [("print(1)", None, "zhuzheng")]


def test_tools_call_no_tenant_passes_none():
    # 省略 tenant → executor 收 None（dispatcher 侧回退当前 active tenant）
    captured = []
    handle_request(
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "execute_code", "arguments": {"code": "print(1)"}}},
        _executor(captured))
    assert captured == [("print(1)", None, None)]


def test_tools_call_nonzero_exit_marks_iserror_and_surfaces_stderr():
    captured = []
    resp = handle_request(
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "execute_code", "arguments": {"code": "x"}}},
        _executor(captured, FakeResult(stdout="oops", stderr="boom", exit_code=3)))
    assert resp["result"]["isError"] is True
    text = resp["result"]["content"][0]["text"]
    assert "exit_code=3" in text
    assert "boom" in text


def test_tools_call_truncated_flag_surfaced():
    resp = handle_request(
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
         "params": {"name": "execute_code", "arguments": {"code": "x"}}},
        _executor([], FakeResult(stdout="big", truncated=True)))
    assert "truncat" in resp["result"]["content"][0]["text"].lower()


def test_tools_call_missing_code_is_invalid_params():
    resp = handle_request(
        {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
         "params": {"name": "execute_code", "arguments": {}}}, _executor([]))
    assert resp["error"]["code"] == -32602


def test_tools_call_unknown_tool_errors():
    resp = handle_request(
        {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
         "params": {"name": "nope", "arguments": {}}}, _executor([]))
    assert resp["error"]["code"] == -32602


def test_executor_not_called_on_bad_tool_call():
    # 缺 code / 未知工具时绝不调 executor（不空跑子进程）
    captured = []
    handle_request(
        {"jsonrpc": "2.0", "id": 8, "method": "tools/call",
         "params": {"name": "execute_code", "arguments": {}}}, _executor(captured))
    handle_request(
        {"jsonrpc": "2.0", "id": 8, "method": "tools/call",
         "params": {"name": "nope", "arguments": {"code": "x"}}}, _executor(captured))
    assert captured == []


# ---------- resolve_tenant 纯路由策略 ----------

def test_resolve_tenant_requested_known_wins():
    alias, err = in3_mcp.resolve_tenant("zhuzheng", default="indx", known=["indx", "zhuzheng"])
    assert (alias, err) == ("zhuzheng", None)


def test_resolve_tenant_omitted_falls_back_to_default():
    alias, err = in3_mcp.resolve_tenant(None, default="indx", known=["indx", "zhuzheng"])
    assert (alias, err) == ("indx", None)


def test_resolve_tenant_unknown_requested_errors_with_known_list():
    alias, err = in3_mcp.resolve_tenant("ghost", default="indx", known=["indx", "zhuzheng"])
    assert alias is None
    assert err and "ghost" in err and "zhuzheng" in err  # 报错列出已知租户便于排查


def test_resolve_tenant_no_request_no_default_errors():
    alias, err = in3_mcp.resolve_tenant(None, default=None, known=["indx"])
    assert alias is None
    assert err and ("tenant" in err.lower() or "租户" in err)


# ---------- notifications / unknown ----------

def test_initialized_notification_no_response():
    resp = handle_request(
        {"jsonrpc": "2.0", "method": "notifications/initialized"}, _executor([]))
    assert resp is None


def test_unknown_method_returns_method_not_found():
    resp = handle_request({"jsonrpc": "2.0", "id": 9, "method": "foo/bar"}, _executor([]))
    assert resp["error"]["code"] == -32601


def test_invalid_jsonrpc_version_rejected():
    resp = handle_request({"jsonrpc": "1.0", "id": 9, "method": "initialize"}, _executor([]))
    assert resp["error"]["code"] == -32600


# ---------- serve_stdio 薄壳 ----------

def test_serve_stdio_roundtrip():
    lines = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": "execute_code", "arguments": {"code": "print(1)"}}}),
    ]
    stdin = io.StringIO("\n".join(lines) + "\n")
    stdout = io.StringIO()
    serve_stdio(_executor([]), stdin=stdin, stdout=stdout)
    out = [l for l in stdout.getvalue().splitlines() if l.strip()]
    assert len(out) == 2
    assert json.loads(out[0])["result"]["serverInfo"]["name"] == "in3-cli"
    assert json.loads(out[1])["result"]["content"][0]["text"] == "RESULT-OK"


def test_serve_stdio_notification_yields_no_output_line():
    stdin = io.StringIO(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
    stdout = io.StringIO()
    serve_stdio(_executor([]), stdin=stdin, stdout=stdout)
    assert stdout.getvalue().strip() == ""


def test_serve_stdio_parse_error_does_not_crash():
    stdin = io.StringIO(
        "not-json\n" + json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}) + "\n")
    stdout = io.StringIO()
    serve_stdio(_executor([]), stdin=stdin, stdout=stdout)
    out = [l for l in stdout.getvalue().splitlines() if l.strip()]
    assert len(out) == 2
    assert json.loads(out[0])["error"]["code"] == -32700


# ---------- 端到端 tracer：MCP → 真执行核 ----------

def test_end_to_end_real_execute(tmp_path):
    """executor 绑真 in3_run.execute（真子进程跑 print），验证 MCP → 执行核全链路打通。

    print 不调后端，无需真凭证——证实 execute_code → ExecuteResult → MCP content 端到端。
    """
    import os
    import in3_run

    def executor(code, timeout, tenant=None):
        ctx = in3_run.ExecuteContext(
            workspace=tmp_path, tenant_alias=tenant or "t",
            env={"PATH": os.environ.get("PATH", "")}, pythonpath=[],
            timeout_s=timeout or 300, audit=False)
        return in3_run.execute(None, code, ctx)

    stdin = io.StringIO(json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "execute_code", "arguments": {"code": "print('mcp-e2e-ok')"}}}) + "\n")
    stdout = io.StringIO()
    serve_stdio(executor, stdin=stdin, stdout=stdout)
    resp = json.loads(stdout.getvalue().strip())
    assert "mcp-e2e-ok" in resp["result"]["content"][0]["text"]
    assert resp["result"]["isError"] is False
