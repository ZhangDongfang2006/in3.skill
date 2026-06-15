#!/usr/bin/env python3
"""
每日采购价格异常检查
- 读取宁波+湖北采购订单明细(当天导出的全量文件)
- 筛选当天下单的采购记录
- 与历史价格对比(该物料的历史采购均价)
- 偏差≥40%（仅正偏离/涨价）标记异常
- 输出Excel报告 + 关联项目信息 + 采购申请人
"""

import sys
import os
import re
from collections import defaultdict
from datetime import datetime, date
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

DATA_DIR = os.path.dirname(os.path.abspath(__file__))

# 列映射(IN3导出的采购订单明细)
COL = {
    'po': 2,           # 采购订单号 (0-indexed)
    'line': 3,         # 行号
    'contract_no': 9,  # 合同编号
    'contract_name': 10, # 合同名称
    'sales_no': 7,     # 销售订单编号
    'sales_name': 8,   # 销售订单名称
    'supplier_code': 11,
    'supplier': 12,    # 供应商名称
    'buyer': 15,       # 采购申请人
    'material_id': 16, # 物料编号
    'material_name': 17, # 物料名称
    'material_desc': 18, # 物料描述
    'qty': 32,         # 采购数量
    'price_with_tax': 42, # 含税单价
    'amount': 44,      # 价税合计
    'order_date': 49,  # 下单日期 (col49可能不对,需要确认)
}

# 实际列需要从文件动态读取
def find_columns(headers):
    """根据列名动态建立映射"""
    col_map = {}
    for i, h in enumerate(headers):
        h_str = str(h).strip() if h else ''
        if h_str == '采购订单号': col_map['po'] = i
        elif h_str == '合同编号': col_map['contract_no'] = i
        elif h_str == '合同名称': col_map['contract_name'] = i
        elif h_str == '销售订单编号': col_map['sales_no'] = i
        elif h_str == '销售订单名称': col_map['sales_name'] = i
        elif h_str == '供应商名称': col_map['supplier'] = i
        elif h_str == '采购申请人': col_map['buyer'] = i
        elif h_str == '物料编号': col_map['material_id'] = i
        elif h_str == '物料名称': col_map['material_name'] = i
        elif h_str == '物料描述': col_map['material_desc'] = i
        elif h_str == '采购数量': col_map['qty'] = i
        elif h_str == '含税单价': col_map['price_with_tax'] = i
        elif h_str == '价税合计': col_map['amount'] = i
        elif h_str == '下单时间' or h_str == '下单日期': col_map['order_date'] = i
    return col_map


def load_all_records(nb_file, hb_file):
    """读取宁波+湖北采购订单明细,返回全部记录"""
    all_records = []

    for filepath, factory in [(nb_file, '宁波'), (hb_file, '湖北')]:
        if not os.path.exists(filepath):
            print(f"  ⚠️ 文件不存在: {filepath}")
            continue

        wb = openpyxl.load_workbook(filepath)
        ws = wb.active

        headers = [cell.value for cell in ws[1]]
        col_map = find_columns(headers)

        count = 0
        for row in ws.iter_rows(min_row=2, values_only=True):
            vals = list(row)

            def get(key):
                idx = col_map.get(key)
                return vals[idx] if idx is not None and idx < len(vals) else None

            po = str(get('po') or '')
            if not po.startswith('PO'):
                continue

            material_id = str(get('material_id') or '')
            if not material_id:
                continue

            price = get('price_with_tax')
            try:
                price = float(price) if price else 0
            except (ValueError, TypeError):
                price = 0

            order_date = get('order_date')
            if order_date and hasattr(order_date, 'strftime'):
                order_date_str = order_date.strftime('%Y-%m-%d')
            else:
                order_date_str = str(order_date or '')

            qty = get('qty')
            try:
                qty = float(qty) if qty else 0
            except (ValueError, TypeError):
                qty = 0

            amount = get('amount')
            try:
                amount = float(amount) if amount else 0
            except (ValueError, TypeError):
                amount = 0

            record = {
                'factory': factory,
                'po': po,
                'material_id': material_id,
                'material_name': str(get('material_name') or ''),
                'material_desc': str(get('material_desc') or ''),
                'supplier': str(get('supplier') or ''),
                'buyer': str(get('buyer') or ''),
                'price': price,
                'qty': qty,
                'amount': amount,
                'order_date': order_date_str,
                'contract_no': str(get('contract_no') or ''),
                'contract_name': str(get('contract_name') or ''),
                'sales_no': str(get('sales_no') or ''),
                'sales_name': str(get('sales_name') or ''),
            }
            all_records.append(record)
            count += 1

        wb.close()
        print(f"  {factory}: {count} 条记录")

    return all_records


def analyze_daily(all_records, target_date, threshold=50):
    """
    筛选target_date的采购,与历史价格对比
    """
    target_str = target_date.strftime('%Y-%m-%d')

    recent = []  # 当天采购
    historical = defaultdict(list)  # 历史采购

    for rec in all_records:
        if rec['order_date'] == target_str:
            recent.append(rec)
        else:
            if rec['price'] > 0:
                historical[rec['material_id']].append(rec)

    print(f"\n当天采购 ({target_str}): {len(recent)} 条")
    print(f"历史采购: {sum(len(v) for v in historical.values())} 条, {len(historical)} 种物料")

    # 历史均价统计
    hist_stats = {}
    for mat_id, recs in historical.items():
        prices = [r['price'] for r in recs if r['price'] > 0]
        if not prices:
            continue
        sorted_prices = sorted(prices)
        hist_stats[mat_id] = {
            'avg': sum(prices) / len(prices),
            'median': sorted_prices[len(sorted_prices) // 2],
            'min': min(prices),
            'max': max(prices),
            'count': len(prices),
            'po_refs': '; '.join(
                f"{r['po']}(¥{r['price']:.2f},{r['order_date']})"
                for r in recs[:20]  # 最多20条
            ),
        }

    # 检测异常
    anomalies = []
    seen = set()

    for rec in recent:
        mat_id = rec['material_id']
        po = rec['po']
        price = rec['price']

        if price <= 0:
            continue

        # 去重:同PO+同物料
        key = (po, mat_id)
        if key in seen:
            continue
        seen.add(key)

        stats = hist_stats.get(mat_id)
        if not stats or stats['count'] < 1:
            continue  # 无历史价格,跳过

        avg = stats['avg']
        deviation = (price - avg) / avg * 100 if avg > 0 else 0

        # 只检测正偏离（涨价），忽略负偏离（降价）
        if deviation >= threshold and deviation > 0:
            # 严重程度
            if deviation >= 100:
                severity = '🔴 高'
            elif deviation >= 50:
                severity = '🟡 中'
            else:
                severity = '🟢 低'

            # 项目信息
            contract_name = rec.get('contract_name', '')
            contract_no = rec.get('contract_no', '')
            sales_name = rec.get('sales_name', '')
            parts = []
            if contract_name:
                parts.append(contract_name)
            if contract_no:
                parts.append(f"合同:{contract_no}")
            if sales_name and sales_name != contract_name:
                parts.append(f"销售订单:{sales_name}")
            project_info = ' | '.join(parts) if parts else '(无关联项目)'

            anomalies.append({
                '严重程度': severity,
                '采购订单号': po,
                '物料编号': mat_id,
                '物料名称': rec['material_name'],
                '规格描述': rec['material_desc'],
                '本次单价': price,
                '本次数量': rec['qty'],
                '本次金额': rec['amount'],
                '供应商': rec['supplier'],
                '下单时间': rec['order_date'],
                '历史均价': round(avg, 2),
                '历史中位价': round(stats['median'], 2),
                '历史最低': stats['min'],
                '历史最高': stats['max'],
                '历史笔数': stats['count'],
                '偏离幅度': f"{deviation:+.1f}%",
                '历史订单编号(备注)': stats['po_refs'],
                '工厂': rec['factory'],
                '采购申请人': rec.get('buyer', ''),
                '关联销售订单/项目信息': project_info,
            })

    # 按偏离幅度排序
    anomalies.sort(key=lambda x: float(x['偏离幅度'].replace('%', '').replace('+', '')), reverse=True)

    return anomalies


def export_excel(anomalies, output_path, target_date):
    """导出Excel"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"每日价格异常-{target_date.strftime('%Y%m%d')}"

    # 样式
    hdr_font = Font(bold=True, size=11, color="FFFFFF")
    hdr_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    red_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
    yellow_fill = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")
    yichang_fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
    border = Border(left=Side('thin'), right=Side('thin'), top=Side('thin'), bottom=Side('thin'))

    columns = [
        ('序号', 5), ('严重程度', 8), ('采购订单号', 22), ('物料编号', 14),
        ('物料名称', 25), ('规格描述', 35), ('本次单价', 10), ('本次数量', 10),
        ('本次金额', 12), ('供应商', 25), ('下单时间', 12),
        ('历史均价', 10), ('历史中位价', 10), ('历史最低', 10), ('历史最高', 10),
        ('历史笔数', 8), ('偏离幅度', 10),
        ('历史订单编号(备注)', 60),
        ('工厂', 12), ('采购申请人', 10), ('关联销售订单/项目信息', 50),
    ]

    for col_idx, (col_name, width) in enumerate(columns, 1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.font = hdr_font
        cell.fill = hdr_fill
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        cell.border = border
        ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = width

    for row_idx, a in enumerate(anomalies, 2):
        a['序号'] = row_idx - 1

        severity = a['严重程度']
        fill = red_fill if '高' in severity else (yellow_fill if '中' in severity else None)
        is_yichang = a['工厂'] == '湖北'

        row_data = [
            a['序号'], a['严重程度'], a['采购订单号'], a['物料编号'],
            a['物料名称'], a['规格描述'], a['本次单价'], a['本次数量'],
            a['本次金额'], a['供应商'], a['下单时间'],
            a['历史均价'], a['历史中位价'], a['历史最低'], a['历史最高'],
            a['历史笔数'], a['偏离幅度'], a['历史订单编号(备注)'],
            a['工厂'], a['采购申请人'], a['关联销售订单/项目信息'],
        ]

        for col_idx, val in enumerate(row_data, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.border = border
            cell.alignment = Alignment(vertical='center', wrap_text=True)
            if fill and col_idx <= 17:
                cell.fill = fill
            if is_yichang and col_idx >= 19:
                cell.fill = yichang_fill

    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = f"A1:U{ws.max_row}"
    wb.save(output_path)
    print(f"✅ 已导出: {output_path} ({len(anomalies)} 条)")


def find_latest_files():
    """找最新的宁波/湖北采购订单明细文件"""
    nb_file = None
    hb_file = None
    nb_date = ''
    hb_date = ''

    for f in os.listdir(DATA_DIR):
        # 匹配 采购订单明细-宁波-YYYYMMDD.xlsx 或 采购订单明细-宁波-YYYY-MM-DD.xlsx
        m = re.match(r'采购订单明细-宁波-(\d{8})\.xlsx$', f)
        if m:
            d = m.group(1)
            if d > nb_date:
                nb_date = d
                nb_file = os.path.join(DATA_DIR, f)
        m = re.match(r'采购订单明细-湖北-(\d{8})\.xlsx$', f)
        if m:
            d = m.group(1)
            if d > hb_date:
                hb_date = d
                hb_file = os.path.join(DATA_DIR, f)

    return nb_file, hb_file


def main():
    target_date = date.today()
    threshold = 40

    # 命令行参数: [YYYY-MM-DD] [threshold]
    if len(sys.argv) > 1:
        try:
            target_date = datetime.strptime(sys.argv[1], '%Y-%m-%d').date()
        except ValueError:
            pass
    if len(sys.argv) > 2:
        try:
            threshold = int(sys.argv[2])
        except ValueError:
            pass

    print(f"=== 每日采购价格异常检查 ===")
    print(f"检查日期: {target_date}")
    print(f"偏差阈值: ≥{threshold}%（仅正偏离）")

    # 找最新文件
    nb_file, hb_file = find_latest_files()
    print(f"\n数据文件:")
    print(f"  宁波: {os.path.basename(nb_file) if nb_file else '❌ 未找到'}")
    print(f"  湖北: {os.path.basename(hb_file) if hb_file else '❌ 未找到'}")

    if not nb_file and not hb_file:
        print("\n❌ 未找到任何采购订单明细文件,请先从IN3导出")
        sys.exit(1)

    # 加载数据
    print("\n加载数据...")
    all_records = load_all_records(nb_file or '', hb_file or '')

    if not all_records:
        print("❌ 无数据")
        sys.exit(1)

    # 分析
    anomalies = analyze_daily(all_records, target_date, threshold)

    if not anomalies:
        print(f"\n✅ {target_date} 无价格异常")
        return

    high = sum(1 for a in anomalies if '高' in a['严重程度'])
    mid = sum(1 for a in anomalies if '中' in a['严重程度'])
    print(f"\n异常分布: 🔴高 {high}, 🟡中 {mid}")

    print("\n--- 异常清单 ---")
    for a in anomalies:
        print(f"  {a['严重程度']} {a['采购订单号']} | {a['物料名称']} | ¥{a['本次单价']} vs 均价¥{a['历史均价']} ({a['偏离幅度']}) | {a['供应商'][:15]}")

    # 导出
    output = os.path.join(DATA_DIR, f'每日价格异常-{target_date.strftime("%Y%m%d")}.xlsx')
    export_excel(anomalies, output, target_date)

    # 输出摘要供 cron 任务使用
    print(f"\n[SUMMARY] {target_date}: {len(anomalies)} 条异常 (🔴{high} 🟡{mid})")
    print(f"[OUTPUT] {output}")


if __name__ == '__main__':
    main()
