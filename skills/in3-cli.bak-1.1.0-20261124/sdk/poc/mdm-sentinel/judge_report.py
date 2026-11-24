# -*- coding: utf-8 -*-
"""判读层（ADR-0001 的"判"侧）：读 mdm_sentinel 产出的 shortlist JSON →
策展分优先级 + 执行简报 → Sourcing 可直接用的分组 HTML。不碰 API，可反复迭代。

跑法：python3 judge_report.py <shortlist.json> [out.html]
真实定时运行里这一步由 agent 执行（见 PROMPT.md）；本脚本是其确定性骨架，
agent 可在此基础上补人话叙述/误报研判。
"""
import html as _html
import json
import sys
from datetime import datetime, timezone

SECONDARY_SHOW = 25  # 价格离散非包装类只展前 N 条（其余计数）


def categorize(x):
    pack = (x.get("pack") or {}).get("qty")
    cause = x.get("cause") or ""
    if x["tier"] == "高度疑似" and cause.startswith("包装单位错配"):
        return "P0 确诊·包装单位错配"
    if x["tier"] == "高度疑似" and pack:
        return "P1 强疑似·包装类"
    if pack:
        return "P2 低优先·包装规格存疑"
    return "P3 价格离散·非包装（次级，不同口径核查）"


ORDER = ["P0 确诊·包装单位错配", "P1 强疑似·包装类", "P2 低优先·包装规格存疑",
         "P3 价格离散·非包装（次级，不同口径核查）"]


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "mdm_report_shortlist.json"
    out = sys.argv[2] if len(sys.argv) > 2 else "mdm_sourcing_report.html"
    data = json.load(open(src, encoding="utf-8"))
    groups = {k: [] for k in ORDER}
    for x in data:
        groups[categorize(x)].append(x)

    n_p0, n_p1 = len(groups[ORDER[0]]), len(groups[ORDER[1]])
    n_p3 = len(groups[ORDER[3]])
    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")

    # 执行简报（确定性生成；定时运行里 agent 可改写成更精炼的人话）
    p0_names = "、".join(f'{x["material_no"]}' for x in groups[ORDER[0]][:6])
    brief = (
        f"本期巡检命中 <b>{len(data)}</b> 条疑似。其中 <b class=hl>{n_p0} 条确诊「包装单位错配」</b>"
        f"（价差≈包装规格，含引爆本次的扎带 EL00556），已给出建议纠正 PCS 单价，"
        f"<b>建议 Sourcing 立即核对并统一价格记录单位</b>：{_html.escape(p0_names)}。"
        f"另 {n_p1} 条包装类强疑似（有包装规格 + 极端价差，需核高价记录是否按包/盒录入）；"
        f"{n_p3} 条为「价格离散·非包装」次级项（同料价差≥10×但无包装规格，属另一类口径/录入问题，"
        f"建议抽查极端值，不在本次包装单位整改范围）。"
    )

    css = """body{font-family:-apple-system,'PingFang SC',sans-serif;margin:0;background:#f5f7fa;color:#1f2937}
.hero{background:linear-gradient(135deg,#1e3a8a,#2563eb);color:#fff;padding:26px 36px}
.hero h1{margin:0;font-size:21px}.hero .sub{opacity:.85;font-size:12.5px;margin-top:5px}
.brief{margin:18px 36px;padding:16px 20px;background:#fff;border-left:4px solid #2563eb;border-radius:8px;font-size:13.5px;line-height:1.7;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.brief .hl{color:#dc2626}
h2{margin:26px 36px 6px;font-size:15px}h2 .c{font-size:12px;color:#6b7280;font-weight:400}
table{width:calc(100% - 72px);margin:6px 36px 10px;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.06)}
th,td{padding:8px 11px;text-align:left;font-size:12.5px;border-bottom:1px solid #f1f1f1;vertical-align:top}
th{background:#f8fafc;color:#475569;font-weight:600}
.p0 td:first-child{box-shadow:inset 3px 0 #dc2626}.p1 td:first-child{box-shadow:inset 3px 0 #f59e0b}
.num{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
.act{color:#b91c1c;font-weight:600}.note{color:#374151}.more{margin:0 36px 30px;color:#9ca3af;font-size:12px}"""

    def rows_html(items, cls):
        out = []
        for i, x in enumerate(items, 1):
            pk = (x.get("pack") or {}).get("qty") or "—"
            rt = f'{x["ratio"]:.0f}×' if x.get("ratio") else "—"
            pr = f'{x["price_min"]:.4f}~{x["price_max"]:.4f}' if x.get("price_min") is not None else "—"
            out.append(
                f'<tr class="{cls}"><td>{i}</td><td>{_html.escape(str(x["material_no"]))}</td>'
                f'<td>{_html.escape(str(x.get("name") or "")[:22])}</td><td class=num>{pk}</td>'
                f'<td class=num>{rt}</td><td class=num>{pr}</td>'
                f'<td><b class=act>{_html.escape(x.get("cause") or "")}</b><br>'
                f'<span class=note>{_html.escape(x.get("note") or "")}</span></td></tr>')
        return "".join(out)

    th = "<tr><th>#</th><th>物料编号</th><th>物料名称</th><th>包装</th><th>价差</th><th>价格区间(未税)</th><th>根因 / 核验要点（建议动作）</th></tr>"
    sections = []
    for k in ORDER:
        items = groups[k]
        if not items:
            continue
        cls = "p0" if k.startswith("P0") else "p1" if k.startswith("P1") else ""
        shown = items if not k.startswith("P3") else items[:SECONDARY_SHOW]
        sec = f'<h2>{_html.escape(k)} <span class=c>（{len(items)} 条{"，展前 " + str(SECONDARY_SHOW) if len(items) > len(shown) else ""}）</span></h2>'
        sec += f"<table><thead>{th}</thead><tbody>{rows_html(shown, cls)}</tbody></table>"
        if len(items) > len(shown):
            sec += f'<p class=more>另 {len(items) - len(shown)} 条价格离散非包装项未展开（按价差降序，已在 shortlist JSON 中）。</p>'
        sections.append(sec)

    doc = f"""<!doctype html><html lang=zh><head><meta charset=utf-8><title>主数据巡检·Sourcing 核验单</title><style>{css}</style></head><body>
<div class=hero><h1>主数据巡检 · 采购单价异常 · Sourcing 核验单</h1>
<div class=sub>tenant=indx · {now} · rule#1 单价异常（信号 C 包装规格 + P 价格离散；Q 数量待 PO 权限）· 确定性脚本算 → 判读层策展（ADR-0001）</div></div>
<div class=brief>{brief}</div>
{''.join(sections)}
<p class=more>说明：本核验单为只读快照。「建议纠正 PCS 单价」=最高价÷包装规格，供 Sourcing 核对依据；最终以人工核验为准，确认后统一更新价格记录单位口径。</p>
</body></html>"""
    open(out, "w", encoding="utf-8").write(doc)
    print(f"分组：" + " / ".join(f"{k.split('·')[0].strip()}:{len(groups[k])}" for k in ORDER))
    print(f"Sourcing 核验单: {out}")


if __name__ == "__main__":
    main()
