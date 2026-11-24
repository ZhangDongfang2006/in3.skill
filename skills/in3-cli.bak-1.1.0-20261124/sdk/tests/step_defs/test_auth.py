"""auth（password-grant 兜底路）的 BDD step defs。绑定 features/in3-client-auth.feature。

RTM #21（AES 串直发不解密 / 缺凭证 fail-loud）/ #22（三鉴权头）/ #23（401 重试一次 /
200 非 JSON 判认证失败）。全程 FakeTransport 桩，不碰真后端。
"""
from pathlib import Path

import pytest
from pytest_bdd import scenarios, given, when, then

from in3_client.auth import AuthFailedError, Session
from in3_client.config import Credentials, MissingCredentialsError, load_credentials
from in3_client.http import HttpError
from ._support import CRED, TOKEN, FakeResponse, FakeTransport, make_http

scenarios("../../features/in3-client-auth.feature")

_SDK_DIR = Path(__file__).resolve().parents[2] / "in3_client"
_DATA_URL = CRED.base_url("md") + "/v2/api/tenants/10030/mdm/currencies/page"


# ---------- 背景（Background） ----------

@given("一个已登录租户的 credentials.json 存有 api_host、tenant_domain、username、user_id 和一段 AES 加密口令串",
       target_fixture="bdd_context")
def _bg_cred():
    return {"cred": CRED}  # CRED.encrypted_password = "AESCIPHER=="（AES 串）


@given("UAAS token 端点 /uaas/oauth/token 已被 mock")
def _bg_token_mocked(bdd_context):
    bdd_context["token_mocked"] = True


# ---------- RTM #21：password-grant 直发 AES 串 ----------

@when("SDK 取 token")
def _w_get_token(bdd_context):
    tr = FakeTransport([FakeResponse(200, dict(TOKEN))])
    Session(CRED, transport=tr).token()
    bdd_context["token_call"] = tr.calls[0]


@then("它向 /uaas/oauth/token 发 grant_type=password 请求")
def _t_grant_password(bdd_context):
    call = bdd_context["token_call"]
    assert call["method"] == "GET"
    assert call["url"].endswith("/uaas/oauth/token")
    assert call["params"]["grant_type"] == "password"


@then("请求的 password 字段等于 credentials.json 里那段 AES 串（逐字一致、未解密）")
def _t_password_verbatim(bdd_context):
    assert bdd_context["token_call"]["params"]["password"] == "AESCIPHER=="


@then("SDK 代码中不存在任何 AES 解密逻辑")
def _t_no_aes_decrypt():
    # 扫 in3_client 全包：不出现任何解密/AES-Cipher 调用（SDK 只直发密文，不解密）。
    blob = "\n".join(p.read_text() for p in _SDK_DIR.rglob("*.py")).lower()
    for forbidden in ("decrypt", "aes.new", "cipher", "from crypto", "import crypto"):
        assert forbidden not in blob, f"SDK 不应含解密逻辑，但出现 {forbidden!r}"


# ---------- RTM #22：三鉴权头 ----------

@given("已拿到 access_token、tenant_domain 与 user_id")
def _g_have_token(bdd_context):
    # 用辨识度高、SDK 不可能硬编码的值 → 三头断言比这些值即证明是从 token 动态读出的。
    tok = {"access_token": "ACCESS-9f3a", "tenant_id": "10030",
           "tenant_domain": "TD-7k2", "user_id": "OP-42x"}
    bdd_context["token"] = tok
    bdd_context["token_responses"] = [FakeResponse(200, tok)]


@when("SDK 发起任意数据请求")
def _w_data_request(bdd_context):
    http, data_tr, _ = make_http([FakeResponse(200, {"content": [], "last": True})],
                                 token_responses=bdd_context.get("token_responses"))
    http.get_json(_DATA_URL)
    bdd_context["headers"] = data_tr.calls[0]["headers"]


@then('请求头 Authorization 等于 "Bearer <access_token>"')
def _t_authorization(bdd_context):
    assert bdd_context["headers"]["Authorization"] == "Bearer " + bdd_context["token"]["access_token"]


@then("请求头 T-CODE 等于 tenant_domain")
def _t_tcode(bdd_context):
    assert bdd_context["headers"]["T-CODE"] == bdd_context["token"]["tenant_domain"]


@then("请求头 X-Operator-ID 等于 user_id")
def _t_operator(bdd_context):
    assert bdd_context["headers"]["X-Operator-ID"] == bdd_context["token"]["user_id"]


# ---------- RTM #23：401 重试一次 / 200 非 JSON ----------

@given("第一次数据请求返回 401")
def _g_first_401(bdd_context):
    # 401 → refresh(无 refresh_token→False)→clear+重换 token→重试 → 200。需 2 个 token 响应。
    bdd_context["data_responses"] = [FakeResponse(401, text="unauthorized"),
                                     FakeResponse(200, {"content": [], "last": True})]
    bdd_context["token_responses"] = [FakeResponse(200, dict(TOKEN)), FakeResponse(200, dict(TOKEN))]


@given("网关对数据请求返回 HTTP 200 且 content-type 不是 JSON（HTML 重定向页）")
def _g_non_json_200(bdd_context):
    bdd_context["data_responses"] = [FakeResponse(200, content_type="text/html", text="<html>login</html>")]
    bdd_context["token_responses"] = [FakeResponse(200, dict(TOKEN))]


@when("SDK 处理该响应")
def _w_handle_response(bdd_context):
    http, data_tr, _ = make_http(bdd_context["data_responses"],
                                 token_responses=bdd_context.get("token_responses"))
    bdd_context["data_tr"] = data_tr
    try:
        bdd_context["result"] = http.get_json(_DATA_URL)
        bdd_context["error"] = None
    except Exception as e:  # noqa: BLE001 —— 捕获供 then 断言类型
        bdd_context["error"] = e


@then("它清除当前 token、重新换 token 并仅重试一次")
def _t_retry_once(bdd_context):
    # 一次 401 + 一次重试 = 恰好 2 次数据请求（仅重试一次，不无限重试）。
    assert len(bdd_context["data_tr"].calls) == 2
    assert bdd_context["error"] is None  # 重试后 200 成功


@then("若重试仍 401 则抛认证错误（不静默吞）")
def _t_still_401_raises():
    # 独立验证：重试仍 401 → 抛 HttpError（不静默返回空）。
    http, _, _ = make_http([FakeResponse(401), FakeResponse(401)],
                           token_responses=[FakeResponse(200, dict(TOKEN)), FakeResponse(200, dict(TOKEN))])
    with pytest.raises(HttpError):
        http.get_json(_DATA_URL)


@then("它判定为认证失败并抛错")
def _t_auth_failure(bdd_context):
    assert isinstance(bdd_context["error"], AuthFailedError)


@then("绝不把 HTML 当作空结果或 0 行返回")
def _t_not_empty(bdd_context):
    # 抛错而非返回空 dict/[]——agent 不会被 HTML 骗成「0 行」。
    assert bdd_context["error"] is not None
    assert bdd_context.get("result") is None


# ---------- RTM #21：缺凭证 fail-loud ----------

@given("credentials.json 缺失或关键字段缺失")
def _g_missing_cred(bdd_context, tmp_path):
    bdd_context["bogus_ws"] = tmp_path / "no-such-workspace"  # 不存在 → load 必抛


@when("SDK 构造 Session")
def _w_construct_session(bdd_context):
    try:
        load_credentials(workspace=bdd_context["bogus_ws"], alias="zhuzheng")
        bdd_context["error"] = None
        bdd_context["session"] = Session(CRED)  # 不该走到
    except Exception as e:  # noqa: BLE001
        bdd_context["error"] = e
        bdd_context["session"] = None


@then("它抛出明确错误")
def _t_raises_clear(bdd_context):
    assert isinstance(bdd_context["error"], MissingCredentialsError)


@then("不返回空 Session、不静默继续")
def _t_no_silent_session(bdd_context):
    assert bdd_context["error"] is not None
    assert bdd_context["session"] is None
