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

from dataclasses import dataclass
from typing import Callable, Optional

from ._transport import default_transport
from .config import Credentials

# 8 模块共用的 SPA OAuth 客户端（与 ibrain-mm/cli src/config/env.ts 同源），可由调用方覆盖。
DEFAULT_CLIENT_ID = "8b80bf13ab4611ea8356000c29ba7340"
DEFAULT_CLIENT_SECRET = "d6223c6102ec47dcb8a9797619dde758"


class AuthFailedError(Exception):
    """换 token 失败（含网关 200-非-JSON、缺 access_token）—— fail-loud，绝不返回空结果。"""


@dataclass
class Token:
    access_token: str
    tenant_id: str
    tenant_domain: str
    user_id: str
    refresh_token: str = ""


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
        grant_mode: str = "password",
    ):
        self._cred = cred
        self._transport = transport or default_transport()
        self._client_id = client_id
        self._client_secret = client_secret
        # "password"（SPA 共用 client + AES 口令）或 "client_credentials"（AGENT 机器令牌，
        # client_id/client_secret 即 AGENT 凭证、无 username/password）。后者 token 响应无 user_id/
        # tenant_domain → _token_from_body 回退 cred.tenant_domain 当 T-CODE（须为租户域名如 "indx"）。
        self._grant_mode = grant_mode
        self._token: Optional[Token] = None

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
        s = cls(cred, transport=transport, client_id=client_id, client_secret=client_secret)
        s._token = Token(
            access_token=access_token,
            tenant_id=tenant_id,
            tenant_domain=tenant_domain or cred.tenant_domain,
            user_id=user_id,
            refresh_token=refresh_token,
        )
        return s

    def token(self) -> Token:
        if self._token is None:
            self._token = self._fetch_token()
        return self._token

    def clear(self) -> None:
        self._token = None

    def refresh(self) -> bool:
        """用 refresh_token 静默换新 access_token（后端实测支持 grant_type=refresh_token、会轮换）。

        成功 → 更新缓存 token、返回 True；无 refresh_token / 刷新失败（4xx / 非 JSON / 缺 access）
        → 返回 False（不抛，调用方据此回退到重新换 token）。
        """
        if self._token is None or not self._token.refresh_token:
            return False
        url = self._cred.uaas_host.rstrip("/") + "/uaas/oauth/token"
        params = {
            "grant_type": "refresh_token",
            "refresh_token": self._token.refresh_token,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        resp = self._transport("GET", url, params=params)
        if resp.status_code != 200 or not _is_json(resp):
            return False
        body = resp.json() or {}
        if not body.get("access_token"):
            return False
        self._token = self._token_from_body(body)
        return True

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
        url = self._cred.uaas_host.rstrip("/") + "/uaas/oauth/token"
        if self._grant_mode == "client_credentials":
            # AGENT 机器令牌：无 username/password，client_id/secret 即 AGENT 凭证。
            params = {
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            }
        else:
            params = {
                "grant_type": "password",
                "username": self._cred.username,
                "password": self._cred.encrypted_password,  # 直发 AES 串，不解密
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            }
        resp = self._transport("GET", url, params=params)
        if resp.status_code != 200:
            raise AuthFailedError(
                f"token endpoint {url} → HTTP {resp.status_code}: {getattr(resp, 'text', '')[:200]}"
            )
        if not _is_json(resp):
            raise AuthFailedError(
                f"token endpoint {url} returned 200 but non-JSON (gateway HTML?) —— treated as auth failure"
            )
        body = resp.json() or {}
        if not body.get("access_token"):
            raise AuthFailedError(f"token endpoint {url} returned 200 JSON without access_token: {body!r}")
        return self._token_from_body(body)

    def _token_from_body(self, body: dict) -> Token:
        return Token(
            access_token=body["access_token"],
            tenant_id=body.get("tenant_id", ""),
            tenant_domain=body.get("tenant_domain", self._cred.tenant_domain),
            user_id=body.get("user_id", ""),
            refresh_token=body.get("refresh_token", ""),
        )
