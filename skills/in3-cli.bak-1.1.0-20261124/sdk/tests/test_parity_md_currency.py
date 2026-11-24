"""md.currency CLI parity 硬门禁（issue #1 §parity，范围严格限本 entity）。

两层：
1. 静态 fixture（默认快跑）：录制的原始 springfox 信封喂进 SDK 全脊柱（auth mock + http +
   envelope + pagination + entity）→ 归一后业务记录，与录制的 CLI `--all` 输出**逐位比对**。
2. @slow 真实子集：真打后端 + 真跑 `exec md currency list --all` 子进程，同样逐位比对
   （默认不跑，`pytest -m slow` 显式触发）。

**只比业务数字（币种记录字段），不比 total**——真后端实锤 CLI total 字段不可信（默认页 total:0
而 items 有 20+），SDK 聚合后 total 置 None，比 total 会假性不一致。按 id 建索引逐位比对全字段。
"""
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from in3_client.auth import Session
from in3_client.config import Credentials
from in3_client.entities.md import CurrencyEntity
from in3_client.http import HttpClient

_FIXTURES = Path(__file__).parent / "fixtures"
_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"

_CRED = Credentials(
    api_host="https://apiv3.industics.com/service",
    tenant_domain="indx",
    username="corp:zhuzheng@indx",
    encrypted_password="AESCIPHER==",
    alias="zhuzheng",
)
_TOKEN = {"access_token": "jwt", "tenant_id": "10030", "tenant_domain": "indx", "user_id": "u-42"}


@dataclass
class _FakeResponse:
    status_code: int
    _json: object = None
    content_type: str = "application/json"
    text: str = ""

    @property
    def headers(self):
        return {"content-type": self.content_type}

    def json(self):
        return self._json


@dataclass
class _FakeTransport:
    responses: list
    calls: list = field(default_factory=list)

    def __call__(self, method, url, headers=None, params=None, **kw):
        self.calls.append({"method": method, "url": url, "params": params})
        return self.responses.pop(0)


def _index_by_id(items):
    return {it["id"]: it for it in items}


def _assert_business_parity(sdk_items, cli_items):
    """按 id 逐位比对全部业务字段；key 集 + 每条记录都必须相等（不比 total）。"""
    si, ci = _index_by_id(sdk_items), _index_by_id(cli_items)
    assert set(si) == set(ci), f"id 集不一致: SDK-only={set(si)-set(ci)}, CLI-only={set(ci)-set(si)}"
    mismatches = {k: {f: (si[k].get(f), ci[k].get(f))
                      for f in set(si[k]) | set(ci[k]) if si[k].get(f) != ci[k].get(f)}
                  for k in si if si[k] != ci[k]}
    assert not mismatches, f"记录级字段不一致: {mismatches}"


def test_parity_static_fixture():
    raw = json.loads((_FIXTURES / "md_currency_raw_page.json").read_text())
    cli = json.loads((_FIXTURES / "md_currency_cli_all.json").read_text())

    sess = Session(_CRED, transport=_FakeTransport([_FakeResponse(200, _TOKEN)]))
    http = HttpClient(sess, transport=_FakeTransport([_FakeResponse(200, raw)]))
    sdk_items = CurrencyEntity(_CRED, sess, http).list(size=500).items

    assert len(sdk_items) == len(cli["items"]) > 0
    _assert_business_parity(sdk_items, cli["items"])


@pytest.mark.slow
def test_parity_live_against_real_backend():
    import in3_client  # noqa: PLC0415

    sdk_items = in3_client.IN3(tenant="zhuzheng").md.currency.list().items

    proc = subprocess.run(
        [sys.executable, "in3_cli.py", "exec", "md", "currency", "list", "--all"],
        cwd=str(_SCRIPTS), capture_output=True, text=True, check=True,
    )
    cli_items = json.loads(proc.stdout)["items"]

    assert len(sdk_items) == len(cli_items) > 0
    _assert_business_parity(sdk_items, cli_items)
