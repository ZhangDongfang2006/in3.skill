"""真实 dispatcher 子进程 + 本地 HTTP：登录验证、并发续期和跨命令持久化。"""
import base64
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlsplit

import pytest


@pytest.fixture
def auth_backend():
    def segment(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()

    token = ".".join([segment({"alg": "RS256"}), segment({"sub": "corp:test@indx",
                       "tenant_domain": "indx", "tenant_id": "99979", "user_id": "fixture-user",
                       "exp": int(time.time()) + 3600}), "fixture-signature"])
    state = {"token": token, "reject_old": False, "reject_refresh": False, "grants": [], "headers": [],
             "validation_status": 200, "validation_type": "application/json"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, body, content_type="application/json"):
            raw = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            path = urlsplit(self.path)
            if "currencies/page" in path.path:
                status = state["validation_status"]
                if status == 302:
                    self.send_response(302)
                    self.send_header("Location", "/redirected")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if status != 200 or state["validation_type"] != "application/json":
                    self.reply(status, {"message": "private-response"}, state["validation_type"])
                    return
            if path.path.endswith("/uaas/oauth/token"):
                params = parse_qs(path.query)
                state["grants"].append(params)
                if params.get("grant_type") != ["refresh_token"] or state["reject_refresh"]:
                    self.reply(400, {"error": "invalid_grant"})
                else:
                    self.reply(200, {"access_token": "AT2", "refresh_token": "RT2"})
                return
            self.data_response()

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.data_response()

        def data_response(self):
            state["headers"].append(dict(self.headers))
            if state["reject_old"] and self.headers.get("Authorization") != "Bearer AT2":
                self.reply(401, {"error": "invalid_token"})
            else:
                self.reply(200, {"content": [{"id": "fixture"}], "number": 0, "last": True})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/service", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def invoke(tmp_path, args, stdin=None):
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    pointer = tmp_path / "pointer.json"
    pointer.write_text(json.dumps({"path": str(ws)}))
    code = ("import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
            "import in3_cli; in3_cli.WORKSPACE_POINTER=Path(sys.argv[2]); "
            "sys.exit(in3_cli.main(sys.argv[3:]))")
    return subprocess.run([sys.executable, "-c", code, str(Path(__file__).parent), str(pointer), *args],
                          input=stdin, capture_output=True, text=True, timeout=15)


def test_login_and_parallel_commands_refresh_once_and_persist(auth_backend, tmp_path):
    host, state = auth_backend
    result = invoke(tmp_path, ["login", "indx", "--paste-token", "--token-stdin", "--env", "custom",
                               "--api-host", host, "--refresh-token", "RT1"], state["token"])
    assert result.returncode == 0, result.stderr
    assert "自动续期" in result.stdout
    assert len(state["headers"]) == 1 and state["grants"] == []
    state["reject_old"] = True
    command = ["exec", "sf", "sim-issue", "list", "--size", "1"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: invoke(tmp_path, command), range(2)))
    for result in results:
        assert result.returncode == 0, result.stderr + result.stdout
        assert json.loads(result.stdout)["items"][0]["id"] == "fixture"
    assert len(state["grants"]) == 1
    assert state["grants"][0]["grant_type"] == ["refresh_token"]
    path = tmp_path / "ws/config/tenants/indx/credentials.json"
    stored = json.loads(path.read_text())
    assert stored["access_token"] == "AT2" and stored["refresh_token"] == "RT2"
    assert stored["tenant_id"] == "99979" and stored["user_id"] == "fixture-user"
    assert invoke(tmp_path, command).returncode == 0
    assert len(state["grants"]) == 1


def test_invalid_token_login_does_not_write_credentials(auth_backend, tmp_path):
    host, state = auth_backend
    state["reject_old"] = True
    result = invoke(tmp_path, ["login", "indx", "--paste-token", "--token-stdin", "--env", "custom",
                               "--api-host", host], state["token"])
    assert result.returncode != 0
    assert "401" in result.stderr and "登录成功" not in result.stdout
    assert not (tmp_path / "ws/config/tenants/indx/credentials.json").exists()
    assert state["grants"] == []


def test_refresh_rejection_never_sends_password_grant(auth_backend, tmp_path):
    host, state = auth_backend
    assert invoke(tmp_path, ["login", "indx", "--paste-token", "--token-stdin", "--env", "custom",
                            "--api-host", host, "--refresh-token", "RT1"], state["token"]).returncode == 0
    state["reject_old"] = state["reject_refresh"] = True
    result = invoke(tmp_path, ["exec", "sf", "sim-issue", "list", "--size", "1"])
    assert result.returncode != 0
    assert json.loads(result.stdout)["error"]["type"] == "AUTH_FAILED"
    assert [grant["grant_type"] for grant in state["grants"]] == [["refresh_token"]]


@pytest.mark.parametrize("status,content_type", [(403, "application/json"), (500, "application/json"),
                                              (302, "application/json"), (200, "text/html")])
def test_validation_errors_and_redirects_do_not_save_or_expose_response(auth_backend, tmp_path, status, content_type):
    host, state = auth_backend
    state["validation_status"] = status
    state["validation_type"] = content_type
    result = invoke(tmp_path, ["login", "indx", "--paste-token", "--token-stdin", "--env", "custom",
                               "--api-host", host], state["token"])
    assert result.returncode != 0
    assert "private-response" not in result.stdout + result.stderr
    assert state["headers"] == []  # 不跟随重定向到数据端点。
    assert not (tmp_path / "ws/config/tenants/indx/credentials.json").exists()
