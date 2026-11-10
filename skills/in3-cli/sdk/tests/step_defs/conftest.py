"""in3_client SDK BDD —— 共享 fixture（pytest-bdd 8 + zh-CN i18n，同步栈）。

step defs 已填实（2026-06-03）：envelope / auth / md_currency 全绿；poc 离线 2 绿 + 5 skip
（parity 逐位 / token 降幅 / doctor BARS / M4 裁决需 zhuzheng 凭证或 HITL，离线不可跑）。
FakeTransport 桩 + IN3 构造照 tests/test_*.py prior art，集中在 _support.py。
"""
import pytest

from ._support import TOKEN, load_fixture


@pytest.fixture
def bdd_context() -> dict:
    """场景内传递状态（raw 响应 / 归一后的 Page / 路径产出 / 异常等）。"""
    return {}


@pytest.fixture
def mock_uaas_token() -> dict:
    """mock /uaas/oauth/token 的 token 响应体（access_token / tenant_domain / user_id）。"""
    return dict(TOKEN)


@pytest.fixture
def recorded_backend() -> dict:
    """features 用例的录制后端响应：md.currency 单页原始信封 + CLI all 输出（parity 基准）。"""
    return {
        "currency_raw_page": load_fixture("md_currency_raw_page.json"),
        "currency_cli": load_fixture("md_currency_cli_all.json"),
    }


@pytest.fixture
def cli_runner():
    """parity 基准：返回录制的 CLI 输出（逐位比对用），不真跑 CLI 子进程。"""
    recorded = {"md.currency": load_fixture("md_currency_cli_all.json")}
    return lambda entity: recorded[entity]
