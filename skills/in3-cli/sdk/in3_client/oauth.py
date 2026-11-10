"""浏览器 OAuth 2.0 Authorization Code + PKCE + loopback 回调（ADR-0003 / issue #8）。

**门禁状态（2026-06-02 M0.5 实证）**：真 prod UAAS 的 /uaas/oauth/authorize 对所有请求
一律返 401「服务异常」(problem+json)，纯客户端浏览器 auth-code 流**当前后端不支持**（需后端
改造）。故 browser_login 默认探测 authorize_available()，不可用即抛 BrowserOAuthUnavailable，
调用方降级到 password-grant + refresh-token（auth.Session）兜底。

本模块的 PKCE/URL/callback/code 交换逻辑**已就位且单测覆盖**：后端一旦放开 authorize 端点，
去掉门禁即为可用主路（client_secret 实测仍必带，非 PKCE-only 公开客户端）。
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import secrets
import threading
import urllib.parse
import webbrowser
from typing import Callable, Optional

from ._transport import default_transport
from .auth import AuthFailedError, Token, _is_json
from .config import Credentials


class BrowserOAuthUnavailable(Exception):
    """当前后端 UAAS 不支持纯客户端浏览器 auth-code 流（authorize 端点 401）。"""


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def generate_pkce() -> tuple[str, str]:
    """生成 (code_verifier, code_challenge)：verifier=base64url(32B 随机)，challenge=S256。"""
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def build_authorize_url(uaas_host: str, client_id: str, redirect_uri: str, challenge: str, state: str) -> str:
    q = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    })
    return uaas_host.rstrip("/") + "/uaas/oauth/authorize?" + q


def parse_callback(query_string: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """解析 loopback 回调 query → (code, state, error)。"""
    q = urllib.parse.parse_qs(query_string)
    err = q.get("error", [None])[0]
    if err:
        return None, q.get("state", [None])[0], err
    return q.get("code", [None])[0], q.get("state", [None])[0], None


def authorize_available(transport: Callable, cred: Credentials, client_id: str) -> bool:
    """探测 authorize 端点是否能服务浏览器登录页（非 401/problem）。当前后端 → False。"""
    url = cred.uaas_host.rstrip("/") + "/uaas/oauth/authorize"
    params = {"response_type": "code", "client_id": client_id,
              "redirect_uri": "http://127.0.0.1:0/callback",
              "code_challenge": "probe", "code_challenge_method": "S256", "state": "probe"}
    try:
        resp = transport("GET", url, params=params)
    except Exception:
        return False
    ct = resp.headers.get("content-type", "") if resp.headers else ""
    if "problem" in ct:
        return False
    return resp.status_code in (200, 302, 303)


def exchange_code(
    transport: Callable, cred: Credentials, code: str, verifier: str,
    redirect_uri: str, client_id: str, client_secret: str,
) -> Token:
    """用 authorization_code 换 token（redirect_uri 与授权请求逐字一致；client_secret 实测必带）。"""
    url = cred.uaas_host.rstrip("/") + "/uaas/oauth/token"
    params = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    resp = transport("POST", url, params=params)
    if resp.status_code != 200 or not _is_json(resp):
        raise AuthFailedError(f"code 交换失败：{url} → {resp.status_code} / ct={resp.headers.get('content-type','')}")
    body = resp.json() or {}
    if not body.get("access_token"):
        raise AuthFailedError(f"code 交换 200 但无 access_token：{body!r}")
    return Token(
        access_token=body["access_token"],
        tenant_id=body.get("tenant_id", ""),
        tenant_domain=body.get("tenant_domain", cred.tenant_domain),
        user_id=body.get("user_id", ""),
        refresh_token=body.get("refresh_token", ""),
    )


# ---------- loopback 回调服务（集成路径，HITL）----------

class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    result: dict = {}

    def do_GET(self):  # noqa: N802
        code, state, err = parse_callback(urllib.parse.urlparse(self.path).query)
        _CallbackHandler.result = {"code": code, "state": state, "error": err}
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        msg = "登录失败，可关闭本页" if err else "登录完成，可关闭本页返回终端"
        self.wfile.write(f"<html><body><h3>{msg}</h3></body></html>".encode("utf-8"))

    def log_message(self, *a):  # 静音
        pass


def browser_login(
    cred: Credentials,
    transport: Optional[Callable] = None,
    open_browser: bool = True,
    client_id: str = None,
    client_secret: str = None,
    timeout_s: int = 120,
) -> Token:
    """浏览器 OAuth 主路（门禁：authorize 不可用即抛 BrowserOAuthUnavailable 让调用方降级）。"""
    from .auth import DEFAULT_CLIENT_ID, DEFAULT_CLIENT_SECRET  # noqa: PLC0415
    transport = transport or default_transport()
    client_id = client_id or DEFAULT_CLIENT_ID
    client_secret = client_secret or DEFAULT_CLIENT_SECRET

    if not authorize_available(transport, cred, client_id):
        raise BrowserOAuthUnavailable(
            "当前后端 UAAS /uaas/oauth/authorize 不可用（401）。浏览器 OAuth 顺延，"
            "请用 password-grant + refresh-token 兜底（见 ADR-0003 M0.5 实证）。"
        )

    verifier, challenge = generate_pkce()
    state = secrets.token_urlsafe(16)
    _CallbackHandler.result = {}
    server = http.server.HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    port = server.server_address[1]
    redirect_uri = f"http://127.0.0.1:{port}/callback"
    try:
        url = build_authorize_url(cred.uaas_host, client_id, redirect_uri, challenge, state)
        if open_browser:
            webbrowser.open(url)
        else:
            print(f"在浏览器打开授权：{url}")
        t = threading.Thread(target=server.handle_request)  # 处理一次回调
        t.start()
        t.join(timeout=timeout_s)
        res = _CallbackHandler.result
        if not res:
            raise AuthFailedError("浏览器授权超时，未收到回调")
        if res.get("error"):
            raise AuthFailedError(f"授权被拒/IdP 报错：{res['error']}")
        if res.get("state") != state:
            raise AuthFailedError("state 不匹配（可能 CSRF/串号），拒绝换 token")
        return exchange_code(transport, cred, res["code"], verifier, redirect_uri, client_id, client_secret)
    finally:
        server.server_close()
