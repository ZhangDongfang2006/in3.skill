"""用本地 HTTP 服务和真实 CLI 子进程验证 SIM 查询、租户路由及大 JSON 管道输出。"""
import json
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest


SCRIPT = Path(__file__).with_name("in3_cli.py")


@pytest.fixture
def backend():
    calls = []
    rows = [{"id": f"i{n}", "description": "明细完整保留" * 5000, "new_field": {"values": [1, None]}}
            for n in range(3)]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send_json(self, data):
            body = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append((self.path, request, dict(self.headers)))
            page, size = request["page"], request["size"]
            self.send_json({"content": rows[page * size:(page + 1) * size], "number": page,
                            "total_elements": 3, "last": (page + 1) * size >= 3})

        def do_GET(self):
            issue_id = self.path.rsplit("/", 1)[1]
            calls.append((self.path, None, dict(self.headers)))
            self.send_json({"id": issue_id, "action_list": [{"attachments": [{"name": "证据"}]}]})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/service", rows, calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def workspace(path, host):
    current = path / "config/current-tenant.json"
    current.parent.mkdir(parents=True)
    current.write_text(json.dumps({"tenant": "other"}))
    for alias, tenant_id in (("other", "12345"), ("target", "99979")):
        cred = path / "config/tenants" / alias / "credentials.json"
        cred.parent.mkdir(parents=True)
        cred.write_text(json.dumps({"api_host": host, "tenant_domain": alias, "username": "test",
                                    "auth_mode": "token", "access_token": "fixture-token",
                                    "tenant_id": tenant_id, "user_id": "fixture-user"}))
    return current


def test_real_dispatcher_full_json_pipe_and_details(backend, tmp_path):
    host, rows, calls = backend
    current = workspace(tmp_path / "ws", host)
    pointer = tmp_path / "pointer.json"
    pointer.write_text(json.dumps({"path": str(tmp_path / "ws")}))
    # 使用当前进程固定 workspace pointer，随后执行真实 dispatcher.main 与 exec 子进程。
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import in3_cli; "
            "from pathlib import Path; in3_cli.WORKSPACE_POINTER=Path(sys.argv[2]); "
            "sys.exit(in3_cli.main(sys.argv[3:]))")
    result = subprocess.run([sys.executable, "-c", code, str(SCRIPT.parent), str(pointer),
                             "exec", "--tenant", "target", "sf", "sim-issue", "list", "--all",
                             "--include-details", "--size", "2", "--filter", "status=0"],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr + result.stdout[:500]
    data = json.loads(result.stdout)
    assert len(result.stdout.encode()) > 65536
    assert [row["description"] for row in data["items"]] == [row["description"] for row in rows]
    assert data["truncated"] is False and len(data["items"]) == 3
    assert all(row["detail"]["action_list"] for row in data["items"])
    assert [call[1]["page"] for call in calls if call[1]] == [0, 1]
    assert all("/tenants/99979/ld/sime/issues" in call[0] for call in calls)
    assert all({key.lower(): value for key, value in call[2].items()}["t-code"] == "target"
               for call in calls)
    assert json.loads(current.read_text()) == {"tenant": "other"}
