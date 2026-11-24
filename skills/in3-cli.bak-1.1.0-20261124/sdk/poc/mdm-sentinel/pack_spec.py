# -*- coding: utf-8 -*-
"""包装规格抽取器（mdm-sentinel 信号 C 的命门）。

从物料名称/描述里抠"每包多少个"的 PCS 数，如 `250根/包`→250、`1000个/包`→1000。
田野基线（《疑似PCS包装单位异常物料分析结果.xlsx》）只认"个/包"，全表干净数值
仅 5/3580；扎带"250根/包"因 `根` 漏抠被降级——本抽取器覆盖全 item-unit 词表修掉它。

纯函数、无外部依赖，可被 mdm_sentinel.py 调用，也可单测。
"""
import re
import unicodedata

# 被数的物品单位（"每包 N〔此〕"里的 N 单位）——田野只覆盖了"个"，这里补全。
ITEM_UNITS = "根个只支条片米卷对套双颗粒块张件枚把芯节组列册本张盘圈管"
# 包装容器单位（"/包"的分母）。
CONTAINERS = "包袋盒卷桶箱板排捆扎盘圈管罐瓶束"

# PCS/pcs 作为 item-unit 的特例（多字符，单列）。
_PCS = r"(?:PCS|pcs|Pcs|pc|个)"

# 主模式：<数字><item-unit>/<container>   例：250根/包、1000个/包、1000PCS/包、100米/卷
# item-unit 必需——裸"数字/包"多为型号尾数粘连（如 SJ-5100100/包），交低置信兜底。
_P_SLASH = re.compile(
    rf"(\d+(?:\.\d+)?)\s*(?:{_PCS}|[{ITEM_UNITS}])\s*[/／]\s*([{CONTAINERS}])"
)
# "一"代替斜杠：1000个一包
_P_YI = re.compile(
    rf"(\d+(?:\.\d+)?)\s*(?:{_PCS}|[{ITEM_UNITS}])\s*一\s*([{CONTAINERS}])"
)
# 前置容器：每包1000个 / 每包1000
_P_EACH = re.compile(
    rf"每\s*([{CONTAINERS}])\s*(\d+(?:\.\d+)?)\s*(?:{_PCS}|[{ITEM_UNITS}])?"
)


def _norm(s):
    if s is None:
        return ""
    # NBSP(\xa0) → 空格；全角数字/斜杠 → 半角；去多余空白
    s = unicodedata.normalize("NFKC", str(s)).replace("\xa0", " ")
    return s


def extract_pack_spec(name=None, desc=None):
    """返回 dict 或 None。

    dict: {qty:int, container:str, matched:str, source:str, confidence:str}
      qty        每包件数（信号 Q 整除判断 / 信号 C 确诊的核心）
      confidence 高=有数字+容器；低=仅容器词无数字（无法用于整除）
    """
    name_n, desc_n = _norm(name), _norm(desc)
    # 描述优先（包装规格通常写在描述尾部），名称兜底
    for src, text in (("desc", desc_n), ("name", name_n)):
        if not text:
            continue
        for pat in (_P_SLASH, _P_YI):
            m = pat.search(text)
            if m:
                qty = float(m.group(1))
                if qty >= 2:  # "1/包"无意义，过滤
                    return {
                        "qty": int(qty) if qty == int(qty) else qty,
                        "container": m.group(2),
                        "matched": m.group(0).strip(),
                        "source": src,
                        "confidence": "高",
                    }
        m = _P_EACH.search(text)
        if m and float(m.group(2)) >= 2:
            qty = float(m.group(2))
            return {
                "qty": int(qty) if qty == int(qty) else qty,
                "container": m.group(1),
                "matched": m.group(0).strip(),
                "source": src,
                "confidence": "高",
            }
    # 仅有容器词、无数字 → 低置信（对应田野"仅包装单位 R003"）。
    # 注意不匹配通用词"包装"——只认 "/包"、"每包" 这类真容器锚点。
    for src, text in (("desc", desc_n), ("name", name_n)):
        for c in CONTAINERS:
            if re.search(rf"[/／]\s*{c}|每{c}", text):
                return {"qty": None, "container": c, "matched": c,
                        "source": src, "confidence": "低"}
    return None
