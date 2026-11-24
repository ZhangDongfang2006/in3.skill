"""#16 M5 cr 业务实体单测（直接实例化，不经 facade）。

覆盖 cr.opp（GET query-string 分页 + repeated-query 多值 + get）/
cr.service_order（POST-body 分页 + body 数组多值 + 深层嵌套 get 原样穿过）/
cr.fee（POST-body 分页 + price-privileged fail-loud + 无 get）。

三个非协商坑层（issue #16）：
  ① 非 tenant 路径覆写：_list_path/_get_path 忽略 tenant_id，base 走 cred.base_url('cr')
     再拼固定 app-prefix（opp→/ssme、service_order→/flsc、fee→/flsc/v3，三者前缀各自硬编码）。
  ② 两种多值机制不混：opp（GET）多值走 **repeated query**（params 里 list 值）；
     service_order/fee（POST）多值进 **body JSON 数组**（json 里 list 值）。
  ③ price-privileged fail-loud：fee 无 price_viewer 角色时后端返 PRIVILEGE_DENIED，
     SDK 必须 fail-loud 抛错（HttpError），绝不吞成空 Page。

桩照 tests/test_cr_bare_entities.py：FakeResponse / FakeTransport（记录 params / json）。
"""
from dataclasses import dataclass, field

import pytest

from in3_client.auth import Session
from in3_client.config import Credentials
from in3_client.envelope import Page
from in3_client.http import HttpError
from in3_client.entities.cr import (
    FeeEntity,
    OppEntity,
    ServiceOrderEntity,
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

_CR_BASE = "https://apiv3.industics.com/service/mom/cr"


def _wire(entity_cls, data_responses, **kw):
    from in3_client.http import HttpClient

    sess = Session(_CRED, transport=FakeTransport([FakeResponse(200, _TOKEN)]))
    data_tr = FakeTransport(data_responses)
    http = HttpClient(sess, transport=data_tr)
    return entity_cls(_CRED, sess, http, **kw), data_tr


# Spring Page 信封（GET/POST 分页归一用）→ 包成 FakeResponse(200, ...)。
def _page_env(content, *, last=True):
    return FakeResponse(200, {"content": content, "last": last, "totalElements": len(content)})


# ---------- cr.opp（GET query-string 分页 + get） ----------

def test_opp_list_get_query_string_pagination():
    ent, tr = _wire(OppEntity, [_page_env([{"id": "o1", "opp_no": "OPP-1"}])])
    page = ent.list()
    assert isinstance(page, Page)
    assert page.items == [{"id": "o1", "opp_no": "OPP-1"}]
    call = tr.calls[0]
    assert call["method"] == "GET"
    # page/size 进 query（GET 分页）。
    assert call["params"]["page"] == "0"
    assert call["params"]["size"] == "20"
    # filter 在 query string，body 不带 filter（GET 无 json）。
    assert call["json"] is None


def test_opp_list_path_app_prefix_ssme_not_tenant_templated():
    ent, tr = _wire(OppEntity, [_page_env([])])
    ent.list()
    url = tr.calls[0]["url"]
    assert url == _CR_BASE + "/ssme/opps/page"
    assert "/v2/api/tenants/" not in url
    # opp 走 /ssme（不是 /flsc）。
    assert "/ssme/" in url
    assert "/flsc" not in url


def test_opp_multi_value_filter_repeated_query_not_json_array():
    # 多值 filter（stage_code/win_flag/status/industry_type）走 repeated query：
    # params 里是 list 值（http/requests 序列化成 repeated key），**不是** JSON body 数组。
    ent, tr = _wire(OppEntity, [_page_env([])])
    ent.list(filter={"stage_code": ["S1", "S2"], "status": ["OPEN", "WON"]})
    call = tr.calls[0]
    assert call["json"] is None  # GET，多值不进 body
    assert call["params"]["stage_code"] == ["S1", "S2"]
    assert call["params"]["status"] == ["OPEN", "WON"]


def test_opp_integer_region_filter_passthrough_no_str_coercion():
    # country/province/city/district 是 integer 类型 filter，原样透传不强转 str。
    ent, tr = _wire(OppEntity, [_page_env([])])
    ent.list(filter={"province": 320000, "city": 320100})
    call = tr.calls[0]
    assert call["params"]["province"] == 320000
    assert call["params"]["city"] == 320100
    assert isinstance(call["params"]["province"], int)


def test_opp_get_single_record_ssme_path():
    ent, tr = _wire(OppEntity, [FakeResponse(200, {"id": "o9", "opp_name": "大单", "stage_code": "S3"})])
    rec = ent.get("o9")
    assert rec["opp_name"] == "大单"
    call = tr.calls[0]
    assert call["method"] == "GET"
    assert call["url"] == _CR_BASE + "/ssme/opps/o9"
    assert "/v2/api/tenants/" not in call["url"]


# ---------- cr.service_order（POST-body 分页 + body 数组多值 + 深层嵌套 get） ----------

def test_service_order_list_post_body_pagination():
    ent, tr = _wire(ServiceOrderEntity, [_page_env([{"id": "so1", "service_order_sn": "SO-1"}])])
    page = ent.list()
    assert page.items[0]["service_order_sn"] == "SO-1"
    call = tr.calls[0]
    assert call["method"] == "POST"
    # filter 进 body、page/size 进 query。
    assert call["params"]["page"] == "0"
    assert call["params"]["size"] == "20"
    assert call["json"] is not None


def test_service_order_list_path_app_prefix_flsc_not_tenant_templated():
    ent, tr = _wire(ServiceOrderEntity, [_page_env([])])
    ent.list()
    url = tr.calls[0]["url"]
    assert url == _CR_BASE + "/flsc/service-orders/page"
    assert "/v2/api/tenants/" not in url
    # service_order 走 /flsc（无 v3）。
    assert "/flsc/" in url
    assert "/flsc/v3" not in url
    assert "/ssme" not in url


def test_service_order_multi_value_filter_body_json_array_not_repeated_query():
    # 多值 filter（status/service_staff/service_type_codes）进 **body JSON 数组**，
    # **不是** repeated query —— 与 opp 的 GET 多值机制不混。
    ent, tr = _wire(ServiceOrderEntity, [_page_env([])])
    ent.list(filter={"status": ["A", "B"], "service_staff": ["u1", "u2"]})
    call = tr.calls[0]
    assert call["json"]["status"] == ["A", "B"]
    assert call["json"]["service_staff"] == ["u1", "u2"]
    # 多值不在 query（query 只有 page/size）。
    assert "status" not in call["params"]
    assert "service_staff" not in call["params"]


def test_service_order_date_filter_passthrough_no_coercion():
    # 时间 filter 是 date 形 YYYY-MM-DD（非 sd 的 datetime ISO），SDK 只透传不强转。
    ent, tr = _wire(ServiceOrderEntity, [_page_env([])])
    ent.list(filter={"start_date": "2026-01-01", "end_date": "2026-01-31"})
    call = tr.calls[0]
    assert call["json"]["start_date"] == "2026-01-01"
    assert call["json"]["end_date"] == "2026-01-31"


def test_service_order_get_deep_nested_vo_passthrough_no_flatten():
    # get 返回深层嵌套 VO（work logs / dispatch history / evaluation items）原样穿过不展平。
    detail = {
        "id": "so7",
        "service_order_sn": "SO-7",
        "work_logs": [{"id": "wl1", "content": "巡检", "items": [{"k": "v"}]}],
        "dispatch_history": [{"id": "d1", "staff": "u1"}],
        "evaluation_items": [{"id": "e1", "score": 5}],
    }
    ent, tr = _wire(ServiceOrderEntity, [FakeResponse(200, detail)])
    rec = ent.get("so7")
    # 整树原样穿过（dict-equality，含嵌套）。
    assert rec == detail
    call = tr.calls[0]
    assert call["method"] == "GET"
    assert call["url"] == _CR_BASE + "/flsc/service-orders/so7"


def test_service_order_all_true_stops_on_has_next_not_total():
    # all=True 翻页靠 has_next（last 字段）——cr POST 端点 total 可能 null，绝不按 total 死循环。
    ent, tr = _wire(ServiceOrderEntity, [
        # 第 0 页 total=null、last=false → 还要翻；第 1 页 last=true → 停。
        FakeResponse(200, {"content": [{"id": "a"}], "last": False, "total": None}),
        FakeResponse(200, {"content": [{"id": "b"}], "last": True, "total": None}),
    ])
    page = ent.list(all=True)
    assert [r["id"] for r in page.items] == ["a", "b"]
    assert len(tr.calls) == 2


# ---------- cr.fee（POST-body 分页 + price-privileged fail-loud + 无 get） ----------

def test_fee_list_post_body_pagination_flsc_v3_path():
    ent, tr = _wire(FeeEntity, [_page_env([{"id": "f1", "amount": 100}])])
    page = ent.list()
    assert page.items[0]["amount"] == 100
    call = tr.calls[0]
    assert call["method"] == "POST"
    # /flsc/v3（带版本段）—— 与 service_order 的 /flsc（无 v3）不同。
    assert call["url"] == _CR_BASE + "/flsc/v3/service-orders/fees/page"
    assert "/flsc/v3/" in call["url"]
    assert "/v2/api/tenants/" not in call["url"]


def test_fee_multi_value_filter_body_json_array():
    # multi:true 的 fee_ids/service_staffs 等走 body 数组（POST 机制，非 repeated query）。
    ent, tr = _wire(FeeEntity, [_page_env([])])
    ent.list(filter={"fee_ids": ["f1", "f2"], "service_staffs": ["u1"]})
    call = tr.calls[0]
    assert call["json"]["fee_ids"] == ["f1", "f2"]
    assert call["json"]["service_staffs"] == ["u1"]


def test_fee_date_filter_passthrough():
    ent, tr = _wire(FeeEntity, [_page_env([])])
    ent.list(filter={"fee_date_from": "2026-02-01", "fee_date_to": "2026-02-28"})
    call = tr.calls[0]
    assert call["json"]["fee_date_from"] == "2026-02-01"
    assert call["json"]["fee_date_to"] == "2026-02-28"


def test_fee_no_privilege_fail_loud_not_swallowed_empty_page():
    # price-privileged：无 price_viewer 角色 → 后端返 PRIVILEGE_DENIED（403 网关拒）。
    # SDK 必须 fail-loud 抛 HttpError，**绝不**吞成空 Page（否则 agent 误判'真没费用' vs '没权限'）。
    # 桩响应体含 {code: 'PRIVILEGE_DENIED'} —— 收紧验：fee.list 不 try/except 吞成空 Page，错误冒泡。
    ent, tr = _wire(FeeEntity, [
        FakeResponse(403, {"code": "PRIVILEGE_DENIED", "message": "no price_viewer role"}),
    ])
    result = None
    with pytest.raises(HttpError) as exc:
        result = ent.list()
    # 关键 fail-loud 断言：抛了 HttpError（403），**没有**返回任何 Page（吞成空就会有 result）。
    assert result is None
    assert exc.value.status == 403
    # 确实打了网络（不是入口短路）——但错误冒泡，没被吞成 Page。
    assert len(tr.calls) == 1
    # 注：当前 frozen base 的 HttpError(status, message) 只带 status + "{method} {url} → 403"，
    # **不携带** 响应体里的 PRIVILEGE_DENIED code（http._request 抛错时丢弃 body）。故无法在
    # HttpError 上断言该 code 字面量——结构层 fail-loud（403 冒泡、不吞 Page）已是 fee 的全部语义。
    # 如需让 agent 直接读到 PRIVILEGE_DENIED code，须改 frozen http.py 给 HttpError 挂 payload（本次不动）。
    assert "403" in str(exc.value)  # 至少 status 在 message 里可见，agent 能据 status 判'无权限'


def test_fee_has_no_get():
    # schema 无 get verb —— 忠实只暴露 list，绝不假装 get。
    ent, _ = _wire(FeeEntity, [])
    assert not hasattr(ent, "get")


# ---------- 只读边界守护 ----------

@pytest.mark.parametrize("cls", [OppEntity, ServiceOrderEntity, FeeEntity])
def test_cr_post_entities_no_write_methods(cls):
    ent, _ = _wire(cls, [])
    for w in ("create", "update", "delete", "post_write", "save", "remove"):
        assert not hasattr(ent, w)
