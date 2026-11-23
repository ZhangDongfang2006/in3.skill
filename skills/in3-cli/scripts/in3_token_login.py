"""token 登录前的轻量只读校验；不尝试续期或口令授权，不输出响应正文。"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # 不向跳转目标转发 Bearer。


def validate_token(api_host: str, fields: dict) -> None:
    """只取一条币种验证服务端接受该 token；失败时禁止覆盖现有凭证。"""
    if not fields.get("tenant_id") or not fields.get("user_id"):
        raise ValueError("token 缺 tenant_id/user_id，无法验证当前用户")
    exp = fields.get("exp")
    if isinstance(exp, (int, float)) and exp <= time.time():
        raise ValueError("token 已过期，请在浏览器重新登录后获取")
    tenant = urllib.parse.quote(str(fields["tenant_id"]), safe="")
    url = f"{api_host.rstrip('/')}/mom/md/v2/api/tenants/{tenant}/mdm/currencies/page?page=0&size=1"
    values = (fields["token"], fields["tenant_domain"], fields["user_id"])
    if any("\n" in str(value) or "\r" in str(value) for value in values):
        raise ValueError("token 身份字段包含非法换行，现有凭证未修改")
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {fields['token']}",
        "T-CODE": str(fields["tenant_domain"]),
        "X-Operator-ID": str(fields["user_id"]),
        "Accept": "application/json",
    })
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=10) as response:
            if response.status != 200 or "json" not in response.headers.get("Content-Type", "").lower():
                raise ValueError("token 校验未返回有效 JSON，现有凭证未修改")
            body = json.load(response)
            if not isinstance(body, (dict, list)) or (isinstance(body, dict) and body.get("error")):
                raise ValueError("token 校验返回错误，现有凭证未修改")
    except urllib.error.HTTPError as error:
        error.close()
        if error.code == 401:
            raise ValueError("服务端拒绝 token（HTTP 401），请重新登录；现有凭证未修改") from None
        raise ValueError(f"无法校验 token（HTTP {error.code}，需要币种读取权限）；现有凭证未修改") from None
    except (OSError, json.JSONDecodeError):
        raise ValueError("token 校验连接或响应异常，现有凭证未修改，请稍后重试") from None
