#!/usr/bin/env python3
"""
IN3 物料重复检查 v3 - 完整版
"""
import pandas as pd
import numpy as np
import re
import json
import time
from difflib import SequenceMatcher
from collections import defaultdict

print(f"[{time.strftime('%H:%M:%S')}] 开始物料重复检查 v3...", flush=True)

# ====== 1. 读取数据 ======
INPUT_FILE = '物料主数据导出结果-20260905161742956.xlsx'
df = pd.read_excel(INPUT_FILE, sheet_name='物料主数据')
print(f"总物料数: {len(df)}, 列数: {len(df.columns)}", flush=True)

# ====== 2. 过滤 ======
# 排除成品柜、甲供件、半成品（这些一般不重复检查）
CATEGORIES_TO_CHECK = ['电器元件', '辅材', '结构件', '紧固件', '工、器具', '机械配件', 
                       '气动配件', '钢材原料', '外购成套', '通用件', '传动配件',
                       '管道配件', '其他', '特殊零件', '电机', '非金属原料', '风叶']
df_check = df[df['物料类别'].isin(CATEGORIES_TO_CHECK)].copy()
print(f"检查范围: {len(df_check)} 条物料（排除成品柜/甲供件/半成品 {len(df) - len(df_check)} 条）", flush=True)

# ====== 3. 数据清洗 ======
def clean_text(s):
    if pd.isna(s):
        return ''
    s = str(s).strip()
    s = s.replace('\u3000', '').replace('\xa0', '')
    s = re.sub(r'\s+', ' ', s)
    return s

df_check['_id'] = df_check['*物料编号'].apply(clean_text)
df_check['_name'] = df_check['*物料名称'].apply(clean_text)
df_check['_desc'] = df_check['*物料描述'].apply(clean_text)
df_check['_category'] = df_check['物料类别'].apply(clean_text)
df_check['_subcategory'] = df_check['物料子类别'].apply(clean_text)
df_check['_manufacturer'] = df_check['制造商'].apply(clean_text)
df_check['_source'] = df_check['*物料来源'].apply(lambda x: clean_text(x) if pd.notna(x) else '')
df_check['_unit'] = df_check['主计量单位'].apply(clean_text)

print(f"[{time.strftime('%H:%M:%S')}] 数据清洗完成", flush=True)

# ====== 4. 生成候选对 ======
print(f"[{time.strftime('%H:%M:%S')}] 筛选候选对...", flush=True)

# 策略：按物料名称分组，同名的物料之间比较描述
name_groups = defaultdict(list)
for idx in df_check.index:
    name = df_check.loc[idx, '_name']
    if name:
        name_groups[name].append(idx)

print(f"唯一物料名称数: {len(name_groups)}", flush=True)
multi_name_groups = {k: v for k, v in name_groups.items() if len(v) > 1}
print(f"有多个物料的名称组数: {len(multi_name_groups)}", flush=True)

# Step 1: 完全同名同描述
exact_dup_groups = defaultdict(list)
for name, indices in multi_name_groups.items():
    desc_map = defaultdict(list)
    for idx in indices:
        desc = df_check.loc[idx, '_desc']
        if desc:
            desc_map[desc].append(idx)
    for desc, idxs in desc_map.items():
        if len(idxs) > 1:
            exact_dup_groups[(name, desc)] = idxs

exact_pairs = []
for key, indices in exact_dup_groups.items():
    for i in range(len(indices)):
        for j in range(i+1, len(indices)):
            exact_pairs.append((indices[i], indices[j]))

print(f"同名同描述候选对数: {len(exact_pairs)}", flush=True)

# Step 2: 同名不同描述但高度相似（SequenceMatcher > 0.85），限制小组避免组合爆炸
similar_pairs = []
pair_set = set()
for name, indices in multi_name_groups.items():
    if len(indices) > 300:
        continue  # 太大的组跳过相似匹配
    descs = {}
    for idx in indices:
        desc = df_check.loc[idx, '_desc']
        if desc:
            descs[idx] = desc
    idx_list = list(descs.keys())
    for i in range(len(idx_list)):
        for j in range(i+1, len(idx_list)):
            d1, d2 = descs[idx_list[i]], descs[idx_list[j]]
            # 快速预检：长度差异太大直接跳过
            if abs(len(d1) - len(d2)) / max(len(d1), len(d2), 1) > 0.3:
                continue
            ratio = SequenceMatcher(None, d1, d2).ratio()
            if ratio > 0.85:
                pair = (min(idx_list[i], idx_list[j]), max(idx_list[i], idx_list[j]))
                if pair not in pair_set:
                    pair_set.add(pair)
                    similar_pairs.append(pair)

print(f"相似描述新增候选对数: {len(similar_pairs)}", flush=True)
all_pairs = exact_pairs + similar_pairs
print(f"总候选对数: {len(all_pairs)}", flush=True)

# ====== 5. 规则分类 ======
print(f"[{time.strftime('%H:%M:%S')}] 规则分类...", flush=True)

def get_row_data(idx):
    return {
        'id': df_check.loc[idx, '_id'],
        'name': df_check.loc[idx, '_name'],
        'desc': df_check.loc[idx, '_desc'],
        'category': df_check.loc[idx, '_category'],
        'subcategory': df_check.loc[idx, '_subcategory'],
        'manufacturer': df_check.loc[idx, '_manufacturer'],
        'source': df_check.loc[idx, '_source'],
        'unit': df_check.loc[idx, '_unit'],
    }

# 排除规则
EXCLUSION_RULES = []

def check_directional_diff(a, b):
    """安装方向不同"""
    dir_pairs = [
        ('左操', '右操'), ('左侧', '右侧'), ('左进', '右进'),
        ('上进', '下进'), ('上出', '下出'),
        ('左进线', '右进线'), ('上进线', '下进线'), ('上出线', '下出线'),
        ('平进平出', '平进侧出'), ('平进侧出', '平进平出'),
        ('上进上出', '上进下出'), ('上进下出', '上进上出'),
        ('下进下出', '下进上出'), ('下进上出', '下进下出'),
    ]
    for d1, d2 in dir_pairs:
        if (d1 in a['desc'] and d2 in b['desc']) or (d2 in a['desc'] and d1 in b['desc']):
            return f'安装方向不同({d1}/{d2})'
    return None

def check_breaker_grade(a, b):
    """断路器壳架等级后字母不同（分断能力不同）"""
    # CDM3-63F vs CDM3-63C, CDM3-125S vs CDM3-125H etc.
    grade_suffixes = {'F': '分断能力F', 'C': '分断能力C', 'D': '分断能力D', 
                      'H': '分断能力H', 'L': '分断能力L', 'M': '分断能力M',
                      'N': '分断能力N', 'S': '分断能力S', 'V': '分断能力V'}
    m_a = re.findall(r'(\d+)([A-Z])\b', a['desc'])
    m_b = re.findall(r'(\d+)([A-Z])\b', b['desc'])
    for (num_a, suf_a) in m_a:
        for (num_b, suf_b) in m_b:
            if num_a == num_b and suf_a in grade_suffixes and suf_b in grade_suffixes and suf_a != suf_b:
                return f'断路器分断能力等级不同({suf_a}/{suf_b})'
    return None

def check_trip_curve(a, b):
    """微型断路器脱扣曲线不同"""
    curves = ['B曲线', 'C曲线', 'D曲线', 'K曲线', 'Z曲线', 'B型', 'C型', 'D型', 'K型', 'Z型']
    for c in curves:
        in_a = c in a['desc'] or c in a['name']
        in_b = c in b['desc'] or c in b['name']
        if in_a != in_b:
            # 确认另一个也有曲线类型
            return f'脱扣曲线不同'
    return None

def check_poles(a, b):
    """极数不同"""
    pole_a = re.findall(r'(\d+)\s*[Pp]', a['desc'])
    pole_b = re.findall(r'(\d+)\s*[Pp]', b['desc'])
    if pole_a and pole_b and set(pole_a) != set(pole_b):
        return f'极数不同({",".join(sorted(set(pole_a)))}/{",".join(sorted(set(pole_b)))})'
    # 1N vs 1P+N 是同一极数不同表述，不算排除
    return None

def check_color(a, b):
    """颜色不同"""
    colors = ['红色', '蓝色', '绿色', '黄色', '白色', '黑色', '灰色', '橙色', '棕色', '紫色']
    for c in colors:
        in_a = c in a['desc'] or c in a['name']
        in_b = c in b['desc'] or c in b['name']
        if in_a != in_b:
            return f'颜色不同({c})'
    return None

def check_rcc_type(a, b):
    """漏电保护类型不同"""
    for lt in ['AC型', 'A型', 'F型', 'B型']:
        if (lt in a['desc']) != (lt in b['desc']):
            return f'漏电保护类型不同({lt})'
    return None

def check_accessory(a, b):
    """带附件vs不带"""
    accessories = ['失压', '辅助', '报警', '门框', '电磁锁', '分励', '合闸', '欠压']
    for acc in accessories:
        in_a = f'带{acc}' in a['desc'] or acc in a['desc']
        in_b = f'带{acc}' in b['desc'] or acc in b['desc']
        # 更精确：一个有附件一个没有
    # 简化：检查描述中"带"/"不带"差异
    if ('带' in a['desc'] and '不带' not in a['desc'] and '带' not in b['desc']):
        has_acc_a = any(acc in a['desc'] for acc in ['失压','辅助','报警','门框','电磁锁','分励','合闸','欠压','OF','SD','MN','MX','XF'])
        has_acc_b = any(acc in b['desc'] for acc in ['失压','辅助','报警','门框','电磁锁','分励','合闸','欠压','OF','SD','MN','MX','XF'])
        if has_acc_a and not has_acc_b:
            return f'带附件vs不带'
    if ('带' in b['desc'] and '不带' not in b['desc'] and '带' not in a['desc']):
        has_acc_a = any(acc in a['desc'] for acc in ['失压','辅助','报警','门框','电磁锁','分励','合闸','欠压','OF','SD','MN','MX','XF'])
        has_acc_b = any(acc in b['desc'] for acc in ['失压','辅助','报警','门框','电磁锁','分励','合闸','欠压','OF','SD','MN','MX','XF'])
        if has_acc_b and not has_acc_a:
            return f'带附件vs不带'
    return None

def check_ct_diff(a, b):
    """互感器差异"""
    ratio_a = re.findall(r'(\d+)/(\d+)', a['desc'])
    ratio_b = re.findall(r'(\d+)/(\d+)', b['desc'])
    if ratio_a and ratio_b and set(ratio_a) != set(ratio_b):
        return f'互感器变比不同({set(ratio_a)}/{set(ratio_b)})'
    # 窗口尺寸
    win_a = re.findall(r'(\d+)\s*[×xX*]\s*(\d+)', a['desc'])
    win_b = re.findall(r'(\d+)\s*[×xX*]\s*(\d+)', b['desc'])
    if win_a and win_b and set(tuple(sorted(map(int, w))) for w in win_a) != set(tuple(sorted(map(int, w))) for w in win_b):
        return f'互感器窗口尺寸不同'
    # 精度等级
    prec_a = re.findall(r'(\d+(?:\.\d+)?)\s*[Ss]级', a['desc'])
    prec_b = re.findall(r'(\d+(?:\.\d+)?)\s*[Ss]级', b['desc'])
    if prec_a and prec_b and set(prec_a) != set(prec_b):
        return f'互感器精度等级不同'
    return None

def check_wire_type(a, b):
    """电线类型不同"""
    wire_types = ['BV', 'BVR', 'RV', 'RVV', 'RVVP', 'KVV', 'KVVP', 'YJV', 'NH-YJV', 
                  'ZR-YJV', 'ZR-BV', 'ZR-BVR', 'WDZA-YJY', 'WDZB-YJY', 'WDZC-YJY',
                  'NH-YJV', 'NHYJV']
    for wt in wire_types:
        if (wt in a['desc']) != (wt in b['desc']):
            return f'电线类型不同({wt})'
    return None

def check_protection_type(a, b):
    """保护类型不同"""
    prots = ['变压器保护', '线路保护', '电容器保护', '电动机保护', '发电机保护']
    for p in prots:
        if (p in a['desc']) != (p in b['desc']):
            return f'保护类型不同({p})'
    return None

def check_thread(a, b):
    """螺纹方向不同"""
    if ('左旋' in a['desc'] and '右旋' in b['desc']) or ('右旋' in a['desc'] and '左旋' in b['desc']):
        return '螺纹方向不同(左旋/右旋)'
    if ('正牙' in a['desc'] and '反牙' in b['desc']) or ('反牙' in a['desc'] and '正牙' in b['desc']):
        return '螺纹方向不同(正牙/反牙)'
    return None

def check_version(a, b):
    """版本不同"""
    ver_a = re.findall(r'[Vv]?(\d+[A-Za-z])\b', a['desc'])
    ver_b = re.findall(r'[Vv]?(\d+[A-Za-z])\b', b['desc'])
    if ver_a and ver_b and set(ver_a) != set(ver_b):
        return f'版本不同({set(ver_a)}/{set(ver_b)})'
    return None

def check_trip_method(a, b):
    """脱扣方式不同"""
    methods = [('TMD', '热磁'), ('MA', '仅电磁'), ('MIC', '电子'), ('LI', '热磁')]
    for code, desc in methods:
        if (code in a['desc']) != (code in b['desc']):
            return f'脱扣方式不同({code})'
    if ('热磁' in a['desc']) != ('热磁' in b['desc']):
        return '脱扣方式不同(热磁)'
    return None

def check_trip_unit(a, b):
    """脱扣单元不同"""
    units = ['LSI', 'LSI/LSIG', 'TMA', 'TMF', 'TMG', 'MIC', 'MA', 'TMD', 'LI', 'LSCI']
    for u in units:
        if (u in a['desc']) != (u in b['desc']):
            return f'脱扣单元不同({u})'
    return None

def check_accessory_type(a, b):
    """配件差异"""
    acc_types = ['安全挂锁', '相间隔板', '端子罩', '防护罩', '手柄', '操作手柄',
                 '延长手柄', '接线端子', '板前', '板后']
    for at in acc_types:
        if (at in a['desc']) != (at in b['desc']):
            return f'配件差异({at})'
    return None

def check_surge_arrester(a, b):
    """过电压保护器型号不同"""
    m_a = re.findall(r'TBP[-‐]?([A-Z])', a['desc'])
    m_b = re.findall(r'TBP[-‐]?([A-Z])', b['desc'])
    if m_a and m_b and set(m_a) != set(m_b):
        return f'过电压保护器型号不同({set(m_a)}/{set(m_b)})'
    return None

def check_series(a, b):
    """型号系列不同"""
    # CM3E(电子式) vs CM3(普通), CDM3 vs CDM3E
    m_a = re.match(r'^([A-Za-z][A-Za-z0-9\-]*)', a['desc'])
    m_b = re.match(r'^([A-Za-z][A-Za-z0-9\-]*)', b['desc'])
    if m_a and m_b:
        sa, sb = m_a.group(1), m_b.group(1)
        # 检查是否一个包含另一个（如 CDM3 vs CDM3E）
        if sa != sb and (sa.startswith(sb) or sb.startswith(sa) or 
                        sa.rstrip('Ee') == sb.rstrip('Ee') or
                        sa.rstrip('Ll') == sb.rstrip('Ll')):
            # 可能是同一系列不同型号
            pass
        elif sa != sb:
            return f'型号系列不同({sa}/{sb})'
    return None

def check_rated_current(a, b):
    """额定电流不同"""
    # 匹配 xxxA 格式的额定电流
    currents_a = set(re.findall(r'(\d+)\s*[Aa](?:\b|(?=\s))', a['desc']))
    currents_b = set(re.findall(r'(\d+)\s*[Aa](?:\b|(?=\s))', b['desc']))
    if currents_a and currents_b:
        # 去掉可能是分断能力的 kA
        currents_a -= set(re.findall(r'(\d+)\s*k?[Aa]', a['desc'].lower()))
        currents_b -= set(re.findall(r'(\d+)\s*k?[Aa]', b['desc'].lower()))
        if currents_a and currents_b and currents_a != currents_b:
            return f'额定电流不同({currents_a}/{currents_b})'
    return None

def check_breaking_capacity(a, b):
    """分断能力不同 kA"""
    ka_a = re.findall(r'(\d+)\s*[kK][aA]', a['desc'])
    ka_b = re.findall(r'(\d+)\s*[kK][aA]', b['desc'])
    if ka_a and ka_b and set(ka_a) != set(ka_b):
        return f'分断能力不同({set(ka_a)}/{set(ka_b)}kA)'
    return None

def check_ip_rating(a, b):
    """保护等级不同"""
    ip_a = re.findall(r'IP\d+', a['desc'])
    ip_b = re.findall(r'IP\d+', b['desc'])
    if ip_a and ip_b and set(ip_a) != set(ip_b):
        return f'保护等级不同({set(ip_a)}/{set(ip_b)})'
    return None

def check_dimensions(a, b):
    """尺寸不同"""
    dim_a = re.findall(r'(\d+)\s*[×xX*]\s*(\d+)\s*[×xX*]\s*(\d+)', a['desc'])
    dim_b = re.findall(r'(\d+)\s*[×xX*]\s*(\d+)\s*[×xX*]\s*(\d+)', b['desc'])
    if dim_a and dim_b and set(tuple(map(int, d)) for d in dim_a) != set(tuple(map(int, d)) for d in dim_b):
        return f'尺寸不同'
    return None

def classify_pair(a, b):
    """分类一对物料"""
    # 相同物料编号 = 肯定不是重复
    if a['id'] == b['id']:
        return ('same_id', '物料编号相同（同一条记录）')
    
    # Rule 1: 甲供件
    if '甲供' in a['source'] or '甲供' in b['source']:
        return ('not_dup', '甲供件不算重复')
    
    # Rule 2: 制造商一有一无
    if (a['manufacturer'] and not b['manufacturer']) or (not a['manufacturer'] and b['manufacturer']):
        return ('not_dup', '制造商一有一无')
    
    # Rule 3: 安装方向不同
    r = check_directional_diff(a, b)
    if r: return ('not_dup', r)
    
    # Rule 4: 断路器分断能力等级不同
    r = check_breaker_grade(a, b)
    if r: return ('not_dup', r)
    
    # Rule 4b: 分断能力 kA 不同
    r = check_breaking_capacity(a, b)
    if r: return ('not_dup', r)
    
    # Rule 5: 脱扣曲线不同
    r = check_trip_curve(a, b)
    if r: return ('not_dup', r)
    
    # Rule 6: 极数不同
    r = check_poles(a, b)
    if r: return ('not_dup', r)
    
    # Rule 7: 颜色不同
    r = check_color(a, b)
    if r: return ('not_dup', r)
    
    # Rule 8: 漏电保护类型不同
    r = check_rcc_type(a, b)
    if r: return ('not_dup', r)
    
    # Rule 9: 带附件vs不带
    r = check_accessory(a, b)
    if r: return ('not_dup', r)
    
    # Rule 10: 互感器差异
    r = check_ct_diff(a, b)
    if r: return ('not_dup', r)
    
    # Rule 11: 电线类型不同
    r = check_wire_type(a, b)
    if r: return ('not_dup', r)
    
    # Rule 12: 保护类型不同
    r = check_protection_type(a, b)
    if r: return ('not_dup', r)
    
    # Rule 13: 螺纹方向不同
    r = check_thread(a, b)
    if r: return ('not_dup', r)
    
    # Rule 14: 版本不同
    r = check_version(a, b)
    if r: return ('not_dup', r)
    
    # Rule 15: 脱扣方式不同
    r = check_trip_method(a, b)
    if r: return ('not_dup', r)
    
    # Rule 16: 脱扣单元不同
    r = check_trip_unit(a, b)
    if r: return ('not_dup', r)
    
    # Rule 17: 配件差异
    r = check_accessory_type(a, b)
    if r: return ('not_dup', r)
    
    # Rule 18: 过电压保护器型号不同
    r = check_surge_arrester(a, b)
    if r: return ('not_dup', r)
    
    # Rule 19: 型号系列不同
    r = check_series(a, b)
    if r: return ('not_dup', r)
    
    # 额外规则：额定电流不同
    r = check_rated_current(a, b)
    if r: return ('not_dup', r)
    
    # 额外规则：保护等级不同
    r = check_ip_rating(a, b)
    if r: return ('not_dup', r)
    
    # 额外规则：尺寸不同
    r = check_dimensions(a, b)
    if r: return ('not_dup', r)
    
    # 确认重复判断
    if a['desc'] == b['desc'] and a['name'] == b['name']:
        if a['manufacturer'] == b['manufacturer']:
            return ('confirmed_dup', '名称描述制造商均相同')
        elif a['manufacturer'] and b['manufacturer']:
            # 两者都有制造商但不同
            return ('likely_dup', '名称描述相同，制造商不同')
        else:
            return ('confirmed_dup', '名称描述相同，均无制造商')
    
    # 描述高度相似
    ratio = SequenceMatcher(None, a['desc'], b['desc']).ratio()
    if ratio >= 0.95:
        return ('likely_dup', f'描述高度相似({ratio:.3f})')
    elif ratio >= 0.85:
        return ('pending', f'描述部分相似({ratio:.3f})，需人工确认')
    
    return ('likely_dup', f'名称相同描述不同(ratio={ratio:.3f})')

# 执行分类
confirmed_dup = []
likely_dup = []
not_dup = []
pending = []
skip_count = 0

for i, (idx_a, idx_b) in enumerate(all_pairs):
    a = get_row_data(idx_a)
    b = get_row_data(idx_b)
    cat, reason = classify_pair(a, b)
    
    if cat == 'same_id':
        skip_count += 1
        continue
    elif cat == 'confirmed_dup':
        confirmed_dup.append({'a': a, 'b': b, 'reason': reason})
    elif cat == 'likely_dup':
        likely_dup.append({'a': a, 'b': b, 'reason': reason})
    elif cat == 'not_dup':
        not_dup.append({'a': a, 'b': b, 'reason': reason})
    elif cat == 'pending':
        pending.append({'a': a, 'b': b, 'reason': reason})
    
    if (i + 1) % 5000 == 0:
        print(f"  已分类 {i+1}/{len(all_pairs)} 对...", flush=True)

print(f"\n[{time.strftime('%H:%M:%S')}] === 分类结果 ===", flush=True)
print(f"  跳过（同一物料编号）: {skip_count}", flush=True)
print(f"  ✅ 确认重复: {len(confirmed_dup)}", flush=True)
print(f"  ⚠️  高度可疑: {len(likely_dup)}", flush=True)
print(f"  ❌ 非重复（规则排除）: {len(not_dup)}", flush=True)
print(f"  ❓ 待人工确认: {len(pending)}", flush=True)
total = len(confirmed_dup) + len(likely_dup) + len(not_dup) + len(pending)
print(f"  总计: {total}", flush=True)

# 保存中间结果
summary = {
    'total_materials': len(df_check),
    'total_candidates': len(all_pairs),
    'confirmed_dup': len(confirmed_dup),
    'likely_dup': len(likely_dup),
    'not_dup': len(not_dup),
    'pending': len(pending),
    'skip': skip_count,
    'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
}
with open('classification_summary_v3.json', 'w', encoding='utf-8') as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)

with open('confirmed_dup_v3.json', 'w', encoding='utf-8') as f:
    json.dump(confirmed_dup, f, ensure_ascii=False)
with open('likely_dup_v3.json', 'w', encoding='utf-8') as f:
    json.dump(likely_dup, f, ensure_ascii=False)
with open('not_dup_v3.json', 'w', encoding='utf-8') as f:
    json.dump(not_dup, f, ensure_ascii=False)
with open('pending_v3.json', 'w', encoding='utf-8') as f:
    json.dump(pending, f, ensure_ascii=False)

print(f"\n[{time.strftime('%H:%M:%S')}] 中间结果已保存", flush=True)
