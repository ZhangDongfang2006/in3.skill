"""SIM CLI：筛选类型、JSON 错误、大输出落盘及免登录自省。"""
import json
from types import SimpleNamespace

import pytest

from in3_client import sf_cli
from in3_client.envelope import Page
from in3_client.http import HttpError


class Issue:
    def __init__(self, items=None, error=None):
        self.items = items or [{"id": "i1", "extra": None}]
        self.error = error
        self.options = None

    def list(self, **options):
        self.options = options
        if self.error:
            raise self.error
        return Page(self.items, 0, len(self.items), False)

    def get(self, entity_id):
        if self.error:
            raise self.error
        return {"id": entity_id, "action_list": []}


def run_cli(monkeypatch, capsys, args, issue=None):
    issue = issue or Issue()
    monkeypatch.setattr(sf_cli, "IN3", lambda **kw: SimpleNamespace(sf=SimpleNamespace(sim_issue=issue)))
    code = sf_cli.main(args)
    output = capsys.readouterr()
    assert output.err == ""
    return code, json.loads(output.out), issue


def test_cli_repeated_filters_are_typed_json_arrays(monkeypatch, capsys):
    code, data, issue = run_cli(monkeypatch, capsys, [
        "sim-issue", "list", "--all", "--page", "2", "--size", "9", "--max", "50",
        "--include-details", "--filter", "status=0", "--filter", "status=1",
        "--filter", "sim_level=SIM1", "--filter", "over_date_only=false",
    ])
    assert code == 0 and data["items"] == issue.items
    assert issue.options == {
        "filter": {"status": [0, 1], "sim_level": ["SIM1"], "over_date_only": False},
        "all": True, "page": 2, "size": 9, "max_items": 50, "max_pages": 1000,
        "include_details": True,
    }


def test_json_array_filter(monkeypatch, capsys):
    _, _, issue = run_cli(monkeypatch, capsys,
                          ["sim-issue", "list", "--filter", 'status=[0,1]'])
    assert issue.options["filter"] == {"status": [0, 1]}


@pytest.mark.parametrize("filters", [["--filter", "status=x"], ["--filter", "no_equals"],
                                    ["--filter", "unknown=x"], ["--filter", "over_date_only=no"],
                                    ["--filter", "key_text=a", "--filter", "key_text=b"]])
def test_bad_filter_is_json_validation_error(monkeypatch, capsys, filters):
    code, data, issue = run_cli(monkeypatch, capsys, ["sim-issue", "list", *filters])
    assert code == 4 and data["error"]["type"] == "VALIDATION"
    assert issue.options is None


def test_invalid_argument_is_json_validation_error(monkeypatch, capsys):
    code, data, _ = run_cli(monkeypatch, capsys, ["sim-issue", "list", "--unknown"])
    assert code == 4 and data["error"]["type"] == "VALIDATION"


@pytest.mark.parametrize("status,kind,exit_code", [(404, "NOT_FOUND", 3), (503, "SERVER", 5),
                                                 (401, "AUTH_FAILED", 2), (403, "FORBIDDEN", 2)])
def test_http_errors_keep_json_envelope(monkeypatch, capsys, status, kind, exit_code):
    code, data, _ = run_cli(monkeypatch, capsys, ["sim-issue", "get", "missing"],
                            Issue(error=HttpError(status, "failed")))
    assert code == exit_code
    assert data["error"] == {"type": kind, "message": "failed", "http_status": status}


def test_get_returns_complete_detail(monkeypatch, capsys):
    code, data, _ = run_cli(monkeypatch, capsys, ["sim-issue", "get", "i9"])
    assert code == 0 and data == {"id": "i9", "action_list": []}


def test_large_output_written_completely_and_with_private_permissions(monkeypatch, capsys, tmp_path):
    rows = [{"id": f"i{n}", "description": "完整明细" * 1000} for n in range(100)]
    path = tmp_path / "sim.json"
    code, data, _ = run_cli(monkeypatch, capsys,
                            ["sim-issue", "list", "--all", "--output", str(path)], Issue(rows))
    assert code == 0
    assert data["output"] == str(path) and data["count"] == 100
    assert json.loads(path.read_text())["items"] == rows
    assert path.stat().st_size > 65536
    assert path.stat().st_mode & 0o777 == 0o600


def test_output_does_not_overwrite_existing_file(monkeypatch, capsys, tmp_path):
    path = tmp_path / "existing.json"
    path.write_text("existing")
    code, data, _ = run_cli(monkeypatch, capsys,
                            ["sim-issue", "list", "--output", str(path)])
    assert code == 4 and data["error"]["type"] == "VALIDATION"
    assert path.read_text() == "existing"


def test_schema_is_available_without_credentials(monkeypatch, capsys):
    monkeypatch.setattr(sf_cli, "IN3", lambda **kw: pytest.fail("自省不能读取凭证"))
    assert sf_cli.main(["__schema"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert "action_list" in data["commands"]["sim-issue"]["get"]["item_fields"]
    assert len(data["commands"]["sim-issue"]["list"]["item_fields"]) == 67
    assert len(data["commands"]["sim-issue"]["list"]["filter_keys"]) == 59


def test_truncated_output_file_summary_is_explicit(monkeypatch, capsys, tmp_path):
    issue = Issue()
    monkeypatch.setattr(issue, "list", lambda **kw: Page(issue.items, None, None, True, True))
    _, data, _ = run_cli(monkeypatch, capsys,
                         ["sim-issue", "list", "--all", "--output", str(tmp_path / "out.json")], issue)
    assert data["truncated"] and data["has_next"]


def test_version_and_capability_match_package_and_schema(monkeypatch, capsys):
    import re
    from pathlib import Path
    from in3_client import __version__
    from in3_client.sf_schema import schema

    package = Path(sf_cli.__file__).parents[1] / "pyproject.toml"
    assert re.search(r'^version = "([^"]+)"', package.read_text(), re.M).group(1) == __version__
    assert sf_cli.main(["--capability"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["version"] == __version__
    keys = schema(__version__)["commands"]["sim-issue"]["list"]["filter_keys"]
    assert set(data["entities"][0]["filter_keys"]) == {key["name"] for key in keys}
    assert len(schema(__version__)["commands"]["sim-issue"]["get"]["item_fields"]) == 57
