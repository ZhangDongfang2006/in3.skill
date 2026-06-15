#!/usr/bin/env python3
"""Review candidate pairs - clean version."""
import json, re, os

data_dir = 'IN3数据'

# === Load data ===
with open(os.path.join(data_dir, 'candidate_pairs.json'), 'r') as f:
    all_pairs = json.load(f)

# Load known sets
known = {'wl': set(), 'dup': set(), 'nondup': set()}
for fn, key in [('物料非重复白名单.json', 'wl'), ('dongfang_confirmed_dup.json', 'dup'), ('dongfang_confirmed_nondup.json', 'nondup')]:
    with open(os.path.join(data_dir, fn), 'r') as f:
        data = json.load(f)
    items = data.get('pairs', data) if isinstance(data, dict) else data
    for item in items:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            known[key].add(tuple(sorted([str(item[0]), str(item[1])])))

print(f"候选: {len(all_pairs)}, 白名单: {len(known['wl'])}, 已确认重复: {len(known['dup'])}, 已确认非重复: {len(known['nondup'])}")

def normalize_mfr(mfr):
    if not mfr:
        return ''
    mfr = str(mfr).strip()
    if not mfr:
        return ''
    for s in ['有限公司', '(中国)', '（中国）', '股份有限公司', '股份公司', '有限责任公司', '公司', '集团', '厂', '制造']:
        mfr = mfr.replace(s, '')
    mfr = mfr.replace('/', '')
    return mfr.strip()

def ultra_norm(s):
    if not s:
        return ''
    s = str(s).strip().lower()
    s = re.sub(r'[\s\u3000]+', '', s)
    s = re.sub(r'[（）\(\)\[\]【】{}]', '', s)
    s = s.replace('×', 'x').replace('－', '-').replace('—', '-').replace('，', ',').replace('：', ':').replace('；', ';').replace('。', '.')
    return s

def get_numbers(s):
    return set(re.findall(r'\d+\.?\d*', str(s)))

def is_nondup(a, b):
    """Return exclusion reason if clearly non-duplicate, else None."""
    ma = normalize_mfr(a.get('manufacturer', ''))
    mb = normalize_mfr(b.get('manufacturer', ''))
    
    # Different manufacturers
    if ma and mb and ma != mb:
        return '制造商不同'
    
    # One has mfr, other doesn't
    if (ma and not mb) or (not ma and mb):
        return '制造商有vs无'
    
    # 甲供件
    sa = str(a.get('source', ''))
    sb = str(b.get('source', ''))
    if '甲供' in sa or '甲供' in sb:
        return '甲供件'
    
    da = str(a.get('desc', ''))
    db = str(b.get('desc', ''))
    uda = ultra_norm(da)
    udb = ultra_norm(db)
    
    # If desc identical (ultra-normalized), don't exclude - might be dup
    if uda == udb:
        return None
    
    # Different numbers = different specs
    na = get_numbers(da)
    nb = get_numbers(db)
    
    # Find numbers that differ (float-equal check)
    def float_set(nums):
        s = set()
        for n in nums:
            try:
                s.add(round(float(n), 2))
            except:
                s.add(n)
        return s
    
    fna = float_set(na)
    fnb = float_set(nb)
    diff_a = fna - fnb
    diff_b = fnb - fna
    if diff_a or diff_b:
        return '规格参数不同'
    
    # Direction/installation
    na_str = str(a.get('name', ''))
    nb_str = str(b.get('name', ''))
    for d in ['上进', '下进', '左操', '右操', '左旋', '右旋', '立式', '卧式', '明装', '暗装', '壁挂', '落地', '平进', '垂进']:
        if (d in da or d in na_str) != (d in db or d in nb_str):
            return f'方向/安装不同:{d}'
    
    # Polarity
    for p in ['1P', '2P', '3P', '4P', 'A型', 'B型', 'C型', 'N型']:
        if (p in da) != (p in db):
            return f'极数不同:{p}'
    
    # Color
    for c in ['红', '黄', '绿', '蓝', '黑', '白', '灰']:
        if (c in na_str or c in da) != (c in nb_str or c in db):
            return f'颜色不同:{c}'
    
    # Surface treatment in name
    for st in ['镀锌', '镀彩锌', '镀白锌', '镀银', '发黑', '镀镍', '不锈钢']:
        if (st in na_str) != (st in nb_str):
            return f'表面处理不同:{st}'
    
    # 附件差异
    for acc in ['失压', '分励', '辅助', '报警', '通讯', '底座']:
        if (acc in da) != (acc in db):
            return f'附件差异:{acc}'
    
    # 分闸合闸
    if ('分闸' in da) != ('分闸' in db) or ('合闸' in da) != ('合闸' in db):
        return '分闸合闸差异'
    
    # Shape (定向/万向)
    if ('定向轮' in na_str) != ('定向轮' in nb_str) or ('万向轮' in na_str) != ('万向轮' in nb_str):
        return '形状差异'
    
    # 柜型
    for ct in ['GCK', 'GCS', 'MNS', 'KYN28', 'GGD']:
        if (ct in da) != (ct in db):
            return f'柜型不同:{ct}'
    
    # Material difference in name
    mat_words = ['铜', '铝', '紫铜', '黄铜']
    for mw in mat_words:
        if (mw in na_str) != (mw in nb_str):
            return f'材质不同:{mw}'
    
    # Name-based exclusion: different semantic categories
    # If names are very different, likely not duplicates
    if na_str != nb_str:
        # Check if names are close synonyms
        synonyms = [
            ('角钢', '角铁'), ('螺母', '螺帽'), ('接触器', '交流接触器'),
            ('断路器', '塑壳断路器'), ('电度表', '电能表'),
            ('多功能表', '电能表'), ('铜排', '母排'),
        ]
        is_syn = any((s1 in na_str and s2 in nb_str) or (s2 in na_str and s1 in nb_str) for s1, s2 in synonyms)
        # Also check if one name contains the other
        if not is_syn and na_str not in nb_str and nb_str not in na_str:
            # Truly different names, check if it's like 塑壳断路器 vs 塑壳漏电断路器
            # These have different functionality
            non_dup_name_pairs = [
                ('微型断路器', '微型漏电断路器'),
                ('塑壳断路器', '塑壳漏电断路器'),
                ('铜排包扣', '绝缘子包扣'), ('铜排包扣', '电缆头包扣'), ('绝缘子包扣', '电缆头包扣'),
                ('金属石墨垫片', '90°压制弯头'),
                ('等径压制三通', '90°压制弯头'), ('等径压制三通', '90°内螺纹压制弯头'),
                ('U型管夹', '等径压制三通'), ('U型管夹', '90°压制弯头'),
            ]
            for p1, p2 in non_dup_name_pairs:
                if (p1 in na_str and p2 in nb_str) or (p2 in na_str and p1 in nb_str):
                    return f'名称类别不同:{na_str} vs {nb_str}'
    
    # Model number letter differences (e.g. BM3E vs BM3)
    # Extract base model without the last letter
    uda = ultra_norm(da)
    udb = ultra_norm(db)
    
    return None

def is_dup(a, b):
    """Return confirmation reason if clearly duplicate, else None."""
    ma = normalize_mfr(a.get('manufacturer', ''))
    mb = normalize_mfr(b.get('manufacturer', ''))
    same_mfr = (ma == mb) or (not ma and not mb)
    
    da = ultra_norm(str(a.get('desc', '')))
    db = ultra_norm(str(b.get('desc', '')))
    
    if da == db and same_mfr:
        return '描述完全相同+同制造商'
    
    # Only formatting diff
    ca = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fff]', '', da)
    cb = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fff]', '', db)
    if ca == cb and ca and same_mfr:
        return '仅格式差异'
    
    return None

# === Process ===
confirmed = []
pending = []
excluded = 0
skipped_wl = 0
skipped_dup = 0
skipped_nondup = 0

for pair in all_pairs:
    a, b = pair['A'], pair['B']
    key = tuple(sorted([a.get('code', ''), b.get('code', '')]))
    
    if key in known['wl']:
        skipped_wl += 1
        continue
    if key in known['dup']:
        skipped_dup += 1
        confirmed.append({'A': a, 'B': b, 'reason': 'Dongfang确认重复'})
        continue
    if key in known['nondup']:
        skipped_nondup += 1
        continue
    
    reason = is_nondup(a, b)
    if reason:
        excluded += 1
        continue
    
    reason = is_dup(a, b)
    if reason:
        confirmed.append({'A': a, 'B': b, 'reason': reason})
        continue
    
    pending.append({'A': a, 'B': b, 'reason': '需人工确认'})

print(f"\n=== 审查结果 ===")
print(f"白名单跳过: {skipped_wl}")
print(f"已知重复: {skipped_dup}")
print(f"已知非重复: {skipped_nondup}")
print(f"规则排除: {excluded}")
print(f"确认重复: {len(confirmed)}")
print(f"待确认: {len(pending)}")

results = {'confirmed': confirmed, 'pending': pending}
with open(os.path.join(data_dir, 'review_results.json'), 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f"已保存到 review_results.json")
