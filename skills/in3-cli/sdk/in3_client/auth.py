"""认证：password-grant token 交换 + refresh 静默刷新 + 三头组装。

（浏览器 OAuth 登录在 oauth.py；当前 prod `/uaas/oauth/authorize` 门禁未放开、运行时降级到
password-grant，见 ADR-0003。本模块只管 password/token 生命周期。）

形状与真 CLI `src/auth/index.ts` 逐位一致：
  GET {uaas_host}/uaas/oauth/token?grant_type=password&username=<corp:u@td>
      &password=<credentials.json 里已 AES 加密的串，直发不解密>
      &client_id=<SPA 共用>&client_secret=<SPA 共用>
  → {access_token, tenant_id, tenant_domain, user_id}
  非 200 / 200-非-JSON / 无 access_token → 认证失败（绝不当空结果）。

数据请求三头：Authorization: Bearer <access_token>; T-CODE: <tenant_domain（取自 token 响应）>;
X-Operator-ID: <user_id（取自 token 响应）>。401 重试逻辑在 http 层（参照源码边界：
auth 负责 token 生命周期，http 负责数据请求 + 重试）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from ._transport import default_transport
from .config import Credentials
from .credential_store import locked_credentials, save_refreshed_token

# 8 模块共用的 SPA OAuth 客户端（与 ibrain-mm/cli src/config/env.ts 同源），可由调用方覆盖。
DEFAULT_CLIENT_ID = "8b80bf13ab4611ea8356000c29ba7340"
DEFAULT_CLIENT_SECRET = "d6223c6102ec47dcb8a9797619dde758"


class AuthFailedError(Exception):
    """换 token 失败（含网关 200-非-JSON、缺 access_token）—— fail-loud，绝不返回空结果。"""


class TokenExpiredError(AuthFailedError):
    """现有 token 被拒且无法续期；必须重新登录，禁止回退口令授权。"""


@dataclass
class Token:
    access_token: str = field(repr=False)
    tenant_id: str
    tenant_domain: str
    user_id: str
    refresh_token: str = field(default="", repr=False)


def _is_json(resp) -> bool:
    ct = resp.headers.get("content-type", "") if resp.headers else ""
    return "json" in ct.lower()


class Session:
    """持有某租户的 token 生命周期。token() 惰性换取并缓存；clear() 强制重换。"""

    def __init__(
        self,
        cred: Credentials,
        transport: Optional[Callable] = None,
        client_id: str = DEFAULT_CLIENT_ID,
        client_secret: str = DEFAULT_CLIENT_SECRET,
        grant_mode: Optional[str] = None,
    ):
        self._cred = cred
        self._transport = transport or default_transport()
        self._client_id = client_id
        self._client_secret = client_secret
        # "password"（SPA 共用 client + AES 口令）或 "client_credentials"（AGENT 机器令牌，
        # client_id/client_secret 即 AGENT 凭证、无 username/password）。后者 token 响应无 user_id/
        # tenant_domain → _token_from_body 回退 cred.tenant_domain 当 T-CODE（须为租户域名如 "indx"）。
        self._grant_mode = grant_mode or cred.auth_mode
        if self._grant_mode not in ("password", "token", "client_credentials"):
            raise ValueError("unknown grant mode")
        self._token: Optional[Token] = None
        self._expired = False

    @classmethod
    def from_token(
        cls,
        cred: Credentials,
        access_token: str,
        refresh_token: str = "",
        tenant_id: str = "",
        tenant_domain: str = "",
        user_id: str = "",
        transport: Optional[Callable] = None,
        client_id: str = DEFAULT_CLIENT_ID,
        client_secret: str = DEFAULT_CLIENT_SECRET,
    ) -> "Session":
        """用现成 token（浏览器/devtools 抓的、或长期 token 粘贴）构造 Session，不走 password-grant。

        绕开被封的 authorize 端点——经 SPA 正常登录（含 SSO/MFA）后捕获 token 即可复用；
        带 refresh_token 时仍可 refresh() 续期。
        """
        s = cls(cred, transport=transport, client_id=client_id, client_secret=client_secret,
                grant_mode="token")
        s._token = Token(
            access_token=access_token,
            tenant_id=tenant_id,
            tenant_domain=tenant_domain or cred.tenant_domain,
            user_id=user_id,
            refresh_token=refresh_token,
        )
        return s

    def token(self) -> Token:
        if self._expired:
            raise TokenExpiredError("Token 已失效且无法续期，请重新 login --browser 或 --paste-token；未尝试口令授权")
        if self._token is None:
            self._token = self._fetch_token()
        return self._token

    def clear(self) -> None:
        self._token = None

    def on_unauthorized(self) -> None:
        """401 仅续期一次；只有明确的口令/机器授权模式允许重新获取 token。"""
        if self.refresh():
            return
        if self._grant_mode == "token":
            self.reject_token()
        self.clear()
        self.token()

    def reject_token(self) -> None:
        """令 token 模式的失效 Session 快速失败；其他模式保留 HttpError 契约。"""
        if self._grant_mode != "token":
            return
        self._expired = True
        self.token()

    def refresh(self) -> bool:
        """用 refresh_token 静默换新 access_token（后端实测支持 grant_type=refresh_token、会轮换）。

        成功更新 token，workspace token 模式同时保存轮换结果；无 refresh_token 或授权被拒返回
        False。连接、存储故障抛 AuthFailedError。调用方只在 password/机器模式允许重新授权。
        """
        if self._token is None or self._expired:
            return False
        path = self._cred.source_path if self._grant_mode == "token" else None
        if path is None:
            return self._refresh_token()
        try:
            with locked_credentials(path) as stored:
                if any(stored.get(k) != getattr(self._cred, k)
                       for k in ("api_host", "tenant_domain", "username")):
                    raise ValueError("凭证身份已改变")
                if stored.get("auth_mode", "token") != "token" or not stored.get("access_token"):
                    raise ValueError("登录方式已改变")
                if stored["access_token"] != self._token.access_token:
                    self._token = self._token_from_body(stored)
                    return True
                if not self._refresh_token():
                    return False
                save_refreshed_token(path, stored, self._token)
                return True
        except (OSError, ValueError):
            raise AuthFailedError("无法安全保存续期凭证（文件不可用或登录已改变），请重新执行登录") from None

    def _refresh_token(self) -> bool:
        if not self._token.refresh_token:
            return False
        url = self._cred.uaas_host.rstrip("/") + "/uaas/oauth/token"
        params = {
            "grant_type": "refresh_token",
            "refresh_token": self._token.refresh_token,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        resp = self._exchange_token(url, params)
        if resp.status_code != 200 or not _is_json(resp):
            return False
        try:
            body = resp.json() or {}
        except ValueError:
            return False
        if not isinstance(body, dict) or not body.get("access_token"):
            return False
        previous = self._token
        refreshed = self._token_from_body(body, previous)
        if any(getattr(previous, k) and str(getattr(previous, k)) != str(getattr(refreshed, k))
               for k in ("tenant_id", "tenant_domain", "user_id")):
            return False
        self._token = refreshed
        return True

    def _exchange_token(self, url: str, params: dict):
        try:
            return self._transport("GET", url, params=params, timeout=15)
        except OSError:
            # 请求异常可能带含口令/refresh_token 的完整 URL，禁止向上游原样转发。
            raise AuthFailedError("连接授权服务失败，未自动重试口令；请稍后重试") from None

    def headers(self) -> dict:
        tok = self.token()
        return {
            "Authorization": f"Bearer {tok.access_token}",
            "T-CODE": tok.tenant_domain,
            "X-Operator-ID": tok.user_id,
            # Accept 对齐 CLI（其 headers() 恒发 Accept: application/json）。某些端点的内容协商依赖它：
            # 缺 Accept 时后端按非 JSON 序列化路径走 → HttpMessageNotWritableException 500
            # （live 2026-06-03 实测 wm /bins/page = storage_bin：缺 Accept→500、带 Accept→200/1612 条）。
            "Accept": "application/json",
        }

    def _fetch_token(self) -> Token:
        if self._grant_mode == "token":
            raise TokenExpiredError("Token 不可用，请重新 login --browser 或 --paste-token；未尝试口令授权")
        url = self._cred.uaas_host.rstrip("/") + "/uaas/oauth/token"
        if self._grant_mode == "client_credentials":
            # AGENT 机器令牌：无 username/password，client_id/secret 即 AGENT 凭证。
            params = {
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            }
        else:
            if any(not isinstance(value, str) or not value.strip()
                   for value in (self._cred.username, self._cred.encrypted_password)):
                raise AuthFailedError("口令授权缺少 username/encrypted_password，未发送请求；请重新登录")
            params = {
                "grant_type": "password",
                "username": self._cred.username,
                "password": self._cred.encrypted_password,  # 直发 AES 串，不解密
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            }
        resp = self._exchange_token(url, params)
        if resp.status_code != 200:
            raise AuthFailedError(
                f"token endpoint → HTTP {resp.status_code}；请检查登录状态，未自动重试口令"
            )
        if not _is_json(resp):
            raise AuthFailedError(
                f"token endpoint {url} returned 200 but non-JSON (gateway HTML?) —— treated as auth failure"
            )
        try:
            body = resp.json() or {}
        except ValueError:
            raise AuthFailedError("token endpoint returned invalid JSON") from None
        if not isinstance(body, dict) or not body.get("access_token"):
            raise AuthFailedError("token endpoint returned 200 JSON without access_token")
        return self._token_from_body(body)

    def _token_from_body(self, body: dict, previous: Optional[Token] = None) -> Token:
        return Token(
            access_token=body["access_token"],
            tenant_id=body.get("tenant_id") or (previous.tenant_id if previous else ""),
            tenant_domain=body.get("tenant_domain") or (previous.tenant_domain if previous else self._cred.tenant_domain),
            user_id=body.get("user_id") or (previous.user_id if previous else ""),
            refresh_token=body.get("refresh_token") or (previous.refresh_token if previous else ""),
        )
