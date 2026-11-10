"""login token 路径单测：_token_response_fields 提取 + _decode_jwt_claims。"""
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import in3_cli  # noqa: E402


def _fake_jwt(claims: dict) -> str:
    def seg(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{seg({'alg': 'RS256'})}.{seg(claims)}.sig"


def test_decode_jwt_claims():
    tok = _fake_jwt({"sub": "corp:u@indx", "tenant_domain": "indx", "exp": 123})
    c = in3_cli._decode_jwt_claims(tok)
    assert c["sub"] == "corp:u@indx" and c["tenant_domain"] == "indx" and c["exp"] == 123


def test_decode_jwt_bad_raises():
    import pytest
    with pytest.raises(ValueError):
        in3_cli._decode_jwt_claims("not-a-jwt")


def test_token_response_fields_from_full_response():
    # 模拟 /uaas/oauth/token 响应（password grant 形状）
    tok = _fake_jwt({"sub": "corp:zhuzheng@indx", "tenant_domain": "indx", "exp": 1780437460})
    body = {
        "access_token": tok, "refresh_token": "RT",
        "sub": "corp:zhuzheng@indx", "tenant_domain": "indx",
        "tenant_id": "99979", "user_id": "u-9", "fullname": "朱政",
    }
    f = in3_cli._token_response_fields(body)
    assert f["token"] == tok
    assert f["refresh_token"] == "RT"
    assert f["username"] == "corp:zhuzheng@indx"
    assert f["tenant_domain"] == "indx"
    assert f["tenant_id"] == "99979"
    assert f["user_id"] == "u-9"
    assert f["fullname"] == "朱政"


def test_token_response_fields_falls_back_to_jwt():
    # 响应只有 access_token，其余字段从 JWT 补
    tok = _fake_jwt({"sub": "corp:a@indx", "tenant_domain": "indx", "tenant_id": "99979",
                     "user_id": "u-x", "exp": 999, "fullname": "甲"})
    f = in3_cli._token_response_fields({"access_token": tok})
    assert f["username"] == "corp:a@indx"
    assert f["tenant_domain"] == "indx"
    assert f["tenant_id"] == "99979"
    assert f["user_id"] == "u-x"
    assert f["exp"] == 999
