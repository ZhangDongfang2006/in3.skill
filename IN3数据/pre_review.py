#!/usr/bin/env python3
"""
增强版预审查：更严格的制造商比较和描述比较规则。
核心逻辑：
- 描述相同 + 制造商不同 → 排除（不同供应商的同规格物料）
- 描述相同 + 制造商一方有一方无 → 排除（Dongfang 2026-06-02 确认）
- 描述相同 + 制造商相同 → 确认重复
- 描述有差异 → 需要详细分析
"""
import json
import re
import os

def load_whitelist(path):
    with open(path, 'r') as f:
        data = json.load(f)
    wl = set()
    for pair in data.get('pairs', []):
        a, b = sorted(pair)
        wl.add((a, b))
    return wl

def normalize_manufacturer(m):
    """统一制造商名称"""
    if not m:
        return ''
    m = str(m).strip()
    if not m:
        return ''
    # 去掉常见后缀
    suffixes = ['有限公司', '有限责任公司', '股份有限公司', '(中国)', '（中国）',
                '科技有限公司', '科技公司', '集团公司', '集团', '制造厂', '制造',
                '电气公司', '电气', '电器公司', '电器', '自动化公司', '自动化',
                '仪表公司', '仪表', '电子公司', '电子', '机械公司', '机械']
    result = m
    for s in suffixes:
        result = result.replace(s, '')
    return result.strip()

def normalize_desc(s):
    """标准化描述用于比较"""
    s = str(s).strip()
    s = s.replace('（', '(').replace('）', ')')
    s = re.sub(r'\s+', ' ', s)  # 多个空格变一个
    s = s.strip()
    return s

def desc_fuzzy_equal(a, b):
    """描述模糊相等判断"""
    na = normalize_desc(a)
    nb = normalize_desc(b)
    if na == nb:
        return True
    # 去掉所有空格和括号后比较
    def strip_all(s):
        s = s.replace(' ', '').replace('　', '')
        s = s.replace('(', '').replace(')', '')
        s = s.replace('/', '').replace('\\', '')
        s = s.replace('+', '').replace('*', '').replace('×', 'x')
        s = s.replace('，', '').replace(',', '')
        s = s.lower()
        return s
    if strip_all(na) == strip_all(nb):
        return True
    return False

def manufacturers_different(mfr_a, mfr_b):
    """
    判断两个制造商是否确实不同。
    返回: True=确实不同, False=相同或无法判断
    """
    if not mfr_a and not mfr_b:
        return False  # 都为空，不算"不同"
    if not mfr_a or not mfr_b:
        return True  # 一个有制造商一个没有 → 非重复（Dongfang 2026-06-02 确认）
    
    nm_a = normalize_manufacturer(mfr_a)
    nm_b = normalize_manufacturer(mfr_b)
    
    if not nm_a or not nm_b:
        return False
    
    # 完全匹配
    if nm_a == nm_b:
        return False
    
    # 一个包含另一个（简称）
    if nm_a in nm_b or nm_b in nm_a:
        return False
    
    # 常见同一厂家不同写法的映射
    aliases = {
        '三菱': ['三菱电机'],
        'ABB': ['ABB'],
        '良信': ['NDM', '良信电器'],
        '正泰': ['CHNT', '正泰电器'],
        '德力西': ['DELIXI', '德力西电气'],
        '环宇': ['环宇高科', 'HUYU'],
        '指明': ['指明集团', 'ZM'],
        '天正': ['TENGEN', '天正电器'],
        '常熟': ['常熟开关', 'RIY1'],
        '上海人民': ['人民电器', 'RMW', 'RMM'],
        '宁波三爱': ['三爱'],
        '大连一互': ['一互'],
        '大连北方': ['北方'],
        '宁波天灵': ['天灵'],
        '江阴长江': ['长江'],
        '长江电气': ['长江'],
        '浙江天际': ['天际'],
        '宁波同禾': ['同禾'],
        '浙江三狮': ['三狮'],
        '江北和能': ['和能'],
        '宁波莱堡': ['莱堡'],
        '宁波正格': ['正格'],
        '杭州华世': ['华世'],
        '浙江侃诚': ['侃诚'],
        '苏州天业': ['天业'],
        '狮特': ['狮特'],
        '福祥瑞特': ['福祥'],
        '上海呈星': ['呈星'],
        '上海甬扬': ['甬扬'],
        '博世力士乐': ['博世', '力士乐'],
        '默飓电气': ['默飓'],
        '上海纳宇': ['纳宇'],
        '浩亭': ['浩亭'],
        '三和电机': ['三和'],
        '郭运浩': [],
        '邵显扬': [],
        '彭更生': [],
    }
    
    # 检查是否属于同一组别名
    def find_group(name):
        name_lower = name.lower()
        for key, alias_list in aliases.items():
            if key in name_lower:
                return key
            for al in alias_list:
                if al.lower() in name_lower:
                    return key
        # 尝试提取核心名称
        return name_lower
    
    group_a = find_group(nm_a)
    group_b = find_group(nm_b)
    
    if group_a == group_b:
        return False  # 同一组别名
    
    return True  # 确实不同

def has_dimension_difference(a, b):
    """检查是否有尺寸/规格数字差异"""
    desc_a = str(a.get('desc', ''))
    desc_b = str(b.get('desc', ''))
    
    # 提取关键数字：电流、功率、尺寸等
    # 电流值 (数字 + A，但不是 AC/AC220V等)
    current_a = re.findall(r'(\d+)\s*A(?![a-zA-ZVv])', desc_a)
    current_b = re.findall(r'(\d+)\s*A(?![a-zA-ZVv])', desc_b)
    
    # 功率
    power_a = re.findall(r'(\d+\.?\d*)\s*[kK][Ww]', desc_a)
    power_b = re.findall(r'(\d+\.?\d*)\s*[kK][Ww]', desc_b)
    
    # 孔数
    holes_a = re.findall(r'(\d+)\s*孔', desc_a)
    holes_b = re.findall(r'(\d+)\s*孔', desc_b)
    
    # 位数
    pos_a = re.findall(r'(\d+)\s*位', desc_a)
    pos_b = re.findall(r'(\d+)\s*位', desc_b)
    
    if holes_a and holes_b and sorted(holes_a) != sorted(holes_b):
        return True, f'孔数不同 ({holes_a} vs {holes_b})'
    if pos_a and pos_b and sorted(pos_a) != sorted(pos_b):
        return True, f'位数不同 ({pos_a} vs {pos_b})'
    if power_a and power_b and sorted(power_a) != sorted(power_b):
        return True, f'功率不同 ({power_a} vs {power_b})'
    
    # 电流比较（取描述中独立的电流值）
    # 排除电压中的数字如 AC220V, 380V 等
    def extract_currents(desc):
        # 匹配 "数字A" 但排除 "AC数字V" "DC数字V" 等
        results = []
        for m in re.finditer(r'(\d+)\s*A\b', desc):
            # 检查前后文
            start = max(0, m.start() - 5)
            prefix = desc[start:m.start()]
            if 'AC' not in prefix.upper() and 'DC' not in prefix.upper():
                results.append(m.group(1))
        return results
    
    cur_a = extract_currents(desc_a)
    cur_b = extract_currents(desc_b)
    if cur_a and cur_b and sorted(cur_a) != sorted(cur_b):
        return True, f'电流不同 ({cur_a} vs {cur_b})'
    
    return False, ''

def has_direction_difference(a, b):
    """检查方向差异"""
    desc_a = str(a.get('desc', ''))
    desc_b = str(b.get('desc', ''))
    name_a = str(a.get('name', ''))
    name_b = str(b.get('name', ''))
    
    combined_a = name_a + ' ' + desc_a
    combined_b = name_b + ' ' + desc_b
    
    dir_pairs = [
        ('左操', '右操'), ('左旋', '右旋'), ('上进', '下进'),
        ('立式', '卧式'), ('平进', '垂进'), ('明装', '暗装'),
        ('壁挂', '落地'),
    ]
    
    for d1, d2 in dir_pairs:
        if (d1 in combined_a and d2 in combined_b) or (d2 in combined_a and d1 in combined_b):
            return True, f'方向不同 ({d1} vs {d2})'
    
    return False, ''

def has_material_difference(a, b):
    """检查材质差异"""
    desc_a = str(a.get('desc', ''))
    desc_b = str(b.get('desc', ''))
    name_a = str(a.get('name', ''))
    name_b = str(b.get('name', ''))
    
    combined_a = name_a + ' ' + desc_a
    combined_b = name_b + ' ' + desc_b
    
    mat_pairs = [
        ('紫铜', '黄铜'), ('铜', '铝'),
        ('SUS304', 'SUS316'), ('304', '316'),
        ('橡胶', '聚氨酯'), ('橡胶', '尼龙'),
    ]
    
    for m1, m2 in mat_pairs:
        if (m1 in combined_a and m2 in combined_b) or (m2 in combined_a and m1 in combined_b):
            return True, f'材质不同 ({m1} vs {m2})'
    
    return False, ''

def has_shape_difference(a, b):
    """检查形状差异"""
    name_a = str(a.get('name', ''))
    name_b = str(b.get('name', ''))
    
    if ('定向轮' in name_a and '万向轮' in name_b) or ('万向轮' in name_a and '定向轮' in name_b):
        return True, '定向轮 vs 万向轮'
    
    return False, ''

def has_function_difference(a, b):
    """检查功能差异"""
    desc_a = str(a.get('desc', ''))
    desc_b = str(b.get('desc', ''))
    
    # 插头 vs 插座
    if ('插头' in desc_a and '插座' in desc_b) or ('插座' in desc_a and '插头' in desc_b):
        return True, '插头 vs 插座'
    
    # 3P vs 4P 极数差异
    combined_a = desc_a
    combined_b = desc_b
    if '3P' in combined_a and '4P' in combined_b and combined_a.replace('3P', '4P') == combined_b:
        return True, '极数不同 (3P vs 4P)'
    if '4P' in combined_a and '3P' in combined_b and combined_a.replace('4P', '3P') == combined_b:
        return True, '极数不同 (4P vs 3P)'
    
    return False, ''

def main():
    data_dir = 'IN3数据'
    
    with open(os.path.join(data_dir, 'candidate_pairs.json'), 'r') as f:
        pairs = json.load(f)
    
    whitelist = load_whitelist(os.path.join(data_dir, '物料非重复白名单.json'))
    
    confirmed = []
    excluded = []
    pending = []
    
    for item in pairs:
        a = item['A']
        b = item['B']
        code_a = a.get('code', '')
        code_b = b.get('code', '')
        name_a = str(a.get('name', '')).strip()
        name_b = str(b.get('name', '')).strip()
        desc_a = str(a.get('desc', '')).strip()
        desc_b = str(b.get('desc', '')).strip()
        mfr_a = str(a.get('manufacturer', '')).strip()
        mfr_b = str(b.get('manufacturer', '')).strip()
        source_a = str(a.get('source', '')).strip()
        source_b = str(a.get('source', '')).strip()
        
        # 1. 白名单
        wl_key = tuple(sorted([code_a, code_b]))
        if wl_key in whitelist:
            excluded.append({'A': a, 'B': b, 'reason': '排除: 白名单（已确认非重复）'})
            continue
        
        # 2. 甲供件
        if source_a == '甲供件' or source_b == '甲供件':
            excluded.append({'A': a, 'B': b, 'reason': '排除: 甲供件'})
            continue
        
        # 3. 名称不同 → 不太可能是重复
        if name_a != name_b:
            # 检查是否只是表述差异
            # 常见同义词
            synonyms = [
                ('铜排', '铜母线'), ('电线', '电缆'), ('导线', '电线'),
                ('标牌', '铭牌'), ('指示灯', '信号灯'),
            ]
            is_synonym = False
            for s1, s2 in synonyms:
                if (s1 in name_a and s2 in name_b) or (s2 in name_a and s1 in name_b):
                    is_synonym = True
                    break
            if not is_synonym:
                excluded.append({'A': a, 'B': b, 'reason': f'排除: 名称不同 ({name_a} vs {name_b})'})
                continue
        
        # 4. 检查形状差异
        diff, reason = has_shape_difference(a, b)
        if diff:
            excluded.append({'A': a, 'B': b, 'reason': f'排除: {reason}'})
            continue
        
        # 5. 检查功能差异
        diff, reason = has_function_difference(a, b)
        if diff:
            excluded.append({'A': a, 'B': b, 'reason': f'排除: {reason}'})
            continue
        
        # 6. 检查方向差异
        diff, reason = has_direction_difference(a, b)
        if diff:
            excluded.append({'A': a, 'B': b, 'reason': f'排除: {reason}'})
            continue
        
        # 7. 检查材质差异
        diff, reason = has_material_difference(a, b)
        if diff:
            excluded.append({'A': a, 'B': b, 'reason': f'排除: {reason}'})
            continue
        
        # 8. 检查尺寸/规格差异
        diff, reason = has_dimension_difference(a, b)
        if diff:
            excluded.append({'A': a, 'B': b, 'reason': f'排除: {reason}'})
            continue
        
        # 9. 检查制造商是否不同
        mfrs_differ = manufacturers_different(mfr_a, mfr_b)
        
        # 10. 描述比较
        desc_eq = desc_fuzzy_equal(desc_a, desc_b)
        
        if desc_eq and mfrs_differ:
            # 描述相同但制造商不同 → 不算重复（不同供应商的同规格物料）
            excluded.append({'A': a, 'B': b, 'reason': f'排除: 制造商不同 ({mfr_a or "无"} vs {mfr_b or "无"})，描述相同'})
            continue
        
        if desc_eq and not mfrs_differ:
            # 描述相同 + 制造商相同 → 确认重复
            confirmed.append({'A': a, 'B': b, 'reason': f'确认重复: 描述相同，制造商相同 ({mfr_a or "无"} / {mfr_b or "无"})'})
            continue
        
        # 描述不同 → 需要详细分析
        # 先尝试简单比较：去掉空格后是否相同
        if desc_eq:
            confirmed.append({'A': a, 'B': b, 'reason': '确认重复: 描述仅有格式差异'})
            continue
        
        # 真正需要 AI 审查的
        pending.append({'A': a, 'B': b, 'reason': '待AI审查'})
    
    print(f'总计: {len(pairs)} 对')
    print(f'确认重复: {len(confirmed)} 对')
    print(f'已排除: {len(excluded)} 对')
    print(f'待AI审查: {len(pending)} 对')
    
    results = {
        'confirmed': confirmed,
        'pending': pending,
        'excluded': excluded
    }
    
    out_file = os.path.join(data_dir, 'review_results.json')
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f'已保存到: {out_file}')
    
    pending_file = os.path.join(data_dir, 'pending_pairs.json')
    with open(pending_file, 'w', encoding='utf-8') as f:
        json.dump(pending, f, ensure_ascii=False, indent=2)
    print(f'待审查配对保存到: {pending_file}')

if __name__ == '__main__':
    main()
