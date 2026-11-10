"""根 conftest：让 `pytest -q` 在 pytest-bdd 未安装时仍能收集单测内环。

BDD 外环（features/ + tests/step_defs/）依赖 pytest-bdd；未装时这些模块 import 即失败，
会中断整个收集。在 pytest-bdd 缺失时跳过 step_defs 目录的收集（外环本就待装后转绿），
单元测试照常运行。装上 pytest-bdd 后此忽略自动失效，BDD scenario 进入收集。
"""
collect_ignore_glob = []

try:
    import pytest_bdd  # noqa: F401
except ImportError:
    collect_ignore_glob.append("tests/step_defs/*")
