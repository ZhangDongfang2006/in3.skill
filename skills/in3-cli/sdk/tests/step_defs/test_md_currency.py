"""md.currency 端到端 + CLI parity 的 BDD step defs（第一颗 tracer bullet，issue #1）。

绑定 features/in3-client-md-currency.feature → IN3().md.currency.list()（注入 FakeTransport
喂录制后端信封）。RTM #8（import 直跑）/ #1（脊柱端到端 + 不做币种归一）/ #31（CLI parity 逐位）。
parity 用录制 fixture md_currency_cli_all.json 作 CLI 基准，不真跑 CLI 子进程。
"""
from pytest_bdd import scenarios, given, when, then

from in3_client.envelope import Page
from ._support import FakeResponse, make_in3

scenarios("../../features/in3-client-md-currency.feature")


def _run_currency_list(raw):
    """注入录制后端信封，跑 in3.md.currency.list()，返回 (page, data_tr, auth_tr)。"""
    in3, data_tr, auth_tr = make_in3([
        FakeResponse(200, raw),
        FakeResponse(200, {"content": [], "last": True}),  # 兜底末页，保证翻页终止
    ])
    return in3.md.currency.list(), data_tr, auth_tr


# ---------- 背景 ----------

@given("一个已登录租户的 workspace（credentials.json 就位）", target_fixture="bdd_context")
def _bg_ws():
    return {}


@given("md currency 端点的录制 fixture 已就位")
def _bg_recorded(bdd_context, recorded_backend):
    bdd_context["raw"] = recorded_backend["currency_raw_page"]
    bdd_context["cli"] = recorded_backend["currency_cli"]


# ---------- RTM #8：import 直跑 ----------

@when("一段 Python 在 import in3_client 后调用 in3.md.currency.list()")
def _w_import_call(bdd_context):
    page, data_tr, auth_tr = _run_currency_list(bdd_context["raw"])
    bdd_context.update(page=page, data_tr=data_tr, auth_tr=auth_tr)


@then("它无需经 run 壳即可返回一个 Page")
def _t_returns_page(bdd_context):
    # 直接 import 调用（无 subprocess/run 壳）即得 Page。
    assert isinstance(bdd_context["page"], Page)


@then("该 Page 的 items 为归一后的币种记录")
def _t_items_normalized(bdd_context):
    items = bdd_context["page"].items
    cli_items = bdd_context["cli"]["items"]
    assert len(items) > 0
    # 与独立 CLI 基准逐位一致（非比自己喂进去的 raw 输入）—— 归一结果与 CLI 等价。
    assert items == cli_items[: len(items)]


# ---------- RTM #1：脊柱端到端 ----------

@when("in3.md.currency.list() 执行")
def _w_spine(bdd_context):
    page, data_tr, auth_tr = _run_currency_list(bdd_context["raw"])
    bdd_context.update(page=page, data_tr=data_tr, auth_tr=auth_tr)


@then("它依次走 config 读凭证、auth 换 token、GET /mdm/currencies/page、envelope 归一、pagination")
def _t_spine_path(bdd_context):
    assert len(bdd_context["auth_tr"].calls) >= 1                  # auth 换了 token
    assert bdd_context["data_tr"].calls[0]["url"].endswith("/mdm/currencies/page")
    assert isinstance(bdd_context["page"], Page)                   # envelope/pagination 产出 Page


@then("返回统一的 Page{items, page, total, has_next}")
def _t_uniform_page(bdd_context):
    p = bdd_context["page"]
    for attr in ("items", "page", "total", "has_next"):
        assert hasattr(p, attr)


# ---------- RTM #31：CLI parity 逐位 ----------

@given("同一 currency 查询分别走 SDK 路径与现有 CLI 路径")
def _g_two_paths(bdd_context):
    sdk_page, _, _ = _run_currency_list(bdd_context["raw"])
    bdd_context["sdk_items"] = sdk_page.items
    bdd_context["cli_items"] = bdd_context["cli"]["items"]


@when("比对两条路径的产出")
def _w_compare(bdd_context):
    bdd_context["diff"] = [
        (i, s, c) for i, (s, c) in enumerate(zip(bdd_context["sdk_items"], bdd_context["cli_items"]))
        if s != c
    ]


@then("业务数字（含币种码字段）逐位一致")
def _t_parity_equal(bdd_context):
    n = len(bdd_context["sdk_items"])
    assert n > 0
    # SDK 取出的这批记录与 CLI 输出对应记录逐位一致（含 currency_code / iso_currency_no）。
    assert bdd_context["sdk_items"] == bdd_context["cli_items"][:n]


@then("任一位不一致即判 parity FAIL（一票否决）")
def _t_parity_veto(bdd_context):
    assert bdd_context["diff"] == []  # 有任一位不一致则非空 → 该断言会 fail（一票否决语义）


# ---------- RTM #1：md.currency 不做 156↔CNY 归一 ----------

@when("in3.md.currency.list() 返回币种记录")
def _w_list_records(bdd_context):
    page, _, _ = _run_currency_list(bdd_context["raw"])
    bdd_context["items"] = page.items


@then("币种码原样穿过")
def _t_codes_passthrough(bdd_context):
    items = bdd_context["items"]
    cli_items = bdd_context["cli"]["items"]
    # 币种码与 CLI 基准逐位一致、未被改写（156 不变成 CNY）。
    assert items == cli_items[: len(items)]


@then("156↔CNY 表示归一留待 issue #7 的 normalize_currency")
def _t_no_currency_normalize(bdd_context):
    # md.currency 不旁挂 normalize_currency 的字母 companion（那是 sd/#7 的事）。
    for rec, raw in zip(bdd_context["items"], bdd_context["raw"]["content"]):
        assert rec.keys() == raw.keys()  # 无新增归一字段
