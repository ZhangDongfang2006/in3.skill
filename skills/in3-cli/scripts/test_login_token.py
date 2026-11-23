"""login token 路径单测：_token_response_fields 提取 + _decode_jwt_claims。"""
import base64
import json
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

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


def _login_fields():
    return {"token": "fixture-AT", "refresh_token": "fixture-RT", "tenant_domain": "indx",
            "tenant_id": "99979", "username": "corp:u@indx", "user_id": "u9"}


def test_token_login_validates_before_replacing_credentials(tmp_path, monkeypatch, capsys):
    old = {"auth_mode": "password", "encrypted_password": "OLD-AES"}
    in3_cli.save_master_cred(old, tmp_path, "indx")

    def reject(*args):
        raise ValueError("服务端拒绝 token")

    monkeypatch.setattr(in3_cli, "validate_token", reject, raising=False)
    args = SimpleNamespace(alias="indx", force=True)
    assert in3_cli._write_token_login(tmp_path, args, _login_fields()) != 0
    assert in3_cli.load_master_cred(tmp_path, "indx") == old
    assert not (tmp_path / "config/current-tenant.json").exists()
    assert "登录成功" not in capsys.readouterr().out


@pytest.mark.parametrize("refresh", ["fixture-RT", ""])
def test_validated_login_reports_renewal_and_exec_scope(tmp_path, monkeypatch, capsys, refresh):
    calls = []
    monkeypatch.setattr(in3_cli, "validate_token", lambda *args: calls.append(args), raising=False)
    fields = dict(_login_fields(), refresh_token=refresh)
    assert in3_cli._write_token_login(tmp_path, SimpleNamespace(alias="indx"), fields) == 0
    assert len(calls) == 1
    assert in3_cli.load_master_cred(tmp_path, "indx")["refresh_token"] == refresh
    out = capsys.readouterr().out
    assert "exec sf" in out and "exec" in out
    assert ("自动续期" if refresh else "无法自动续期") in out


def test_expired_token_is_rejected_before_network_request(monkeypatch):
    from in3_token_login import validate_token

    def no_network(*args, **kwargs):
        pytest.fail("过期 token 不应发校验请求")

    monkeypatch.setattr("urllib.request.build_opener", no_network)
    with pytest.raises(ValueError, match="已过期"):
        validate_token("https://h", dict(_login_fields(), exp=1))
