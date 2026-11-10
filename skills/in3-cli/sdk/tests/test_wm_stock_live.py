"""#6 wm.stock 真后端 parity（@slow，默认不跑）。比业务 items 逐位一致。

注：total 不比——SDK 对不可信 total 置 None，wm CLI 用 ||len/||0，这是有意的安全差异。
fan-out 多值：SDK 与 wm CLI 都支持，比成功 id 的聚合 items 集合。`pytest -m slow` 触发。
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _cli(args):
    out = subprocess.run([sys.executable, "in3_cli.py", "exec", *args],
                         cwd=str(_SCRIPTS), capture_output=True, text=True, check=True)
    return json.loads(out.stdout).get("items", [])


@pytest.mark.slow
def test_stock_views_parity_live():
    import in3_client  # noqa: PLC0415

    in3 = in3_client.IN3(tenant="zhuzheng")

    # 从 bin 视图拿一个有物理库存的 material_id
    bin_items = in3.wm.stock.bin(size=20).items
    assert len(bin_items) > 0, "bin 视图应有真实库存行"
    mid = next((r.get("material_id") for r in bin_items if r.get("material_id")), None)
    assert mid, "应能从 bin 行取到一个 material_id"

    # material 视图单值：items 逐位一致
    sdk_mat = in3.wm.stock.material(material_id=mid).items
    cli_mat = _cli(["wm", "stock", "material", "--material-id", mid])
    assert sdk_mat == cli_mat, "material 视图单值 items 应逐位一致"

    # bin 视图单值（同一 material）：items 逐位一致
    sdk_bin = in3.wm.stock.bin(material_id=mid).items
    cli_bin = _cli(["wm", "stock", "bin", "--material-id", mid])
    assert sdk_bin == cli_bin, "bin 视图单值 items 应逐位一致"


@pytest.mark.slow
def test_stock_fanout_parity_live():
    import in3_client  # noqa: PLC0415

    in3 = in3_client.IN3(tenant="zhuzheng")
    bin_items = in3.wm.stock.bin(size=30).items
    mids = list({r["material_id"] for r in bin_items if r.get("material_id")})[:3]
    assert len(mids) >= 1

    sdk = in3.wm.stock.material(material_ids=mids).items
    # CLI 多值 fan-out：重复 --material-ids
    args = ["wm", "stock", "material"]
    for m in mids:
        args += ["--material-ids", m]
    cli = _cli(args)

    # 比成功 id 的聚合 items 集合（按 id 排序后逐位）。
    key = lambda r: (r.get("material_id"), r.get("id"))
    assert sorted(sdk, key=key) == sorted(cli, key=key), "fan-out 聚合 items 应一致"
