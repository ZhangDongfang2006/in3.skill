"""#14 M3 pp 业务单据单测（直接实例化实体，不经 facade）。

Wave2 6 实体（§6 行 492-581）：
- production_plan：POST-body 分页 + camelCase filter 透传 + include_items **client-side
  enrich_items_fanout**（fail-isolated）；per-source（records/issues/kitting）失败 → inline {error}
  子对象，单 header 整体抓取失败 → items=None+items_error（不冒泡）。
- demand_supply：POST-body 分页（照 PostPagedEntity）+ camelCase filter + get(id)。
- sales_order：SO **物料视图**（非 SO header），list POST-paged + camelCase filter；
  get 返裸 List → 包 {id, items} surrogate。
- bom_tree：**get-only**（无 .list），bulk POST /mds/materials/bom-tree/bulk，CSV/list material ids
  → 多 id fan 成多树；硬编码字面 path。
- production_plan_record：productionPlanId **必填进 URL 路径段**（{ppId}），缺失 fail-loud；裸 List 包 Page。
- kitting_template：list GET-paged（snake_case filter material_group/material_category）；
  get 是 surrogate（取该模板 items 首页 → {id, items}，可能 truncation）。

camelCase（production_plan/demand_supply/sales_order）vs snake_case（kitting_template）在 pp 内碎到
entity，逐个按 §6 透传——本测专门钉死「不要把 snake 误驼峰、不要把 camel 误 snake」。
"""
from dataclasses import dataclass, field

import pytest

from in3_client.auth import Session
from in3_client.config import Credentials
from in3_client.envelope import Page
from in3_client.http import HttpClient, HttpError
from in3_client.entities.pp import (
    ProductionPlanEntity,
    DemandSupplyEntity,
    SalesOrderEntity,
    BomTreeEntity,
    ProductionPlanRecordEntity,
    KittingTemplateEntity,
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

_PP_BASE = "https://apiv3.industics.com/service/mom/pp"


def _wire(entity_cls, data_responses, **kw):
    sess = Session(_CRED, transport=FakeTransport([FakeResponse(200, _TOKEN)]))
    data_tr = FakeTransport(data_responses)
    http = HttpClient(sess, transport=data_tr)
    return entity_cls(_CRED, sess, http, **kw), data_tr


# =========================================================
# pp.demand_supply —— POST-body 分页 + camelCase filter + get
# =========================================================

def test_demand_supply_list_is_post_with_body_filter():
    ent, tr = _wire(DemandSupplyEntity, [
        FakeResponse(200, {"content": [{"id": "d1"}], "last": True}),
    ])
    ent.list(filter={"plantId": "P1"}, size=20, all=False)
    call = tr.calls[0]
    assert call["method"] == "POST"  # 绝不退回 GET
    # live parity 校正：pp POST 端点要求 page/size 随 filter 一起进 body（number 型），无 query 参。
    assert call["json"] == {"plantId": "P1", "page": 0, "size": 20}  # filter + 分页全进 body
    assert call["params"] is None  # 无 query 参


def test_demand_supply_multi_value_filter_is_body_json_array():
    # 多值过滤进 body JSON 数组（不是 GET repeated query string）。
    ent, tr = _wire(DemandSupplyEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(filter={"materialIds": ["M-1", "M-2"]}, size=20, all=False)
    call = tr.calls[0]
    assert call["json"]["materialIds"] == ["M-1", "M-2"]  # body 内是真数组
    # 分页参随 body（number 型），无 query 参。
    assert call["json"]["page"] == 0 and call["json"]["size"] == 20
    assert call["params"] is None


def test_demand_supply_camelcase_keys_passthrough_no_snake():
    # camelCase filter key 原样透传（不做 snake 转换）。
    ent, tr = _wire(DemandSupplyEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(filter={"historyId": "H1", "demandType": "X"}, size=20, all=False)
    body = tr.calls[0]["json"]
    assert "historyId" in body and "demandType" in body
    assert "history_id" not in body and "demand_type" not in body


def test_demand_supply_get_single_record():
    ent, tr = _wire(DemandSupplyEntity, [FakeResponse(200, {"id": "d1", "qty": 5})])
    rec = ent.get("d1")
    assert rec["id"] == "d1"
    assert tr.calls[0]["method"] == "GET"
    assert tr.calls[0]["url"].endswith("/d1")


def test_demand_supply_tenant_templated_url():
    ent, tr = _wire(DemandSupplyEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(all=False)
    assert tr.calls[0]["url"].startswith(_PP_BASE + "/v2/api/tenants/10030/")


# =========================================================
# pp.sales_order —— SO 物料视图（非 header），POST list + surrogate get
# =========================================================

def test_sales_order_list_is_post_body_camelcase():
    ent, tr = _wire(SalesOrderEntity, [FakeResponse(200, {"content": [{"soId": "S1"}], "last": True})])
    ent.list(filter={"soId": "S1", "procurementTypes": ["A", "B"]}, size=20, all=False)
    call = tr.calls[0]
    assert call["method"] == "POST"
    assert call["json"]["soId"] == "S1"
    assert call["json"]["procurementTypes"] == ["A", "B"]  # multi → body array
    # 分页参随 body（number 型），无 query 参。
    assert call["json"]["page"] == 0 and call["json"]["size"] == 20
    assert call["params"] is None


def test_sales_order_get_wraps_bare_list_as_surrogate():
    # get 返裸 List<MaterialStatisticsVO> → 包 {id, items} surrogate（不是 SO header）。
    ent, tr = _wire(SalesOrderEntity, [
        FakeResponse(200, [{"materialNo": "M-1"}, {"materialNo": "M-2"}]),
    ])
    res = ent.get("S1")
    assert res["id"] == "S1"
    assert res["items"] == [{"materialNo": "M-1"}, {"materialNo": "M-2"}]
    assert tr.calls[0]["method"] == "GET"


def test_sales_order_get_empty_list_surrogate():
    ent, tr = _wire(SalesOrderEntity, [FakeResponse(200, [])])
    res = ent.get("S9")
    assert res == {"id": "S9", "items": []}


# =========================================================
# pp.bom_tree —— get-only bulk POST，多 id CSV fan 成多树
# =========================================================

def test_bom_tree_no_list_method():
    # get-only：不假装有 .list（忠实，照 sd 无 .get）。
    ent, _ = _wire(BomTreeEntity, [])
    assert not hasattr(ent, "list")


def test_bom_tree_get_csv_bulk_post_literal_path():
    ent, tr = _wire(BomTreeEntity, [
        FakeResponse(200, {"items": [{"materialId": "M-1"}, {"materialId": "M-2"}], "total": 2}),
    ])
    page = ent.get("M-1,M-2")
    assert isinstance(page, Page)
    assert len(page.items) == 2
    call = tr.calls[0]
    assert call["method"] == "POST"
    # 硬编码字面 /mds/materials/bom-tree/bulk（跨 mds-style，不带 /production-plans 前缀）。
    assert "/mds/materials/bom-tree/bulk" in call["url"]
    assert "/production-plans" not in call["url"]


def test_bom_tree_csv_split_into_id_array_body():
    ent, tr = _wire(BomTreeEntity, [FakeResponse(200, {"items": [], "total": 0})])
    ent.get("M-1,M-2,M-3")
    body = tr.calls[0]["json"]
    # CSV → list[str]（去空白），进 body 数组。
    flat = body.get("material_ids") or body.get("materialIds")
    assert flat == ["M-1", "M-2", "M-3"]


def test_bom_tree_get_accepts_list_arg():
    # 接受 list[str] 也接受 CSV string。
    ent, tr = _wire(BomTreeEntity, [FakeResponse(200, {"items": [], "total": 0})])
    ent.get(["M-1", "M-2"])
    body = tr.calls[0]["json"]
    flat = body.get("material_ids") or body.get("materialIds")
    assert flat == ["M-1", "M-2"]


def test_bom_tree_csv_strips_whitespace_and_empties():
    ent, tr = _wire(BomTreeEntity, [FakeResponse(200, {"items": [], "total": 0})])
    ent.get(" M-1 , , M-2 ")
    body = tr.calls[0]["json"]
    flat = body.get("material_ids") or body.get("materialIds")
    assert flat == ["M-1", "M-2"]  # 空段剔除、首尾空白剥离


# =========================================================
# pp.production_plan_record —— productionPlanId 必填进 URL 路径段
# =========================================================

def test_ppr_list_requires_pp_id_in_path_segment():
    ent, tr = _wire(ProductionPlanRecordEntity, [
        FakeResponse(200, [{"id": "rec1"}, {"id": "rec2"}]),
    ])
    page = ent.list("PP-100")
    assert isinstance(page, Page)
    assert page.total == 2  # 裸 List → coerce 包 Page
    url = tr.calls[0]["url"]
    assert "PP-100" in url  # ppId 进路径段（非 query/body）
    assert tr.calls[0]["params"] is None or "productionPlanId" not in (tr.calls[0]["params"] or {})


def test_ppr_list_missing_pp_id_fail_loud():
    ent, _ = _wire(ProductionPlanRecordEntity, [])
    with pytest.raises((ValueError, TypeError)):
        ent.list("")  # 缺失/空 → fail-loud，不静默调


def test_ppr_list_none_pp_id_fail_loud():
    ent, _ = _wire(ProductionPlanRecordEntity, [])
    with pytest.raises((ValueError, TypeError)):
        ent.list(None)


def test_ppr_get_both_required_pp_id_in_path():
    ent, tr = _wire(ProductionPlanRecordEntity, [FakeResponse(200, {"id": "rec1"})])
    rec = ent.get("rec1", "PP-100")
    assert rec["id"] == "rec1"
    url = tr.calls[0]["url"]
    assert "PP-100" in url and url.endswith("/rec1")


def test_ppr_get_missing_pp_id_fail_loud():
    ent, _ = _wire(ProductionPlanRecordEntity, [])
    with pytest.raises((ValueError, TypeError)):
        ent.get("rec1", "")


def test_ppr_bare_list_empty_not_swallowed():
    ent, tr = _wire(ProductionPlanRecordEntity, [FakeResponse(200, [])])
    page = ent.list("PP-100")
    assert page.items == []
    assert page.total == 0


# =========================================================
# pp.kitting_template —— list GET-paged snake_case filter + surrogate get
# =========================================================

def test_kitting_template_list_is_get_paged_snake_case():
    # list 是 pp 唯一 GET-query-paged 实体；filter key 是 snake_case（与同模块 camelCase 相反）。
    ent, tr = _wire(KittingTemplateEntity, [
        FakeResponse(200, {"content": [{"id": "kt1"}], "last": True}),
    ])
    ent.list(filter={"material_group": "G1", "material_category": "C1"}, size=20, all=False)
    call = tr.calls[0]
    assert call["method"] == "GET"  # GET-query-paged（非 POST）
    # snake_case 透传到 query（**不**驼峰成 materialGroup）。
    assert call["params"].get("material_group") == "G1"
    assert call["params"].get("material_category") == "C1"
    assert "materialGroup" not in call["params"]
    assert "materialCategory" not in call["params"]


def test_kitting_template_get_is_surrogate_id_items():
    # get 无后端单 GET → 回退取该模板 items 首页 → 包 {id, items}。
    ent, tr = _wire(KittingTemplateEntity, [
        FakeResponse(200, {"content": [{"item": "i1"}, {"item": "i2"}], "last": False}),
    ])
    res = ent.get("kt1")
    assert res["id"] == "kt1"
    assert res["items"] == [{"item": "i1"}, {"item": "i2"}]
    # 走 items 子路径（manual-kitting-template-items）。
    url = tr.calls[0]["url"]
    assert "kt1" in url
    assert "manual-kitting-template-items" in url


def test_kitting_template_get_first_page_only_truncation():
    # surrogate get 只取首页（非全量）——构造满页确认不自动翻页。
    ent, tr = _wire(KittingTemplateEntity, [
        FakeResponse(200, {"content": [{"item": "i1"}], "last": False}),
    ])
    ent.get("kt1")
    assert len(tr.calls) == 1  # 单次首页请求，不翻全


def test_kitting_template_list_tenant_templated():
    ent, tr = _wire(KittingTemplateEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(all=False)
    assert tr.calls[0]["url"].startswith(_PP_BASE + "/v2/api/tenants/10030/")


# =========================================================
# pp.production_plan —— POST-body 分页 + camelCase + client-side enrich_items_fanout
# =========================================================

def test_production_plan_list_is_post_body_camelcase():
    ent, tr = _wire(ProductionPlanEntity, [
        FakeResponse(200, {"content": [{"id": "pp1"}], "last": True}),
    ])
    ent.list(filter={"plantId": "P1", "materialIds": ["M-1", "M-2"], "moTypes": ["T1"]},
             size=20, all=False)
    call = tr.calls[0]
    assert call["method"] == "POST"  # 绝不退回 GET-query 分页
    assert call["json"]["plantId"] == "P1"
    assert call["json"]["materialIds"] == ["M-1", "M-2"]  # camelCase + body array
    assert call["json"]["moTypes"] == ["T1"]
    # live parity 校正：pp POST 端点要求 page/size 随 body（number 型），无 query 参。
    assert call["json"]["page"] == 0 and call["json"]["size"] == 20
    assert call["params"] is None
    # 绝不把 materialIds 误成 mm 的 snake material_ids。
    assert "material_ids" not in call["json"]


def test_production_plan_list_no_fanout_when_include_items_false():
    ent, tr = _wire(ProductionPlanEntity, [
        FakeResponse(200, {"content": [{"id": "pp1"}, {"id": "pp2"}], "last": True}),
    ])
    page = ent.list(filter={}, size=20, all=False, include_items=False)
    # include_items=False → 仅 list 一次，无 per-header sub-fetch。
    assert len(tr.calls) == 1
    assert all("items" not in h for h in page.items)


def test_production_plan_include_items_fanout_attaches_per_header():
    # include_items=True → 对每个 header client-side fan-out 取 records/issues/kitting 子源。
    # 用可注入的 fetch_items_for 桩（不打真子端点），验证 enrich 行为。
    ent, tr = _wire(ProductionPlanEntity, [
        FakeResponse(200, {"content": [{"id": "pp1"}, {"id": "pp2"}], "last": True}),
    ])

    def fake_fetch(header):
        return {"records": [{"r": header["id"]}], "issues": [], "kitting": []}

    page = ent.list(filter={}, size=20, all=False, include_items=True,
                    fetch_items_for=fake_fetch)
    by_id = {h["id"]: h for h in page.items}
    assert by_id["pp1"]["items"]["records"] == [{"r": "pp1"}]
    assert by_id["pp2"]["items"]["records"] == [{"r": "pp2"}]


def test_production_plan_include_items_fail_isolated_per_header():
    # 单 header 整体子抓取抛错 → 该 header items=None + items_error，不冒泡，其余正常。
    ent, tr = _wire(ProductionPlanEntity, [
        FakeResponse(200, {"content": [{"id": "ok1"}, {"id": "BAD"}, {"id": "ok2"}], "last": True}),
    ])

    def fake_fetch(header):
        if header["id"] == "BAD":
            raise RuntimeError("boom: 503 sub-fetch")
        return {"records": [{"r": header["id"]}], "issues": [], "kitting": []}

    page = ent.list(filter={}, size=20, all=False, include_items=True,
                    fetch_items_for=fake_fetch)  # 不抛
    by_id = {h["id"]: h for h in page.items}
    assert by_id["BAD"]["items"] is None
    assert "items_error" in by_id["BAD"] and "boom" in by_id["BAD"]["items_error"]
    assert by_id["ok1"]["items"]["records"] == [{"r": "ok1"}]
    assert "items_error" not in by_id["ok1"]
    assert len(page.items) == 3  # 失败 header 仍在


def test_production_plan_default_fetch_items_per_source_inline_error():
    # 默认 fetch_items_for（打真子端点）：per-source 失败 → inline {error} 子对象，
    # 不整体抛（fail-soft-per-source，镜像 CLI）。records 成功、issues 端点 500 → issues={error}。
    # 桩：list(1) + 单 header 的 records(ok)/issues(500)/kitting(ok) 三子端点。
    ent, tr = _wire(ProductionPlanEntity, [
        FakeResponse(200, {"content": [{"id": "pp1"}], "last": True}),  # list
        FakeResponse(200, {"content": [{"r": 1}], "last": True}),        # records ok
        FakeResponse(500, text="boom"),                                  # issues 500
        FakeResponse(200, {"content": [{"k": 1}], "last": True}),        # kitting ok
    ])
    page = ent.list(filter={}, size=20, all=False, include_items=True)
    items = page.items[0]["items"]
    assert items["records"] == [{"r": 1}]
    assert items["kitting"] == [{"k": 1}]
    # issues 子源失败 → inline {error}（不是把整 header 打成 items=None）。
    assert isinstance(items["issues"], dict) and "error" in items["issues"]


def test_production_plan_get_surrogate_or_detail():
    # get(id) 返单条详情（dict）。
    ent, tr = _wire(ProductionPlanEntity, [FakeResponse(200, {"id": "pp1", "sn": "SN1"})])
    rec = ent.get("pp1")
    assert rec["id"] == "pp1"
    assert tr.calls[0]["method"] == "GET"
    assert tr.calls[0]["url"].endswith("/pp1")


# =========================================================
# 只读边界守护 —— 全实体 not hasattr 写方法
# =========================================================

@pytest.mark.parametrize("cls", [
    ProductionPlanEntity, DemandSupplyEntity, SalesOrderEntity,
    BomTreeEntity, ProductionPlanRecordEntity, KittingTemplateEntity,
])
def test_pp_business_entities_no_write_methods(cls):
    ent, _ = _wire(cls, [])
    for w in ("create", "update", "delete", "post_write", "save", "remove"):
        assert not hasattr(ent, w)


def test_bom_tree_get_only_no_list_faithful():
    # bom_tree 是 get-only：not hasattr .list（忠实不假装）。
    ent, _ = _wire(BomTreeEntity, [])
    assert hasattr(ent, "get")
    assert not hasattr(ent, "list")


# =========================================================
# 币种 —— production_plan 是产量/物料导向，§6 schema 无金额字段 → 不接 currency_index
# =========================================================

def test_production_plan_has_no_currency_index_param():
    import inspect  # noqa: PLC0415
    # §6 production-plan schema 无金额/币种字段 → 构造器不接 currency_index（防误套 sd 金额模板）。
    params = inspect.signature(ProductionPlanEntity.__init__).parameters
    assert "currency_index" not in params, "production_plan 不应接 currency_index（无金额字段）"
    # 构造无需币种参数即成立，list 不做归一、无 eager 网络调用。
    ent, tr = _wire(ProductionPlanEntity, [FakeResponse(200, {"content": [], "last": True})])
    ent.list(filter={}, all=False)
    assert len(tr.calls) == 1
