#!/usr/bin/env python3
"""
IN3 物料重复检查分析脚本
分析物料主数据，生成可疑重复物料 Excel 报告
"""

import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from collections import defaultdict
import re
import difflib
from datetime import datetime

INPUT_FILE = '/Users/zhangdongfang/.openclaw/workspace-in3bot/物料主数据导出结果-20260905193855382.xlsx'
OUTPUT_FILE = f'/Users/zhangdongfang/.openclaw/workspace-in3bot/可疑重复物料_{datetime.now().strftime("%Y%m%d")}.xlsx'

# 关键列索引 (0-based)
COL_ID = 0          # 物料ID
COL_CODE = 1        # 物料编号
COL_NAME = 5        # 物料名称
COL_DESC = 6        # 物料描述
COL_CATEGORY = 8    # 物料类别
COL_SUBCAT = 10     # 物料子类别
COL_MFR = 12        # 制造商
COL_SOURCE = 13     # 物料来源
COL_UNIT = 21       # 主计量单位
COL_LEADTIME = 17   # 提前期
COL_PRICE = 60      # 标准价格
COL_CREATOR = 69    # 创建人
COL_CDATE = 71      # 创建日期
COL_MODIFIER = 73   # 最近修改人
COL_MDATE = 75      # 最近修改日期

print("=" * 60)
print("IN3 物料重复检查分析")
print("=" * 60)

# Step 1: 数据加载
print("\n[Step 1] 加载物料数据...")
wb = openpyxl.load_workbook(INPUT_FILE)
ws = wb['物料主数据']

# 读取表头
headers = [cell.value for cell in ws[1]]
total_cols = len(headers)
print(f"  列数: {total_cols}")

# 读取所有数据行
materials = []
for row in ws.iter_rows(min_row=2, values_only=True):
    if row[COL_CODE] is None and row[COL_NAME] is None:
        continue
    materials.append(list(row))

print(f"  总物料数: {len(materials)}")
wb.close()

# Step 2: 按物料名称分组
print("\n[Step 2] 按物料名称分组...")
name_groups = defaultdict(list)
for mat in materials:
    name = str(mat[COL_NAME] or '').strip()
    if name:
        name_groups[name].append(mat)

print(f"  不同物料名称数: {len(name_groups)}")
multi_groups = {k: v for k, v in name_groups.items() if len(v) > 1}
print(f"  有重复名称的组数: {len(multi_groups)}")

# 排除规则函数
def check_exclude_rules(desc_a, desc_b, name_a, name_b, mfr_a, mfr_b):
    """
    检查是否应该排除（非重复）
    返回 (is_excluded: bool, reason: str)
    """
    da = str(desc_a or '').strip()
    db = str(desc_b or '').strip()
    ma = str(mfr_a or '').strip()
    mb = str(mfr_b or '').strip()

    if da == db:
        return False, ""

    # 1. 甲供件
    if '甲供' in da or '甲供' in db:
        return True, "甲供件"

    # 2. 制造商完全不同（都有的情况下）
    if ma and mb:
        # 简化比较：去掉常见前缀后缀
        def normalize_mfr(m):
            m = re.sub(r'有限公司|股份|集团|公司|科技|电气|设备', '', m)
            return m.strip()
        nma = normalize_mfr(ma)
        nmb = normalize_mfr(mb)
        # 检查是否一个包含另一个（处理简称）
        if nma and nmb and nma != nmb:
            if nma not in nmb and nmb not in nma:
                return True, f"制造商不同: {ma} vs {mb}"

    # 3. 制造商一有一无
    if (ma and not mb) or (mb and not ma):
        return True, f"制造商一有一无: {ma} vs {mb}"

    # 4. 安装方向不同
    directions = ['左操', '右操', '上进', '下进', '上进下出', '下进上出', '前接线', '后接线',
                  '上进线', '下进线', '上进上出', '下进下出', '板前', '板后', '插入式',
                  '上进出', '下进出']
    dir_in_a = [d for d in directions if d in da]
    dir_in_b = [d for d in directions if d in db]
    if dir_in_a and dir_in_b and dir_in_a != dir_in_b:
        return True, f"安装方向不同: {dir_in_a} vs {dir_in_b}"

    # 5. 断路器分断能力不同 (kA)
    ka_a = re.findall(r'(\d+(?:\.\d+)?)\s*kA', da, re.IGNORECASE)
    ka_b = re.findall(r'(\d+(?:\.\d+)?)\s*kA', db, re.IGNORECASE)
    if ka_a and ka_b and sorted(ka_a) != sorted(ka_b):
        return True, f"分断能力不同: {ka_a} vs {ka_b} kA"

    # 6. 脱扣曲线不同
    curves = ['C型', 'D型', 'K型', 'B型', 'A型', 'C曲线', 'D曲线', 'K曲线', 'B曲线']
    curve_a = [c for c in curves if c in da]
    curve_b = [c for c in curves if c in db]
    if curve_a and curve_b and curve_a != curve_b:
        return True, f"脱扣曲线不同: {curve_a} vs {curve_b}"

    # 7. 极数不同
    poles_pattern = r'(\d+P|\d+[Pp]|单极|双极|三极|四极|1P|2P|3P|4P|1p|2p|3p|4p)'
    poles_a = re.findall(poles_pattern, da, re.IGNORECASE)
    poles_b = re.findall(poles_pattern, db, re.IGNORECASE)
    if poles_a and poles_b and set(p.upper() for p in poles_a) != set(p.upper() for p in poles_b):
        return True, f"极数不同: {poles_a} vs {poles_b}"

    # 8. 颜色不同
    color_pattern = r'(RAL\d{3,4}|[\u4e00-\u9fff]*(?:红|蓝|绿|黄|白|黑|灰|橙|紫|银|金)色?)'
    colors_a = re.findall(color_pattern, da)
    colors_b = re.findall(color_pattern, db)
    if colors_a and colors_b and set(colors_a) != set(colors_b):
        return True, f"颜色不同: {colors_a} vs {colors_b}"

    # 9. 漏电类型不同
    rcd_types = ['AC型', 'A型', 'A-SI型', 'B型', 'F型']
    rcd_a = [t for t in rcd_types if t in da]
    rcd_b = [t for t in rcd_types if t in db]
    if rcd_a and rcd_b and rcd_a != rcd_b:
        return True, f"漏电类型不同: {rcd_a} vs {rcd_b}"

    # 10. 带附件vs不带
    accessories = ['OF', 'AX', '欠压', '分励', '辅助', '报警', 'MX', 'MN', 'SD', 'ATMT',
                   'OF辅助', 'SD报警', '附件']
    acc_a = [a for a in accessories if a in da]
    acc_b = [a for a in accessories if a in db]
    # 一个有附件一个没有
    if (acc_a and not acc_b) or (acc_b and not acc_a):
        return True, f"带附件vs不带: {acc_a} vs {acc_b}"

    # 11. 互感器差异 - 变比
    ct_pattern = r'(\d+)\s*/\s*(\d+)'
    ct_a = re.findall(ct_pattern, da)
    ct_b = re.findall(ct_pattern, db)
    if ct_a and ct_b and set(ct_a) != set(ct_b):
        return True, f"互感器变比不同: {ct_a} vs {ct_b}"

    # 12. 电线类型不同
    wire_types = ['YJV', 'BVR', 'RVV', 'RVVP', 'BV', 'RVS', 'RV', 'KVV', 'KVVP',
                  'YJLV', 'VV', 'WDZ', 'NH', 'ZR', 'WDZN']
    wire_a = [w for w in wire_types if w in da]
    wire_b = [w for w in wire_types if w in db]
    if wire_a and wire_b and wire_a != wire_b:
        return True, f"电线类型不同: {wire_a} vs {wire_b}"

    # 13. 保护类型不同 (IP等级)
    ip_pattern = r'IP\d+[A-Z]?'
    ip_a = re.findall(ip_pattern, da, re.IGNORECASE)
    ip_b = re.findall(ip_pattern, db, re.IGNORECASE)
    if ip_a and ip_b and set(ip_a) != set(ip_b):
        return True, f"IP等级不同: {ip_a} vs {ip_b}"

    # 14. 螺纹方向
    if ('左旋' in da and '右旋' in db) or ('右旋' in da and '左旋' in db):
        return True, "螺纹方向不同: 左旋 vs 右旋"

    # 15. 版本号不同
    ver_pattern = r'V(\d+)'
    ver_a = re.findall(ver_pattern, da, re.IGNORECASE)
    ver_b = re.findall(ver_pattern, db, re.IGNORECASE)
    if ver_a and ver_b and ver_a != ver_b:
        return True, f"版本号不同: V{ver_a} vs V{ver_b}"

    # 16. 脱扣方式不同
    trip_types = ['热磁式', '电子式']
    trip_a = [t for t in trip_types if t in da]
    trip_b = [t for t in trip_types if t in db]
    if trip_a and trip_b and trip_a != trip_b:
        return True, f"脱扣方式不同: {trip_a} vs {trip_b}"

    # 17. 脱扣单元不同 (TMF值)
    tmf_pattern = r'TMF[\d.]*D?'
    tmf_a = re.findall(tmf_pattern, da, re.IGNORECASE)
    tmf_b = re.findall(tmf_pattern, db, re.IGNORECASE)
    if tmf_a and tmf_b and set(tmf_a) != set(tmf_b):
        return True, f"脱扣单元不同: {tmf_a} vs {tmf_b}"

    # 18. 配件差异
    if ('配件' in da or '附件' in da or '端子' in da or '接线端' in da) and \
       ('配件' in db or '附件' in db or '端子' in db or '接线端' in db):
        # 提取具体型号
        model_a = re.sub(r'.*?(配件|附件|端子|接线端)', '', da).strip()
        model_b = re.sub(r'.*?(配件|附件|端子|接线端)', '', db).strip()
        if model_a and model_b and model_a != model_b:
            return True, f"配件差异: {model_a} vs {model_b}"

    # 19. 型号系列不同
    # 提取型号前缀（字母部分）
    model_prefix_a = re.match(r'^([A-Za-z]+[\d]?)', da)
    model_prefix_b = re.match(r'^([A-Za-z]+[\d]?)', db)
    if model_prefix_a and model_prefix_b:
        pa = model_prefix_a.group(1).upper()
        pb = model_prefix_b.group(1).upper()
        if pa != pb and len(pa) >= 3 and len(pb) >= 3:
            return True, f"型号系列不同: {pa} vs {pb}"

    # 20. 材质不同
    materials_list = ['铜', '铝', '不锈钢', '镀锌', '紫铜', '黄铜', '铝合金']
    mat_a = [m for m in materials_list if m in da]
    mat_b = [m for m in materials_list if m in db]
    if mat_a and mat_b and mat_a != mat_b:
        return True, f"材质不同: {mat_a} vs {mat_b}"

    # 21-22. 额定电气参数不同 (额定电流、额定电压)
    # 提取电流值
    current_pattern = r'(\d+(?:\.\d+)?)\s*A(?!\w)'
    cur_a = re.findall(current_pattern, da)
    cur_b = re.findall(current_pattern, db)
    if cur_a and cur_b and sorted(float(x) for x in cur_a) != sorted(float(x) for x in cur_b):
        return True, f"额定电流不同: {cur_a}A vs {cur_b}A"

    # 提取电压值
    voltage_pattern = r'(\d+(?:\.\d+)?)\s*V(?!\w)'
    vol_a = re.findall(voltage_pattern, da)
    vol_b = re.findall(voltage_pattern, db)
    if vol_a and vol_b and sorted(float(x) for x in vol_a) != sorted(float(x) for x in vol_b):
        return True, f"额定电压不同: {vol_a}V vs {vol_b}V"

    # 23. 型号编码位不同
    # 简化：如果两个描述中的数字序列差异很大
    nums_a = re.findall(r'\d+', da)
    nums_b = re.findall(r'\d+', db)
    if nums_a and nums_b:
        # 计算共同数字比例
        common = set(nums_a) & set(nums_b)
        all_nums = set(nums_a) | set(nums_b)
        if all_nums and len(common) / len(all_nums) < 0.3 and len(all_nums) >= 3:
            return True, f"型号编码差异大: {nums_a} vs {nums_b}"

    # 24. 接线方式不同
    wiring = ['板前接线', '板后接线', '插入式', '固定式', '抽屉式']
    wire_a = [w for w in wiring if w in da]
    wire_b = [w for w in wiring if w in db]
    if wire_a and wire_b and wire_a != wire_b:
        return True, f"接线方式不同: {wire_a} vs {wire_b}"

    # 25. 通讯功能不同
    comm = ['RS485', '通讯', 'Modbus', '通讯模块', '通讯接口']
    comm_a = [c for c in comm if c in da]
    comm_b = [c for c in comm if c in db]
    if (comm_a and not comm_b) or (comm_b and not comm_a):
        return True, f"通讯功能不同: {comm_a} vs {comm_b}"

    # 26. DI/DO配置不同
    dio_pattern = r'(\d+)\s*(?:DI|DO|AI|AO)'
    dio_a = re.findall(dio_pattern, da, re.IGNORECASE)
    dio_b = re.findall(dio_pattern, db, re.IGNORECASE)
    if dio_a and dio_b and sorted(dio_a) != sorted(dio_b):
        return True, f"DI/DO配置不同: {dio_a} vs {dio_b}"

    # 27. 手车式/固定式
    mount = ['手车式', '固定式', '抽出式']
    mount_a = [m for m in mount if m in da]
    mount_b = [m for m in mount if m in db]
    if mount_a and mount_b and mount_a != mount_b:
        return True, f"安装方式不同: {mount_a} vs {mount_b}"

    # 28. 电抗器参数不同
    react_pattern = r'(\d+(?:\.\d+)?)\s*%?'
    # 电抗率
    rate_a = re.findall(r'电抗率\s*(\d+(?:\.\d+)?)\s*%', da)
    rate_b = re.findall(r'电抗率\s*(\d+(?:\.\d+)?)\s*%', db)
    if rate_a and rate_b and rate_a != rate_b:
        return True, f"电抗率不同: {rate_a}% vs {rate_b}%"

    # 29. 接触器类型不同 (AC/DC线圈)
    if ('AC' in da and 'DC' in db) or ('DC' in da and 'AC' in db):
        # 避免误判AC/DC电压
        if not ('交流' in da or '直流' in da):
            pass  # 可能只是电压标注
    coil_a = re.findall(r'(AC|DC)\s*(?:线圈|操作|控制)', da, re.IGNORECASE)
    coil_b = re.findall(r'(AC|DC)\s*(?:线圈|操作|控制)', db, re.IGNORECASE)
    if coil_a and coil_b and coil_a != coil_b:
        return True, f"接触器线圈类型不同: {coil_a} vs {coil_b}"

    # 30. 变频器功率不同
    power_pattern = r'(\d+(?:\.\d+)?)\s*(?:kW|KW)'
    pwr_a = re.findall(power_pattern, da, re.IGNORECASE)
    pwr_b = re.findall(power_pattern, db, re.IGNORECASE)
    if pwr_a and pwr_b and sorted(float(x) for x in pwr_a) != sorted(float(x) for x in pwr_b):
        return True, f"功率不同: {pwr_a}kW vs {pwr_b}kW"

    # 额外规则：功率不同
    power2_pattern = r'(\d+(?:\.\d+)?)\s*(?:kW|KW|W)'
    pw2_a = re.findall(power2_pattern, da, re.IGNORECASE)
    pw2_b = re.findall(power2_pattern, db, re.IGNORECASE)
    if pw2_a and pw2_b:
        sorted_a = sorted(float(x) for x in pw2_a)
        sorted_b = sorted(float(x) for x in pw2_b)
        if sorted_a != sorted_b:
            return True, f"功率不同: {pw2_a} vs {pw2_b}"

    return False, ""


def calc_similarity(s1, s2):
    """计算两个字符串的相似度"""
    if not s1 or not s2:
        return 0.0
    return difflib.SequenceMatcher(None, s1, s2).ratio()


def find_differences(desc_a, desc_b):
    """找出两个描述之间的差异"""
    da = str(desc_a or '').strip()
    db = str(desc_b or '').strip()
    if da == db:
        return "描述完全相同"

    diffs = []
    # 用 difflib 找出差异
    matcher = difflib.SequenceMatcher(None, da, db)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'replace':
            diffs.append(f"[{da[i1:i2]}→{db[j1:j2]}]")
        elif tag == 'delete':
            diffs.append(f"[-{da[i1:i2]}]")
        elif tag == 'insert':
            diffs.append(f"[+{db[j1:j2]}]")

    return ' '.join(diffs) if diffs else "有差异但无法精确定位"


# Step 3: 候选对筛选与排除规则应用
print("\n[Step 3] 候选对筛选与排除规则应用...")

confirmed_duplicates = []  # 确认重复
suspected_duplicates = []  # 可疑重复
excluded_count = 0
total_pairs_checked = 0

for idx, (name, group) in enumerate(multi_groups.items()):
    if (idx + 1) % 500 == 0:
        print(f"  处理进度: {idx + 1}/{len(multi_groups)} 组...")

    n = len(group)
    if n > 100:
        # 组太大，只比较描述最接近的前20对
        # 先计算所有两两描述相似度
        desc_list = [str(m[COL_DESC] or '') for m in group]
        candidates = []
        for i in range(n):
            for j in range(i + 1, n):
                sim = calc_similarity(desc_list[i], desc_list[j])
                candidates.append((sim, i, j))
        candidates.sort(reverse=True)
        top_pairs = [(i, j) for _, i, j in candidates[:20]]
    else:
        top_pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]

    for i, j in top_pairs:
        mat_a = group[i]
        mat_b = group[j]
        desc_a = str(mat_a[COL_DESC] or '').strip()
        desc_b = str(mat_b[COL_DESC] or '').strip()
        name_a = str(mat_a[COL_NAME] or '').strip()
        name_b = str(mat_b[COL_NAME] or '').strip()
        mfr_a = str(mat_a[COL_MFR] or '').strip()
        mfr_b = str(mat_b[COL_MFR] or '').strip()

        total_pairs_checked += 1

        if desc_a == desc_b:
            # 描述完全相同 → 确认重复
            diff_desc = "描述完全相同"
            confirmed_duplicates.append({
                'mat_a': mat_a, 'mat_b': mat_b,
                'diff': diff_desc, 'note': '描述完全相同'
            })
        else:
            # 计算相似度
            sim = calc_similarity(desc_a, desc_b)
            if sim < 0.5:
                continue  # 相似度太低，跳过

            # 应用排除规则
            is_excluded, reason = check_exclude_rules(desc_a, desc_b, name_a, name_b, mfr_a, mfr_b)

            diff_desc = find_differences(desc_a, desc_b)

            if is_excluded:
                excluded_count += 1
            else:
                # 无法排除 → 可疑重复
                suspected_duplicates.append({
                    'mat_a': mat_a, 'mat_b': mat_b,
                    'diff': diff_desc, 'note': f'相似度{sim:.1%}' + (f'; {reason}' if reason else '')
                })

print(f"  总检查对数: {total_pairs_checked}")
print(f"  排除对数: {excluded_count}")
print(f"  确认重复: {len(confirmed_duplicates)}")
print(f"  可疑重复: {len(suspected_duplicates)}")

# Step 4: 生成 Excel
print("\n[Step 4] 生成 Excel 报告...")

out_wb = openpyxl.Workbook()

# 样式定义
blue_fill = PatternFill(start_color='E8F0FE', end_color='E8F0FE', fill_type='solid')
orange_fill = PatternFill(start_color='FFF3E0', end_color='FFF3E0', fill_type='solid')
red_font = Font(color='FF0000', bold=False)
header_font = Font(bold=True, size=11)
header_fill = PatternFill(start_color='D9E1F2', end_color='D9E1F2', fill_type='solid')
thin_border = Border(
    left=Side(style='thin'),
    right=Side(style='thin'),
    top=Side(style='thin'),
    bottom=Side(style='thin')
)

HEADERS = ['物料编号A', '物料名称A', '物料描述A', '类别A', '子类别A', '制造商A', '单位A',
           '物料编号B', '物料名称B', '物料描述B', '类别B', '子类别B', '制造商B', '单位B',
           '差异说明', '备注']

DESC_COL_WIDTH = 50


def write_sheet(ws, data, sheet_name):
    """写入一个 sheet"""
    ws.title = sheet_name

    # 写表头
    for col_idx, header in enumerate(HEADERS, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = thin_border
        cell.alignment = Alignment(horizontal='center', vertical='center')

    # 写数据
    for row_idx, item in enumerate(data):
        mat_a = item['mat_a']
        mat_b = item['mat_b']
        row_num = row_idx * 2 + 2  # A/B交替行

        # A 行 (蓝色)
        fill_a = blue_fill
        row_a = [
            str(mat_a[COL_CODE] or ''),
            str(mat_a[COL_NAME] or ''),
            str(mat_a[COL_DESC] or ''),
            str(mat_a[COL_CATEGORY] or ''),
            str(mat_a[COL_SUBCAT] or ''),
            str(mat_a[COL_MFR] or ''),
            str(mat_a[COL_UNIT] or ''),
            '', '', '', '', '', '', '',
            item['diff'],
            item['note']
        ]
        for col_idx, val in enumerate(row_a, 1):
            cell = ws.cell(row=row_num, column=col_idx, value=val)
            cell.fill = fill_a
            cell.border = thin_border
            cell.alignment = Alignment(vertical='center', wrap_text=True)
            # 差异说明列红色字体
            if col_idx == 15:  # 差异说明
                cell.font = red_font

        # B 行 (橙色)
        fill_b = orange_fill
        row_b = [
            '', '', '', '', '', '', '',
            str(mat_b[COL_CODE] or ''),
            str(mat_b[COL_NAME] or ''),
            str(mat_b[COL_DESC] or ''),
            str(mat_b[COL_CATEGORY] or ''),
            str(mat_b[COL_SUBCAT] or ''),
            str(mat_b[COL_MFR] or ''),
            str(mat_b[COL_UNIT] or ''),
            '', ''
        ]
        for col_idx, val in enumerate(row_b, 1):
            cell = ws.cell(row=row_num + 1, column=col_idx, value=val)
            cell.fill = fill_b
            cell.border = thin_border
            cell.alignment = Alignment(vertical='center', wrap_text=True)

    # 设置列宽
    for col_idx in range(1, len(HEADERS) + 1):
        if col_idx in [3, 10]:  # 物料描述列
            ws.column_dimensions[get_column_letter(col_idx)].width = DESC_COL_WIDTH
        elif col_idx in [15, 16]:  # 差异说明、备注
            ws.column_dimensions[get_column_letter(col_idx)].width = 40
        else:
            ws.column_dimensions[get_column_letter(col_idx)].width = 15

    # 冻结窗格在 C3
    ws.freeze_panes = 'C3'


# 写 Sheet1 - 确认重复
ws1 = out_wb.active
write_sheet(ws1, confirmed_duplicates, '确认重复')

# 写 Sheet2 - 可疑重复
ws2 = out_wb.create_sheet()
write_sheet(ws2, suspected_duplicates, '可疑重复')

out_wb.save(OUTPUT_FILE)

# 统计摘要
print("\n" + "=" * 60)
print("分析完成！统计摘要")
print("=" * 60)
print(f"总物料数: {len(materials)}")
print(f"不同物料名称数: {len(name_groups)}")
print(f"同名多物料组数: {len(multi_groups)}")
print(f"总检查对数: {total_pairs_checked}")
print(f"排除对数（非重复）: {excluded_count}")
print(f"确认重复对数: {len(confirmed_duplicates)}")
print(f"可疑重复对数: {len(suspected_duplicates)}")
print(f"")
print(f"输出文件: {OUTPUT_FILE}")
