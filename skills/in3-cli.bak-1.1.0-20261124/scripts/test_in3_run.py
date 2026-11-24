"""execute 执行核 + audit 单测（issue #2）。用真子进程跑极小代码（快、确定）。"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import in3_run  # noqa: E402
from in3_run import ExecuteContext, execute  # noqa: E402


def _ctx(tmp_path, timeout_s=300, cap=in3_run.DEFAULT_OUTPUT_CAP, pythonpath=None, args=None, audit=True):
    return ExecuteContext(
        workspace=tmp_path,
        tenant_alias="zhuzheng",
        env={"PATH": __import__("os").environ.get("PATH", "")},
        pythonpath=pythonpath or [],
        timeout_s=timeout_s,
        output_cap_bytes=cap,
        audit=audit,
        script_args=args or [],
    )


def test_code_runs_and_captures_stdout(tmp_path):
    r = execute(None, "print('hello-core')", _ctx(tmp_path))
    assert "hello-core" in r.stdout
    assert r.exit_code == 0
    assert r.truncated is False


def test_exit_code_passthrough(tmp_path):
    r = execute(None, "import sys; sys.exit(3)", _ctx(tmp_path))
    assert r.exit_code == 3


def test_result_has_exactly_five_fields(tmp_path):
    r = execute(None, "print(1)", _ctx(tmp_path))
    from dataclasses import fields
    assert {f.name for f in fields(r)} == {"stdout", "stderr", "exit_code", "duration_s", "truncated"}


def test_script_and_code_both_none_raises(tmp_path):
    with pytest.raises(ValueError):
        execute(None, None, _ctx(tmp_path))


def test_code_takes_priority_over_script(tmp_path):
    script = tmp_path / "s.py"
    script.write_text("print('FROM_SCRIPT')")
    r = execute(str(script), "print('FROM_CODE')", _ctx(tmp_path))
    assert "FROM_CODE" in r.stdout and "FROM_SCRIPT" not in r.stdout


def test_timeout_yields_124(tmp_path):
    r = execute(None, "import time; time.sleep(5)", _ctx(tmp_path, timeout_s=1))
    assert r.exit_code == 124


def test_default_timeout_is_300():
    assert in3_run.DEFAULT_TIMEOUT_S == 300


def test_output_over_cap_truncated_with_mark(tmp_path):
    # 打印 > cap 字节
    r = execute(None, "print('x' * 200)", _ctx(tmp_path, cap=50))
    assert r.truncated is True
    assert r.stdout.endswith("[TRUNCATED@64KB]")
    assert len("x" * 200) > 50


def test_output_under_cap_not_truncated(tmp_path):
    r = execute(None, "print('short')", _ctx(tmp_path, cap=65536))
    assert r.truncated is False
    assert "[TRUNCATED@64KB]" not in r.stdout


def test_script_args_passed_through(tmp_path):
    script = tmp_path / "s.py"
    script.write_text("import sys; print('ARG=' + sys.argv[1])")
    r = execute(str(script), None, _ctx(tmp_path, args=["hello"]))
    assert "ARG=hello" in r.stdout


def test_pythonpath_injection(tmp_path):
    libdir = tmp_path / "lib"
    libdir.mkdir()
    (libdir / "mymod.py").write_text("VALUE = 'injected-ok'")
    r = execute(None, "import mymod; print(mymod.VALUE)", _ctx(tmp_path, pythonpath=[str(libdir)]))
    assert "injected-ok" in r.stdout


# ---------- audit ----------

def _latest_audit(tmp_path):
    files = list((tmp_path / "audit").glob("*.json"))
    return json.loads(max(files, key=lambda p: p.stat().st_mtime).read_text())


def test_audit_record_fields_complete(tmp_path):
    execute(None, "print('audited')", _ctx(tmp_path))
    rec = _latest_audit(tmp_path)
    assert set(rec.keys()) == {
        "timestamp", "tenant", "script_source", "exit_code", "duration_s",
        "stdout_excerpt", "stderr_excerpt", "output_truncated", "timed_out",
    }
    assert rec["tenant"] == "zhuzheng"
    assert rec["exit_code"] == 0
    assert rec["timed_out"] is False


def test_audit_timeout_record(tmp_path):
    execute(None, "import time; time.sleep(5)", _ctx(tmp_path, timeout_s=1))
    rec = _latest_audit(tmp_path)
    assert rec["timed_out"] is True
    assert rec["exit_code"] == 124


def test_audit_truncation_flag_consistent(tmp_path):
    execute(None, "print('y' * 200)", _ctx(tmp_path, cap=50))
    rec = _latest_audit(tmp_path)
    assert rec["output_truncated"] is True
    assert rec["stdout_excerpt"].endswith("[TRUNCATED@64KB]")


def test_audit_dir_autocreated(tmp_path):
    assert not (tmp_path / "audit").exists()
    execute(None, "print(1)", _ctx(tmp_path))
    assert (tmp_path / "audit").is_dir()


def test_audit_rotation_keeps_100(tmp_path):
    # 写 105 条不同源 → 仅留最近 100
    for i in range(105):
        execute(None, f"print({i})", _ctx(tmp_path))
    files = list((tmp_path / "audit").glob("*.json"))
    assert len(files) == in3_run.AUDIT_KEEP


def test_audit_disabled_writes_nothing(tmp_path):
    execute(None, "print(1)", _ctx(tmp_path, audit=False))
    assert not (tmp_path / "audit").exists()
