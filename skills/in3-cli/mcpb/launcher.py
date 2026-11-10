#!/usr/bin/env python3
"""in3-mcp .mcpb 配置壳的薄 launcher（纯 stdlib，零第三方依赖）。

被 Claude Desktop 用「用户在扩展设置里填的 python」启动（manifest.server.mcp_config.command
= ${user_config.python_path}）。本壳本身不含业务代码 / SDK；它只做一件事：用同一个 python
转去运行用户机器上已装好的 in3_cli.py 的 `mcp` 子命令（dispatcher 自己会定位 SDK + workspace +
租户凭证）。

为什么要这个 launcher 而不是直接 command+args 指向 in3_cli.py：mcpb 的 server.entry_point
是必填字段且应指向包内真实文件；用包内 launcher 满足它，同时给环境自检 + 友好报错留个落点
（见 MCP-SERVER.md §8.5 路 A）。
"""
import os
import sys
import runpy


def _die(msg: str) -> "NoReturn":  # noqa: F821
    sys.stderr.write(f"[in3-mcp 配置壳] {msg}\n")
    sys.exit(1)


def main() -> None:
    cli_path = os.environ.get("IN3_CLI_PATH")
    if not cli_path:
        _die("缺 IN3_CLI_PATH —— 在 Claude Desktop 扩展设置里填 in3_cli.py 路径后重装/重启。")
    if not os.path.isfile(cli_path):
        _die(f"in3_cli.py 不存在: {cli_path!r}。检查扩展设置里的『in3_cli.py 路径』是否填对。")

    scripts_dir = os.path.dirname(os.path.abspath(cli_path))
    # runpy.run_path 不会自动把脚本目录加进 sys.path；不加则 in3_cli.py 里
    # `import in3_run / in3_mcp`（同目录兄弟模块）会 ModuleNotFoundError。
    sys.path.insert(0, scripts_dir)
    # 让 in3_cli.py 的 argparse 看到 `mcp` 子命令，并以 __main__ 身份执行
    # （触发其 if __name__ == "__main__" 入口；__file__ 由 run_path 设为 cli_path，
    #  dispatcher 据此 Path(__file__).parent 自定位 SDK）。
    sys.argv = [cli_path, "mcp"]
    runpy.run_path(cli_path, run_name="__main__")


if __name__ == "__main__":
    main()
