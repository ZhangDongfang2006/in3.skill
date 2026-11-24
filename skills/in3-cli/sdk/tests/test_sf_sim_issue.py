"""SIM 查询契约：POST 请求体分页、全量翻页、完整字段及详情补齐。"""
from dataclasses import dataclass, field

import pytest

from in3_client import IN3
from in3_client.config import Credentials
from in3_client.http import HttpError


@dataclass
class Response:
    data: object
    status_code: int = 200
    headers: dict = field(default_factory=lambda: {"content-type": "application/json"})

    def json(self):
        return self.data


class Transport:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def __call__(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        return next(self.responses)


def wire(responses, tenant_id="99979"):
    transport = Transport(responses)
    cred = Credentials("https://api.example/service", "example", "user", "cipher", "test")
    auth = Transport([Response({"access_token": "test", "tenant_id": tenant_id,
                               "tenant_domain": "example", "user_id": "u1"})])
    return IN3(cred=cred, transport=transport, auth_transport=auth), transport


def test_list_sends_post_filters_and_pagination_in_body():
    api, transport = wire([Response({"content": [], "number": 3, "last": True})])
    api.sf.sim_issue.list(filter={"status": [0, 1], "sim_level": ["SIM1", "SIM2"],
                                  "personally_concerned": False}, page=3, size=7, all=False)
    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://api.example/service/mom/sf/v2/api/tenants/99979/ld/sime/issues/page"
    assert call["json"] == {"status": [0, 1], "sim_level": ["SIM1", "SIM2"],
                            "personally_concerned": False, "page": 3, "size": 7,
                            "sort": ["si.id,asc"]}
    assert not call.get("params")


def test_all_follows_last_without_using_total_and_preserves_unknown_fields():
    rows = [{"id": "i1", "new_server_field": {"nested": [1, None]}},
            {"id": "i2", "column_a": None}]
    api, transport = wire([
        Response({"content": rows[:1], "total_elements": 0, "last": False}),
        Response({"content": rows[1:], "total_elements": 0, "last": True}),
    ])
    result = api.sf.sim_issue.list(size=1)
    assert result.items == rows
    assert [call["json"]["page"] for call in transport.calls] == [0, 1]
    assert result.has_next is False and result.truncated is False


def test_single_page_keeps_backend_total():
    api, _ = wire([Response({"content": [{"id": "i1"}], "total_elements": 42,
                            "number": 2, "last": False})])
    result = api.sf.sim_issue.list(page=2, all=False)
    assert (result.page, result.total, result.has_next) == (2, 42, True)


def test_all_starts_at_requested_page():
    api, transport = wire([Response({"content": [], "last": True})])
    api.sf.sim_issue.list(page=4)
    assert transport.calls[0]["json"]["page"] == 4


def test_details_keep_list_fields_and_full_nested_detail():
    detail = {"id": "i1", "description": "完整描述", "action_list": [{"attachments": ["a"]}],
              "log_list": [{"remark": "完成"}], "images": [{"url": "signed"}],
              "root_causes": [{"code": "A"}], "sim_issue_refs": [{"ref_order_id": "so1"}]}
    api, transport = wire([
        Response({"content": [{"id": "i1", "sim1_pf_date": "2026-10-01", "description": "摘要"}],
                  "last": True}), Response(detail),
    ])
    row = api.sf.sim_issue.list(include_details=True).items[0]
    assert row["sim1_pf_date"] == "2026-10-01"
    assert row["description"] == "完整描述"
    assert row["detail"] == detail
    assert transport.calls[1]["method"] == "GET"
    assert transport.calls[1]["url"].endswith("/ld/sime/issues/i1")


def test_detail_null_does_not_erase_list_value():
    api, _ = wire([Response({"content": [{"id": "i1", "description": "列表描述"}], "last": True}),
                   Response({"id": "i1", "description": None})])
    row = api.sf.sim_issue.list(include_details=True).items[0]
    assert row["description"] == "列表描述"
    assert row["detail"]["description"] is None


def test_detail_failure_does_not_return_partial_success():
    api, _ = wire([Response({"content": [{"id": "i1"}], "last": True}), Response({}, 503)])
    with pytest.raises(HttpError) as exc:
        api.sf.sim_issue.list(include_details=True)
    assert exc.value.status == 503


def test_detail_enrichment_requires_issue_id():
    api, _ = wire([Response({"content": [{"description": "缺少ID"}], "last": True})])
    with pytest.raises(ValueError, match="id"):
        api.sf.sim_issue.list(include_details=True)


def test_get_uses_authenticated_tenant_and_escapes_id():
    api, transport = wire([Response({"id": "other"})], tenant_id="12345")
    api.sf.sim_issue.get("a/b")
    assert transport.calls[0]["url"].endswith("/tenants/12345/ld/sime/issues/a%2Fb")


def test_get_not_found_raises():
    api, _ = wire([Response({}, 404)])
    with pytest.raises(HttpError) as exc:
        api.sf.sim_issue.get("missing")
    assert exc.value.status == 404


def test_unknown_filter_rejected_before_network():
    api, transport = wire([])
    with pytest.raises(ValueError):
        api.sf.sim_issue.list(filter={"unknown_field": "ignored"})
    assert transport.calls == []


def test_sort_is_validated_and_has_unique_tiebreaker():
    api, transport = wire([Response({"content": [], "last": True})])
    api.sf.sim_issue.list(filter={"sort": ["reported_date,desc"]})
    assert transport.calls[0]["json"]["sort"] == ["si.reported_date,desc", "si.id,asc"]


@pytest.mark.parametrize("data", [{"error": {"message": "failure"}}, {}, {"content": None}])
def test_malformed_response_is_not_reported_as_empty_success(data):
    api, _ = wire([Response(data)])
    with pytest.raises(ValueError):
        api.sf.sim_issue.list()


def test_ignored_pagination_is_reported_as_failure():
    api, _ = wire([Response({"content": [{"id": "i1"}], "number": 0, "last": False}),
                   Response({"content": [{"id": "i1"}], "number": 0, "last": True})])
    with pytest.raises(ValueError, match="page"):
        api.sf.sim_issue.list(size=1)


def test_empty_non_last_page_does_not_loop_until_limit():
    api, _ = wire([Response({"content": [], "last": False})])
    with pytest.raises(ValueError):
        api.sf.sim_issue.list()


@pytest.mark.parametrize("options", [{"size": 0}, {"page": -1}, {"max_pages": 0},
                                     {"max_items": 0}, {"filter": {"status": ["bad"]}},
                                     {"filter": {"over_date_only": "false"}},
                                     {"filter": {"sim_level": "SIM1"}},
                                     {"filter": {"sort": ["id;DROP TABLE x,asc"]}},
                                     {"filter": {"start_reported_date": "2026-99-01"}}])
def test_invalid_input_rejected_before_network(options):
    api, transport = wire([])
    with pytest.raises(ValueError):
        api.sf.sim_issue.list(**options)
    assert transport.calls == []


def test_max_pages_marks_incomplete():
    api, _ = wire([Response({"content": [{"id": "i1"}], "last": False})])
    result = api.sf.sim_issue.list(max_pages=1)
    assert result.truncated and result.has_next


def test_max_items_marks_incomplete_and_only_enriches_returned_rows():
    api, transport = wire([
        Response({"content": [{"id": "i1"}, {"id": "i2"}], "last": False}),
        Response({"content": [{"id": "i3"}, {"id": "i4"}], "last": True}),
        Response({"id": "i1"}), Response({"id": "i2"}), Response({"id": "i3"}),
    ])
    result = api.sf.sim_issue.list(size=2, max_items=3, include_details=True)
    assert [row["id"] for row in result.items] == ["i1", "i2", "i3"]
    assert result.truncated and result.has_next
    assert len(transport.calls) == 5


def test_max_items_equal_actual_total_is_complete():
    api, _ = wire([Response({"content": [{"id": "i1"}], "last": True})])
    result = api.sf.sim_issue.list(max_items=1)
    assert not result.truncated and not result.has_next


def test_no_mutating_methods_exposed():
    api, _ = wire([])
    for method in ("create", "update", "delete", "save", "close"):
        assert not hasattr(api.sf.sim_issue, method)
