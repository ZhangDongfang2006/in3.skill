"""mm M3 业务单据单测（issue #14 §6：contract / purchase_requirement / source_list / ecn / quotation）。

直接实例化 entity（FakeTransport，不经 facade）。逐实体钉死本片坑层：
- contract（simple-list-get）：list /spm/contracts/pages；get online→offline 404 fallback +
  旁挂 _contract_type='online'/'offline'；两路都 404 才 fail-loud；category 单值、supplier_id/status multi；
  date filter；header-only（不造行项）；只读边界。
- purchase_requirement（fanout-gotcha）：list typo path /spm/purchase-requirents/pages（少个 e）；
  get /spm/purchase-requirents/<id>；include_items → bulk-get POST，body 是**裸 prId 数组**（非 {ids:[]}），
  返 detail 自带 items 按 id 挂回 header；multi filter；只读边界。
- source_list（simple-list-get）：list 标准 /spm/source-lists/page；get 走 ?id= query-param
  （/spm/source-lists?id=<id>，非 path 段）；单值 filter；只读边界。
- ecn（simple-list-get）：list /ecn-bom/page（**无 spm 前缀**）；get /ecn-bom/<id>/check（尾缀 /check）；
  from_time/to_time 是 datetime ISO 透传；material_ids multi；只读边界。
- quotation（fanout-gotcha=POST-body 分页）：list POST /spm-rfq/pages（filter 进 body、page/size 进 query，
  PostPagedEntity）；get /spm-rfq/quotation/query/<id>（完全不同子路径）；date+datetime 双套并存只透传；
  supplier_ids/rfq_id integer；只读边界。

桩照 tests/test_mm_m1_m2.py / test_m0_post_paged_bare_coerce.py。
"""
from dataclasses import dataclass, field

import inspect

import pytest

from in3_client.auth import Session
from in3_client.config import Credentials
from in3_client.envelope import Page
from in3_client.http import HttpClient, HttpError
from in3_client.entities.mm import (
    ContractEntity,
    EcnEntity,
    PurchaseRequirementEntity,
    QuotationEntity,
    SourceListEntity,
)


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
        self.calls.append(
            {"method": method, "url": url, "params": params, "json": kw.get("json")}
        )
        return self.responses.pop(0)


_CRED = Credentials(
    api_host="https://apiv3.industics.com/service",
    tenant_domain="indx",
    username="corp:zhuzheng@indx",
    encrypted_password="AESCIPHER==",
    alias="zhuzheng",
)
_TOKEN = {"access_token": "jwt", "tenant_id": "10030", "tenant_domain": "indx", "user_id": "u-42"}

_MM_BASE = "https://apiv3.industics.com/service/mom/mm/v2/api/tenants/10030"

_WRITE_METHODS = ("create", "update", "delete", "save", "remove", "post_write")


def _wire(entity_cls, data_responses):
    sess = Session(_CRED, transport=FakeTransport([FakeResponse(200, _TOKEN)]))
    data_tr = FakeTransport(data_responses)
    http = HttpClient(sess, transport=data_tr)
    return entity_cls(_CRED, sess, http), data_tr


# ====================== mm.contract (simple-list-get + online/offline 404 fallback) ======================

def test_contract_list_url_is_contracts_pages():
    ent, tr = _wire(ContractEntity, [FakeResponse(200, {"content": [{"id": "c1"}], "last": True})])
    page = ent.list()
    assert isinstance(page, Page)
    assert page.items == [{"id": "c1"}]
    assert tr.calls[0]["url"] == _MM_BASE + "/spm/contracts/pages"


def test_contract_list_category_single_value_supplier_status_multi():
    ent, tr = _wire(ContractEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(filter={
        "category": "ONLINE",                 # 单值字符串
        "supplier_id": ["S-1", "S-2"],        # multi
        "status": [10, 20],                   # multi
        "from_created_date": "2026-01-01",    # date
    })
    p = tr.calls[0]["params"]
    assert p["category"] == "ONLINE"
    assert p["supplier_id"] == ["S-1", "S-2"]   # list 透传（repeated query）
    assert p["status"] == [10, 20]
    assert p["from_created_date"] == "2026-01-01"


def test_contract_unknown_filter_key_raises():
    ent, _ = _wire(ContractEntity, [FakeResponse(200, {"content": [], "last": True})])
    with pytest.raises(ValueError):
        ent.list(filter={"bogus": 1})


def test_contract_get_online_hit_annotates_online_type():
    # 第一路 online 命中（200）→ 不打 offline；旁挂 _contract_type='online'
    ent, tr = _wire(ContractEntity, [FakeResponse(200, {"id": "c1", "contract_no": "ON-1"})])
    rec = ent.get("c1")
    assert rec["contract_no"] == "ON-1"
    assert rec["_contract_type"] == "online"
    assert len(tr.calls) == 1
    assert tr.calls[0]["url"] == _MM_BASE + "/spm/online-contracts/c1"


def test_contract_get_online_404_then_offline_hit():
    # online 404 → 回退打 offline（200）；旁挂 _contract_type='offline'
    ent, tr = _wire(ContractEntity, [
        FakeResponse(404, text="not found"),
        FakeResponse(200, {"id": "c2", "contract_no": "OFF-1"}),
    ])
    rec = ent.get("c2")
    assert rec["contract_no"] == "OFF-1"
    assert rec["_contract_type"] == "offline"
    assert len(tr.calls) == 2
    assert tr.calls[0]["url"] == _MM_BASE + "/spm/online-contracts/c2"
    assert tr.calls[1]["url"] == _MM_BASE + "/spm/offline-contracts/c2"


def test_contract_get_both_404_fail_loud():
    # 两路都 404 → 抛 HttpError（不静默返空）
    ent, tr = _wire(ContractEntity, [
        FakeResponse(404, text="nf"),
        FakeResponse(404, text="nf"),
    ])
    with pytest.raises(HttpError):
        ent.get("ghost")
    assert len(tr.calls) == 2


def test_contract_get_online_non_404_error_does_not_fallback():
    # online 500 → 不是 404，不应回退 offline，直接冒泡（responses 只给一条，回退会 IndexError）
    ent, tr = _wire(ContractEntity, [FakeResponse(500, text="boom")])
    with pytest.raises(HttpError):
        ent.get("c3")
    assert len(tr.calls) == 1  # 没有打 offline


def test_contract_no_write_methods():
    ent, _ = _wire(ContractEntity, [])
    for w in _WRITE_METHODS:
        assert not hasattr(ent, w)


def test_contract_list_has_no_include_items_param():
    # contract 是 header-only（不造行项）→ list 签名钉死无 include_items，防后续误加 fan-out。
    params = inspect.signature(ContractEntity.list).parameters
    assert "include_items" not in params, "contract 是 header-only，不应有 include_items"


# ====================== mm.purchase_requirement (typo path + bare-array bulk-get) ======================

def test_purchase_requirement_list_url_is_typo_path_pages():
    ent, tr = _wire(PurchaseRequirementEntity, [FakeResponse(200, {"content": [{"id": "pr1"}], "last": True})])
    ent.list()
    # 内部 typo path：/spm/purchase-requirents/pages（少个 e）
    assert tr.calls[0]["url"] == _MM_BASE + "/spm/purchase-requirents/pages"


def test_purchase_requirement_get_url_typo_path_single_id():
    ent, tr = _wire(PurchaseRequirementEntity, [FakeResponse(200, {"id": "pr1", "pr_no": "PR-7"})])
    rec = ent.get("pr1")
    assert rec["pr_no"] == "PR-7"
    assert tr.calls[0]["url"] == _MM_BASE + "/spm/purchase-requirents/pr1"


def test_purchase_requirement_list_multi_filters_and_plant():
    ent, tr = _wire(PurchaseRequirementEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(plant="P-1", filter={
        "purchase_type": ["A", "B"],
        "status": [1, 2],
        "approval_statuses": ["WAIT", "DONE"],
        "from_created_date": "2026-01-01",
    })
    p = tr.calls[0]["params"]
    assert p["plant_id"] == "P-1"
    assert p["purchase_type"] == ["A", "B"]
    assert p["status"] == [1, 2]
    assert p["approval_statuses"] == ["WAIT", "DONE"]
    assert p["from_created_date"] == "2026-01-01"


def test_purchase_requirement_unknown_filter_key_raises():
    ent, _ = _wire(PurchaseRequirementEntity, [FakeResponse(200, {"content": [], "last": True})])
    with pytest.raises(ValueError):
        ent.list(filter={"nope": 1})


def test_purchase_requirement_include_items_bulk_get_bare_array_body():
    # list 返 2 个 header；include_items → 一次 bulk-get POST，body 是裸 prId 数组（非 {ids:[]}）。
    list_resp = FakeResponse(200, {"content": [{"id": "pr1"}, {"id": "pr2"}], "last": True})
    # bulk-get 返完整 detail 数组（每个自带 items），按 id 挂回 header
    bulk_resp = FakeResponse(200, [
        {"id": "pr1", "items": [{"line": 1}]},
        {"id": "pr2", "items": [{"line": 2}, {"line": 3}]},
    ])
    ent, tr = _wire(PurchaseRequirementEntity, [list_resp, bulk_resp])
    page = ent.list(include_items=True)
    by_id = {h["id"]: h for h in page.items}
    assert by_id["pr1"]["items"] == [{"line": 1}]
    assert by_id["pr2"]["items"] == [{"line": 2}, {"line": 3}]
    # 第二次调用是 bulk-get
    bulk_call = tr.calls[1]
    assert bulk_call["method"] == "POST"
    assert bulk_call["url"] == _MM_BASE + "/spm/purchase-requirents/bulk-get"
    # body 是裸数组（非 {ids:[..]} / {pr_ids:[..]}）
    assert bulk_call["json"] == ["pr1", "pr2"]


def test_purchase_requirement_include_items_empty_detail_yields_empty_items():
    # 某 header 在 bulk-get 中无对应 detail → items=[]（与 CLI 一致）
    list_resp = FakeResponse(200, {"content": [{"id": "pr1"}, {"id": "pr2"}], "last": True})
    bulk_resp = FakeResponse(200, [{"id": "pr1", "items": [{"line": 1}]}])  # pr2 缺
    ent, _ = _wire(PurchaseRequirementEntity, [list_resp, bulk_resp])
    page = ent.list(include_items=True)
    by_id = {h["id"]: h for h in page.items}
    assert by_id["pr1"]["items"] == [{"line": 1}]
    assert by_id["pr2"]["items"] == []  # 空 detail → []


def test_purchase_requirement_no_include_items_no_bulk_call():
    ent, tr = _wire(PurchaseRequirementEntity, [FakeResponse(200, {"content": [{"id": "pr1"}], "last": True})])
    page = ent.list()
    assert "items" not in page.items[0]
    assert len(tr.calls) == 1  # 没有 bulk-get


def test_purchase_requirement_no_write_methods():
    ent, _ = _wire(PurchaseRequirementEntity, [])
    for w in _WRITE_METHODS:
        assert not hasattr(ent, w)


# ====================== mm.source_list (standard list, query-param get) ======================

def test_source_list_list_url_is_source_lists_page():
    ent, tr = _wire(SourceListEntity, [FakeResponse(200, {"content": [{"id": "sl1"}], "last": True})])
    ent.list()
    assert tr.calls[0]["url"] == _MM_BASE + "/spm/source-lists/page"


def test_source_list_get_url_is_query_param_not_path():
    ent, tr = _wire(SourceListEntity, [FakeResponse(200, {"id": "sl1", "material_id": "M-9"})])
    rec = ent.get("sl1")
    assert rec["material_id"] == "M-9"
    # get 走 ?id= query-param，URL 是 /spm/source-lists（无 /sl1 path 段）
    assert tr.calls[0]["url"] == _MM_BASE + "/spm/source-lists"
    assert tr.calls[0]["params"]["id"] == "sl1"


def test_source_list_list_passes_single_value_filter():
    ent, tr = _wire(SourceListEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(filter={"supplier_id": "S-1", "material_id": "M-2"})
    p = tr.calls[0]["params"]
    assert p["supplier_id"] == "S-1"
    assert p["material_id"] == "M-2"


def test_source_list_unknown_filter_key_raises():
    ent, _ = _wire(SourceListEntity, [FakeResponse(200, {"content": [], "last": True})])
    with pytest.raises(ValueError):
        ent.list(filter={"bad": 1})


def test_source_list_no_write_methods():
    ent, _ = _wire(SourceListEntity, [])
    for w in _WRITE_METHODS:
        assert not hasattr(ent, w)


# ====================== mm.ecn (no spm prefix, /<id>/check get, datetime) ======================

def test_ecn_list_url_is_ecn_bom_page_no_spm_prefix():
    ent, tr = _wire(EcnEntity, [FakeResponse(200, {"content": [{"id": "e1"}], "last": True})])
    ent.list()
    # 无 spm 前缀：/ecn-bom/page
    assert tr.calls[0]["url"] == _MM_BASE + "/ecn-bom/page"


def test_ecn_get_url_has_check_suffix():
    ent, tr = _wire(EcnEntity, [FakeResponse(200, {"id": "e1", "bomchange_id": "BC-1"})])
    rec = ent.get("e1")
    assert rec["bomchange_id"] == "BC-1"
    # get 尾缀 /check
    assert tr.calls[0]["url"] == _MM_BASE + "/ecn-bom/e1/check"


def test_ecn_list_datetime_and_material_ids_multi():
    ent, tr = _wire(EcnEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(filter={
        "material_ids": ["M-1", "M-2"],            # multi
        "from_time": "2026-01-01T00:00:00",        # datetime 透传不强转
        "to_time": "2026-06-30T23:59:59",
    })
    p = tr.calls[0]["params"]
    assert p["material_ids"] == ["M-1", "M-2"]
    assert p["from_time"] == "2026-01-01T00:00:00"
    assert p["to_time"] == "2026-06-30T23:59:59"


def test_ecn_unknown_filter_key_raises():
    ent, _ = _wire(EcnEntity, [FakeResponse(200, {"content": [], "last": True})])
    with pytest.raises(ValueError):
        ent.list(filter={"nope": 1})


def test_ecn_no_write_methods():
    ent, _ = _wire(EcnEntity, [])
    for w in _WRITE_METHODS:
        assert not hasattr(ent, w)


# ====================== mm.quotation (POST-body paging, weird get path, date+datetime) ======================

def test_quotation_list_is_post_with_filter_in_body():
    ent, tr = _wire(QuotationEntity, [FakeResponse(200, {"content": [{"id": "q1"}], "last": True})])
    page = ent.list(filter={"rfq_no": "RFQ-1"})
    assert page.items == [{"id": "q1"}]
    call = tr.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == _MM_BASE + "/spm-rfq/pages"
    # filter 进 body，page/size 进 query（绝不退化成 GET-query 分页）
    assert call["json"]["rfq_no"] == "RFQ-1"
    assert call["params"]["page"] == "0"
    assert call["params"]["size"] == "20"
    # filter 不在 query
    assert "rfq_no" not in call["params"]


def test_quotation_list_multi_filter_is_body_json_array_not_repeated_query():
    ent, tr = _wire(QuotationEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(filter={"supplier_ids": [101, 102], "statuses": ["OPEN"]})
    call = tr.calls[0]
    # multi 进 body 作 JSON 数组（不是 GET repeated query string）
    assert call["json"]["supplier_ids"] == [101, 102]
    assert call["json"]["statuses"] == ["OPEN"]
    assert "supplier_ids" not in (call["params"] or {})


def test_quotation_list_date_and_datetime_dual_keys_passthrough():
    ent, tr = _wire(QuotationEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(filter={
        "quotation_date_from": "2026-01-01",                  # date
        "quotation_date_time_from": "2026-01-01T08:00:00",    # datetime（双套并存）
        "rfq_id": 55,                                          # integer
    })
    body = tr.calls[0]["json"]
    # 两套日期 key 都原样透传，不强转、不互相覆盖
    assert body["quotation_date_from"] == "2026-01-01"
    assert body["quotation_date_time_from"] == "2026-01-01T08:00:00"
    assert body["rfq_id"] == 55


def test_quotation_get_url_is_quotation_query_subpath():
    ent, tr = _wire(QuotationEntity, [FakeResponse(200, {"id": "q1", "quotation_no": "QT-1"})])
    rec = ent.get("q1")
    assert rec["quotation_no"] == "QT-1"
    # get 是完全不同子路径 /spm-rfq/quotation/query/<id>
    assert tr.calls[0]["url"] == _MM_BASE + "/spm-rfq/quotation/query/q1"
    assert tr.calls[0]["method"] == "GET"


def test_quotation_unknown_filter_key_raises():
    ent, _ = _wire(QuotationEntity, [FakeResponse(200, {"content": [], "last": True})])
    with pytest.raises(ValueError):
        ent.list(filter={"made_up": 1})


def test_quotation_list_does_not_use_get_paged_entity():
    # 回归 POST-body 分页不混 GET：QuotationEntity 必须继承 PostPagedEntity
    from in3_client.entities.base import PostPagedEntity
    assert issubclass(QuotationEntity, PostPagedEntity)


def test_quotation_no_write_methods():
    ent, _ = _wire(QuotationEntity, [])
    for w in _WRITE_METHODS:
        assert not hasattr(ent, w)
