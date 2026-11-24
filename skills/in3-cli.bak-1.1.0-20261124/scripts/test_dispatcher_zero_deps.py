"""issue #2 AC 行68：dispatcher 本体启动不 import in3_client/requests/pandas。

只有子进程脚本 / cmd_run 内 lazy import 才碰 SDK；`import in3_cli` 本身必须零外部依赖，
这样未装 SDK / 无 pandas 时 status/login/exec 等子命令照常工作（`in3_cli.py --help` 不炸）。
用干净子进程验证（当前 pytest 进程可能已加载这些模块，必须隔离）。
"""
import subprocess
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent

_HEAVY = ("in3_client", "requests", "pandas", "numpy")


def _run(pycode: str):
    return subprocess.run(
        [sys.executable, "-c", pycode],
        cwd=str(_SCRIPTS), capture_output=True, text=True,
    )


def test_import_in3_cli_does_not_pull_sdk_or_heavy_deps():
    code = (
        "import sys, in3_cli\n"
        f"leaked = [m for m in {_HEAVY!r} if m in sys.modules]\n"
        "print('LEAK:' + ','.join(leaked))\n"
        "sys.exit(1 if leaked else 0)\n"
    )
    r = _run(code)
    assert r.returncode == 0, f"dispatcher 启动泄漏重依赖: {r.stdout.strip()} | {r.stderr.strip()}"


def test_build_parser_does_not_pull_sdk():
    # 构建 argparse（--help 走的路径）也不应触发 SDK / pandas import。
    code = (
        "import sys, in3_cli\n"
        "in3_cli.build_parser()\n"
        f"leaked = [m for m in {_HEAVY!r} if m in sys.modules]\n"
        "print('PARSER_OK LEAK:' + ','.join(leaked))\n"
        "sys.exit(1 if leaked else 0)\n"
    )
    r = _run(code)
    assert "PARSER_OK" in r.stdout, r.stderr
    assert r.returncode == 0, f"build_parser 泄漏重依赖: {r.stdout.strip()} | {r.stderr.strip()}"
