#!/usr/bin/env python3
"""Reproducibly (re)build vendor/python/ wheelhouse for in3-cli SDK offline install.

cmd_init 用 `pip install --no-index --find-links vendor/python/ --target <ws>/python-packages/
in3_client requests pandas` 离线装进 workspace（见 docs/in3-cli-cemcp/issues/2,7）。本脚本把
所需 wheel 拉/打进 vendor/python/。**离线安装本身不需要网；只有跑本脚本重建 wheelhouse 才需要。**

矩阵（2026-06-03 决定，cp312 × 3 平台含 Windows）：
- in3_client            —— 从 ../sdk 打 py3-none-any wheel（纯 Python，任意平台/py 可装）。
- requests 栈 + 时间库   —— universal py3-none-any（requests urllib3 certifi idna charset-normalizer
                           python-dateutil pytz tzdata six），任意 py3/平台可装（硬装目标）。
- pandas + numpy        —— cp312 二进制 × {macOS arm64, linux x86_64(manylinux2014), Windows amd64}。
                           缺平台/py 版本时 cmd_init 优雅跳过 → 运行时 stdlib 降级（df/join 不崩）。

注：各平台取该平台最优 cp312 wheel（pip 逐平台只认兼容 wheel，混版本无害；SDK 仅用 pd.DataFrame）。
要扩 py 版本/平台：改 PY / PLATFORMS 重跑。

用法: python3 vendor/build-wheelhouse.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "python"
SDK = HERE.parent / "sdk"

PY = "312"
PLATFORMS = ["macosx_11_0_arm64", "manylinux2014_x86_64", "win_amd64"]
UNIVERSAL = ["requests", "urllib3", "certifi", "idna",
             "python-dateutil", "pytz", "tzdata", "six"]
BINARY = ["pandas", "numpy"]


def run(args: list[str]) -> None:
    print("  $", " ".join(args))
    subprocess.run(args, check=True)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    pip = [sys.executable, "-m", "pip"]

    print("[1/4] build in3_client wheel (py3-none-any)")
    run([*pip, "wheel", str(SDK), "--no-deps", "-w", str(OUT)])

    print("[2/4] universal pure-python deps (requests 栈 + 时间库)")
    run([*pip, "download", "--no-deps", "--dest", str(OUT), *UNIVERSAL])

    print("[3/4] universal charset-normalizer (py3-none-any，让 requests 跨 py 可装)")
    run([*pip, "download", "--no-deps", "--only-binary=:all:",
         "--python-version", "3.12", "--implementation", "py", "--abi", "none",
         "--platform", "any", "--dest", str(OUT), "charset-normalizer"])

    print(f"[4/4] pandas/numpy cp{PY} binary × {len(PLATFORMS)} 平台")
    for plat in PLATFORMS:
        run([*pip, "download", "--no-deps", "--only-binary=:all:",
             "--python-version", PY, "--implementation", "cp", "--platform", plat,
             "--dest", str(OUT), *BINARY])

    wheels = sorted(p.name for p in OUT.glob("*.whl"))
    print(f"\ndone → {OUT}  ({len(wheels)} wheels)")
    for w in wheels:
        print("   ", w)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
