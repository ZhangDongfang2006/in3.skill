"""cmd_init SDK wheel 离线装（issue #2 行63-68 / #7 行42-48）单测。

mock `_pip_install_to_target`（不真跑 pip）验证两层装配语义：
- 硬装 in3_client + requests，软装 pandas（best-effort）；
- 缺当前平台 pandas wheel → 跳过不硬失败；
- 缺 wheelhouse → 整步跳过不调 pip、不抛；
- pip 命令形态含 --no-index --find-links --target。
"""
from pathlib import Path

import pytest

import in3_cli


class _FakePip:
    def __init__(self, rc: int = 0, stderr: str = ""):
        self.returncode = rc
        self.stderr = stderr


def _wheelhouse(tmp_path: Path, names=("in3_client-1.1.0-py3-none-any.whl", "requests-2.34.2-py3-none-any.whl")):
    d = tmp_path / "wh"
    d.mkdir()
    for n in names:
        (d / n).write_text("fake wheel")
    return d


def test_both_layers_install(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        in3_cli, "_pip_install_to_target",
        lambda pkgs, find_links, target: (calls.append((list(pkgs), Path(target))) or _FakePip(0)),
    )
    ws = tmp_path / "ws"; ws.mkdir()
    res = in3_cli._install_sdk_wheels(ws, find_links=_wheelhouse(tmp_path))
    assert res["installed"] == ["in3_client", "requests", "pandas"]
    assert res["skipped"] == []
    assert calls[0][0] == ["in3_client", "requests"]   # 硬装层
    assert calls[1][0] == ["pandas"]                    # 软装层
    assert calls[0][1] == ws / "python-packages"        # target 指向 workspace


def test_pandas_missing_is_skipped_not_fatal(tmp_path, monkeypatch):
    # pandas 缺当前平台/py wheel → rc=1；硬装层成功 → init 不失败、pandas 进 skipped。
    monkeypatch.setattr(
        in3_cli, "_pip_install_to_target",
        lambda pkgs, find_links, target: _FakePip(1) if pkgs == ["pandas"] else _FakePip(0),
    )
    ws = tmp_path / "ws"; ws.mkdir()
    res = in3_cli._install_sdk_wheels(ws, find_links=_wheelhouse(tmp_path))
    assert res["installed"] == ["in3_client", "requests"]
    assert res["skipped"] == ["pandas"]


def test_hard_layer_failure_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.setattr(in3_cli, "_pip_install_to_target", lambda *a, **k: _FakePip(1, "boom"))
    ws = tmp_path / "ws"; ws.mkdir()
    res = in3_cli._install_sdk_wheels(ws, find_links=_wheelhouse(tmp_path))  # 不抛
    assert "in3_client" in res["skipped"] and "pandas" in res["skipped"]


def test_empty_wheelhouse_skips_all_without_pip(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(in3_cli, "_pip_install_to_target", lambda *a, **k: (called.append(1), _FakePip(0))[1])
    ws = tmp_path / "ws"; ws.mkdir()
    empty = tmp_path / "empty"; empty.mkdir()
    res = in3_cli._install_sdk_wheels(ws, find_links=empty)
    assert called == []  # 空 wheelhouse 不调 pip
    assert set(res["skipped"]) == {"in3_client", "requests", "pandas"}


def test_missing_wheelhouse_dir_skips(tmp_path, monkeypatch):
    monkeypatch.setattr(in3_cli, "_pip_install_to_target", lambda *a, **k: pytest.fail("缺 wheelhouse 不应调 pip"))
    ws = tmp_path / "ws"; ws.mkdir()
    res = in3_cli._install_sdk_wheels(ws, find_links=tmp_path / "does-not-exist")
    assert set(res["skipped"]) == {"in3_client", "requests", "pandas"}


def test_pip_command_shape(tmp_path, monkeypatch):
    # _pip_install_to_target 构造的 pip 命令含 --no-index --find-links --target（不真跑 pip）。
    captured = {}
    monkeypatch.setattr(in3_cli.subprocess, "run", lambda argv, **kw: captured.update(argv=argv) or _FakePip(0))
    in3_cli._pip_install_to_target(["in3_client", "requests"], tmp_path / "wh", tmp_path / "pkg")
    argv = captured["argv"]
    assert "--no-index" in argv
    assert "--find-links" in argv and str(tmp_path / "wh") in argv
    assert "--target" in argv and str(tmp_path / "pkg") in argv
    assert argv[-2:] == ["in3_client", "requests"]
