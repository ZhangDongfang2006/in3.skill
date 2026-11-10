# -*- coding: utf-8 -*-
"""pack_spec 抽取器单测：硬断言关键 case + 对田野 3580 真实串做覆盖率回归。

跑法：python3 test_pack_spec.py
- 硬断言部分零外部依赖（durable）。
- 覆盖率 sweep 仅在 scratchpad/corpus.json 存在时跑（来自 dump_corpus.py）。
"""
import json
import os
import sys

from pack_spec import extract_pack_spec

# ---- 硬断言：来自田野 Excel 的真实串，含他漏掉的"根/包" ----
CASES = [
    # (name, desc, 期望 qty)  —— EL00556 是引爆本项目的扎带，田野抠成 None
    ("【电气辅材-批领】扎带黑色300",
     "易买优选,自锁式尼龙扎带\xa0YM5*300黑（国标）250根/包", 250),
    ("扎带", "易买优选,自锁式尼龙扎带\xa0YM3*100黑（国标）1000根/包", 1000),
    ("扎带", "易买优选,自锁式尼龙扎带\xa0YM3*150黑（国标）1000根/包，用量单位根", 1000),
    ("接线端子-针形2.5", "易买优选,导线面积2.5mm²长10mm针型端子\xa0\xa0YM-E2510红紫铜1000个/包", 1000),
    ("接线端子-Y形2.5", "易买优选,2.5mm²S叉型预绝缘端头红色护套YM-SV2-3.2红黄铜无焊缝1000个/包", 1000),
    ("安全压线帽", "M24881易买优选黄标 安全压线帽 CE-2X 1000个/包", 1000),
    # 全角斜杠 / PCS 单位 / 每包句式
    ("X", "某物料 100PCS/包", 100),
    ("X", "某物料 500只／袋", 500),
    ("X", "螺丝 每盒200个", 200),
]

# ---- 假阳性守卫：纯尺寸/无包装的串必须不抠出数字 ----
NEG_CASES = [
    ("加工铝型材II", "HGY-TPCA-03-10-10,6061合金,欧标双槽，槽宽8.2"),          # 纯尺寸
    ("端子", "导线面积0.5mm²长10mm针型端子 YM-E0510"),                          # 有 *数字 但无 /包
    ("型材", "YM5*300黑（国标）"),                                              # *300 不该被当包装数
]


def run_asserts():
    fails = []
    for name, desc, want in CASES:
        r = extract_pack_spec(name, desc)
        got = r["qty"] if r else None
        ok = got == want
        print(f"  {'✓' if ok else '✗'} want={want:<6} got={got!s:<6} matched={r['matched'] if r else None!r}  <= {desc[:40]!r}")
        if not ok:
            fails.append((desc, want, got))
    print("  --- 假阳性守卫（应为 None 或低置信无数字）---")
    for name, desc in NEG_CASES:
        r = extract_pack_spec(name, desc)
        got = r["qty"] if r else None
        ok = got is None
        print(f"  {'✓' if ok else '✗'} qty={got!s:<6} <= {desc[:45]!r}")
        if not ok:
            fails.append((desc, None, got))
    return fails


def run_sweep():
    here = os.path.dirname(os.path.abspath(__file__))
    # corpus.json 由 scratchpad/dump_corpus.py 生成
    candidates = [
        os.environ.get("CORPUS_JSON", ""),
        "/private/tmp/claude-501/-Users-shenchenjian-WorkSpace-ind-skills/5db11146-3e88-47e7-b277-1d01403562ad/scratchpad/corpus.json",
        os.path.join(here, "corpus.json"),
    ]
    path = next((p for p in candidates if p and os.path.exists(p)), None)
    if not path:
        print("\n[sweep 跳过] 未找到 corpus.json（运行 scratchpad/dump_corpus.py 生成）")
        return
    recs = json.load(open(path, encoding="utf-8"))
    n = len(recs)
    ye_qty = sum(1 for x in recs if x.get("ye_qty") is not None)        # 田野干净数值
    ye_text = sum(1 for x in recs if x.get("ye_text"))                  # 田野有包装文本
    my_hi = my_lo = 0
    won = []   # 田野=None 而我抠出了数字
    for x in recs:
        r = extract_pack_spec(x.get("name"), x.get("desc"))
        if r and r["qty"] is not None:
            my_hi += 1
            if x.get("ye_qty") is None:
                won.append((x["material_no"], r["qty"], r["matched"], x.get("desc")))
        elif r:
            my_lo += 1
    print(f"\n[sweep over {n} 真实串]")
    print(f"  田野 干净数值: {ye_qty}/{n}   (有包装文本: {ye_text})")
    print(f"  本抽取器 高置信(有数值): {my_hi}/{n}   低置信(仅容器): {my_lo}")
    print(f"  净赢(田野 None→我抠出): {len(won)} 条")
    for mno, qty, matched, desc in won[:12]:
        print(f"    [{mno}] {qty} <= {matched!r}  ({str(desc)[:38]})")


if __name__ == "__main__":
    print("=== 硬断言 ===")
    fails = run_asserts()
    run_sweep()
    if fails:
        print(f"\n❌ {len(fails)} 个断言失败")
        sys.exit(1)
    print("\n✅ 全部硬断言通过")
