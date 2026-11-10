"""#13 M2 fn 模块 bare-array 实体单测（直接实例化，不经 facade）。

覆盖 company_code（裸 List 包 Page，有 get；自身不发 fncc header，是 cc 定义源）/
posting_period（裸 List /posting-periods/all，仅 list 无 get；字段名 posting_period_name
**非** period_name；状态在嵌套 valuation_region_posting_periods[].{enabled,closed,current}）。

fn company_code / posting_period 都是 tenant-templated（/v2/api/tenants/<tid>/）—— 与 cr 不同。
裸 List 走 #10 的 _list_bare/coerce_to_page，不经 normalize、不被 or {} 吞空。
"""
from dataclasses import dataclass, field

import pytest

from in3_client.auth import Session
from in3_client.config import Credentials
from in3_client.envelope import Page
from in3_client.http import HttpClient, HttpError
from in3_client.entities.fn import CompanyCodeEntity, PostingPeriodEntity


@dataclass
class FakeResponse:
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
class FakeTransport:
    responses: list
    calls: list = field(default_factory=list)

    def __call__(self, method, url, headers=None, params=None, **kw):
        self.calls.append({"method": method, "url": url, "params": params, "json": kw.get("json")})
        return self.responses.pop(0)


_CRED = Credentials(
    api_host="https://apiv3.industics.com/service",
    tenant_domain="indx",
    username="corp:zhuzheng@indx",
    encrypted_password="AESCIPHER==",
    alias="zhuzheng",
)
_TOKEN = {"access_token": "jwt", "tenant_id": "10030", "tenant_domain": "indx", "user_id": "u-42"}

_FN_BASE = "https://apiv3.industics.com/service/mom/fn"


def _wire(entity_cls, data_responses, **kw):
    sess = Session(_CRED, transport=FakeTransport([FakeResponse(200, _TOKEN)]))
    data_tr = FakeTransport(data_responses)
    http = HttpClient(sess, transport=data_tr)
    return entity_cls(_CRED, sess, http, **kw), data_tr


# ---------- fn.company_code ----------

def test_company_code_list_wraps_bare_list():
    ent, tr = _wire(CompanyCodeEntity, [
        FakeResponse(200, [
            {"id": "cc1", "company_code": "1000", "taxpayer_identification": "91XXXX"},
            {"id": "cc2", "company_code": "2000"},
        ]),
    ])
    page = ent.list()
    assert isinstance(page, Page)
    assert page.items[0]["company_code"] == "1000"
    assert page.total == 2
    assert page.has_next is False
    assert tr.calls[0]["method"] == "GET"


def test_company_code_list_tenant_templated_url():
    ent, tr = _wire(CompanyCodeEntity, [FakeResponse(200, [])])
    ent.list()
    # parity 2026-06-03 校正：实端点 /company-codes/list（无 apar/ 前缀），与 CLI `fn company-code list` 对齐。
    assert tr.calls[0]["url"] == _FN_BASE + "/v2/api/tenants/10030/company-codes/list"


def test_company_code_get_single_record():
    ent, tr = _wire(CompanyCodeEntity, [FakeResponse(200, {"id": "cc1", "company_code": "1000"})])
    rec = ent.get("cc1")
    assert rec["company_code"] == "1000"
    # parity 2026-06-03 校正：get 实端点 /company-codes/{id}（无 apar/ 前缀）。
    assert tr.calls[0]["url"] == _FN_BASE + "/v2/api/tenants/10030/company-codes/cc1"


def test_company_code_list_passes_filter():
    ent, tr = _wire(CompanyCodeEntity, [FakeResponse(200, [])])
    ent.list(filter={"company_code": "1000"})
    assert tr.calls[0]["params"]["company_code"] == "1000"


def test_company_code_get_404_raises():
    # id 不存在 → 按 M0 404 语义 raise HttpError（不静默返 {}）。
    ent, _ = _wire(CompanyCodeEntity, [FakeResponse(404, text="not found")])
    with pytest.raises(HttpError):
        ent.get("nope")


# ---------- fn.posting_period（list-only） ----------

def test_posting_period_list_wraps_bare_list():
    ent, tr = _wire(PostingPeriodEntity, [
        FakeResponse(200, [
            {
                "id": "pp1",
                "posting_period_name": "2026-01",
                "valuation_region_posting_periods": [
                    {"enabled": True, "closed": False, "current": True},
                ],
            },
        ]),
    ])
    page = ent.list()
    assert isinstance(page, Page)
    it = page.items[0]
    # 字段名回归：posting_period_name（非 period_name）。
    assert it["posting_period_name"] == "2026-01"
    assert "period_name" not in it
    # 状态在嵌套数组而非顶层 status。
    assert it["valuation_region_posting_periods"][0]["enabled"] is True
    assert it["valuation_region_posting_periods"][0]["closed"] is False
    assert it["valuation_region_posting_periods"][0]["current"] is True
    assert page.total == 1


def test_posting_period_list_endpoint_is_all():
    ent, tr = _wire(PostingPeriodEntity, [FakeResponse(200, [])])
    ent.list()
    assert tr.calls[0]["url"].endswith("/posting-periods/all")
    assert tr.calls[0]["method"] == "GET"


def test_posting_period_has_no_get():
    # 仅 list、无 get（裸 List /posting-periods/all，忠实不暴露 .get）。
    ent, _ = _wire(PostingPeriodEntity, [])
    assert not hasattr(ent, "get")


def test_posting_period_list_passes_valuation_region_id_query():
    # §6 行 761-762：posting_period.list 吃 valuation_region_id filter → 透传进 query（int 不强转）。
    ent, tr = _wire(PostingPeriodEntity, [FakeResponse(200, [])])
    ent.list(valuation_region_id=7)
    assert tr.calls[0]["params"]["valuation_region_id"] == 7
    assert isinstance(tr.calls[0]["params"]["valuation_region_id"], int)


def test_posting_period_list_no_valuation_region_id_omits_query():
    # 不传 valuation_region_id → query 不含该键（默认 None 不注入）。
    ent, tr = _wire(PostingPeriodEntity, [FakeResponse(200, [])])
    ent.list()
    assert "valuation_region_id" not in (tr.calls[0]["params"] or {})


def test_posting_period_list_filter_dict_passthrough():
    # filter dict 也透传进 query（裸 List base_params 即 query）。
    ent, tr = _wire(PostingPeriodEntity, [FakeResponse(200, [])])
    ent.list(filter={"valuation_region_id": 3})
    assert tr.calls[0]["params"]["valuation_region_id"] == 3


# ---------- 只读边界守护 ----------

@pytest.mark.parametrize("cls", [CompanyCodeEntity, PostingPeriodEntity])
def test_fn_entities_no_write_methods(cls):
    ent, _ = _wire(cls, [])
    for w in ("create", "update", "delete", "post_write", "save", "remove"):
        assert not hasattr(ent, w)
