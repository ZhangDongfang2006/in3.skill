#!/usr/bin/env python3
"""
IN3 物料重复检查 v4 - 高效版
策略：完全相同 + 标准化相同 + 快速模糊匹配（仅±2长度差）
"""
import pandas as pd
import re
import json
import pickle
from collections import defaultdict
import time, gc

start = time.time()

# 1. 读取数据
print("Step 1: 读取数据...")
INPUT = 'IN3数据/物料主数据导出结果-20260509161728.xlsx'
df = pd.read_excel(INPUT, sheet_name='物料主数据', header=0)
print(f"  总行数: {len(df)}")

col_names = list(df.columns)
COL_MAP = {
    '物料编号': 1, '物料名称': 5, '物料描述': 6, '物料类别': 8, '物料子类别': 10,
    '制造商': 12, '物料来源': 13, '提前期': 17, '主计量单位': 21, '标准价格': 60,
    '创建人': 69, '创建日期': 71, '最近修改人': 72, '最近修改日期': 74,
}
key_cols = list(COL_MAP.keys())
data = df[[col_names[i] for i in COL_MAP.values()]].copy()
data.columns = key_cols

for c in key_cols:
    data[c] = data[c].fillna('').astype(str).str.strip()
data['创建日期'] = data['创建日期'].apply(lambda x: x.split(' ')[0] if ' ' in x and len(x)>10 else x)
data['最近修改日期'] = data['最近修改日期'].apply(lambda x: x.split(' ')[0] if ' ' in x and len(x)>10 else x)

print(f"  物料总数: {len(data)}")
del df; gc.collect()

# 2. 标准化
def normalize(s):
    s = s.strip()
    s = s.replace('（','(').replace('）',')')
    s = s.replace('，',',').replace('。','.').replace('：',':')
    s = s.replace('；',';').replace('"','"').replace('"','"')
    s = s.replace('【','[').replace('】',']')
    s = re.sub(r'\s+', ' ', s)
    return s

def deep_normalize(s):
    s = normalize(s)
    s = s.replace(' ', '').replace('-','').replace('/','')
    return s

# 预计算
descs = data['物料描述'].tolist()
norms = [normalize(d) for d in descs]
deeps = [deep_normalize(d) for d in descs]

print(f"  标准化完成, 耗时: {time.time()-start:.1f}s")

# 3. 按物料类别分组
print("\nStep 2: 筛选可疑重复...")
cat_indices = defaultdict(list)
for i in range(len(data)):
    cat = data.iloc[i]['物料类别']
    if cat:
        cat_indices[cat].append(i)

all_pairs = set()  # (min_idx, max_idx)

# 3a. 完全相同描述
print("  3a. 完全相同描述...")
norm_to_idx = defaultdict(list)
for i, n in enumerate(norms):
    if n:
        norm_to_idx[n].append(i)

for n, idxs in norm_to_idx.items():
    if len(idxs) > 1:
        for a in range(len(idxs)):
            for b in range(a+1, len(idxs)):
                all_pairs.add((min(idxs[a], idxs[b]), max(idxs[a], idxs[b])))

print(f"    完全相同: {len(all_pairs)} 对")

# 3b. 深度标准化后相同
print("  3b. 深度标准化后相同...")
deep_to_idx = defaultdict(list)
for i, d in enumerate(deeps):
    if d:
        deep_to_idx[d].append(i)

for d, idxs in deep_to_idx.items():
    if len(idxs) > 1:
        for a in range(len(idxs)):
            for b in range(a+1, len(idxs)):
                pair = (min(idxs[a], idxs[b]), max(idxs[a], idxs[b]))
                if pair not in all_pairs:
                    all_pairs.add(pair)

print(f"    含深度标准化: {len(all_pairs)} 对")

# 3c. 1N -> 1P+N
print("  3c. 1N vs 1P+N...")
for i in range(len(norms)):
    if '1N' not in norms[i]:
        continue
    replaced = norms[i].replace('1N', '1P+N')
    for j in range(len(norms)):
        if i == j:
            continue
        if norms[j] == replaced:
            pair = (min(i, j), max(i, j))
            if pair not in all_pairs:
                all_pairs.add(pair)

print(f"    含1N替换: {len(all_pairs)} 对")

# 3d. 模糊匹配 - 仅在同类别内，描述长度差≤2
print("  3d. 模糊匹配...")
from rapidfuzz import fuzz

fuzzy_count = 0
for cat, idxs in cat_indices.items():
    if len(idxs) < 2:
        continue
    
    # 按长度分桶 (桶大小=3)
    len_buckets = defaultdict(list)
    for i in idxs:
        lb = len(descs[i]) // 3
        len_buckets[lb].append(i)
    
    # 检查相邻桶
    for lb in sorted(len_buckets.keys()):
        bucket_indices = len_buckets[lb]
        # Also check adjacent bucket
        if lb + 1 in len_buckets:
            bucket_indices = bucket_indices + len_buckets[lb + 1]
        
        n = len(bucket_indices)
        if n > 2000:
            # Too many, skip fuzzy for this bucket
            continue
        
        for a in range(n):
            da = descs[bucket_indices[a]]
            la = len(da)
            if la < 3:
                continue
            for b in range(a + 1, n):
                db = descs[bucket_indices[b]]
                lb2 = len(db)
                if abs(la - lb2) > 3:
                    continue
                
                ia, ib = bucket_indices[a], bucket_indices[b]
                pair = (min(ia, ib), max(ia, ib))
                if pair in all_pairs:
                    continue
                
                # Quick check: same first 5 chars
                if la >= 5 and lb2 >= 5 and da[:5] != db[:5]:
                    continue
                
                ratio = fuzz.ratio(da, db)
                if ratio >= 90:
                    all_pairs.add(pair)
                    fuzzy_count += 1

print(f"    模糊匹配新增: {fuzzy_count} 对")
print(f"  总可疑重复: {len(all_pairs)} 对")
print(f"  耗时: {time.time()-start:.1f}s")

# 4. 规则分类
print("\nStep 3: 规则分类...")

def apply_rules(i, j):
    ra = data.iloc[i]
    rb = data.iloc[j]
    da, db = str(ra['物料描述']), str(rb['物料描述'])
    na, nb = str(ra['物料名称']), str(rb['物料名称'])
    ma, mb = str(ra['制造商']), str(rb['制造商'])
    sa, sb = str(ra['物料子类别']), str(rb['物料子类别'])
    wa, wb = str(ra['物料来源']), str(rb['物料来源'])
    
    # 规则1: 甲供件
    for s in [sa, sb, wa, wb, da, db]:
        if '甲供' in s:
            return 'non_dup', '甲供件（规则1）'
    
    # 规则2: 一方有制造商一方无
    hma, hmb = bool(ma), bool(mb)
    if hma != hmb:
        return 'non_dup', '一方有制造商一方无（规则2）'
    
    # 规则3: 安装方向
    for pa, pb in [('左操','右操'),('平进平出','平进侧出'),('上进','下进'),('上进下出','下进上出'),('左进','右进'),('左出','右出')]:
        if (pa in da and pb in db) or (pb in da and pa in db):
            return 'non_dup', f'安装方向不同（规则3）'
    
    # 规则4: 分断能力
    for pfx in ['CDM3','CM3','CDM3E','CM3E']:
        m1 = re.search(f'({pfx}-\\d+)([FCDHLMSN])', da)
        m2 = re.search(f'({pfx}-\\d+)([FCDHLMSN])', db)
        if m1 and m2 and m1.group(1)==m2.group(1) and m1.group(2)!=m2.group(2):
            return 'non_dup', f'分断能力不同（规则4）'
    
    # 规则5: 脱扣曲线
    for pat in [r'(\d+[AP])\s*([BCD])\b', r'C(\d+)([BCD])\b']:
        m1, m2 = re.search(pat, da), re.search(pat, db)
        if m1 and m2:
            b1, b2 = ''.join(m1.groups()[:-1]), ''.join(m2.groups()[:-1])
            if b1 == b2 and m1.group()[-1] != m2.group()[-1]:
                return 'non_dup', f'脱扣曲线不同（规则5）'
    
    # 规则6: 极数
    for pa, pb in [('1P+N','2P'),('1P','2P'),('3P','4P'),('2P','3P'),('1P+N','1P')]:
        if (pa in da and pb in db) or (pb in da and pa in db):
            return 'non_dup', f'极数不同（规则6）'
    
    # 规则7: 颜色
    cws = ['灰色','棕色','红色','黑色','白色','蓝色','绿色','黄色','橙色']
    for cw in cws:
        if cw in da and cw not in db:
            for cw2 in cws:
                if cw2 in db and cw2 not in da:
                    return 'non_dup', f'颜色不同（规则7）'
    
    # 规则8: 漏电类型
    if ('A型' in da and 'AC型' in db) or ('AC型' in da and 'A型' in db):
        return 'non_dup', '漏电保护类型不同（规则8）'
    
    # 规则9: 附件
    accs = ['失压','辅助','报警','门框','电磁锁','分励']
    if any(a in da for a in accs) != any(a in db for a in accs):
        return 'non_dup', '带附件vs不带（规则9）'
    
    # 规则10: 互感器
    if '互感器' in na or '互感器' in nb:
        pa, pb = re.findall(r'([\d.]+)级', da), re.findall(r'([\d.]+)级', db)
        if pa and pb and set(pa)!=set(pb):
            return 'non_dup', '互感器精度不同（规则10）'
        ra2, rb2 = re.findall(r'(\d+/\d+)', da), re.findall(r'(\d+/\d+)', db)
        if ra2 and rb2 and set(ra2)!=set(rb2):
            return 'non_dup', '互感器变比不同（规则10）'
    
    # 规则11: 电线类型
    wts = ['BV','BVR','ZR-YJV','YJV','NH-YJV','WDZA-YJY','WDZ-YJY','WDZB-YJY','WDZN-YJY','WDZA-YJV','WDZ-YJV','RVV','RVVP','KVV','KVVP','KVVRP','YJV22','NH-YJV22','VV22']
    for wt in wts:
        if wt in da and wt not in db:
            for wt2 in wts:
                if wt2 in db and wt2 not in da:
                    return 'non_dup', f'电线类型不同（规则11）'
    
    # 规则12: 保护类型
    pts = ['变压器保护','线路保护','电容器保护','电动机保护','发电机保护']
    pa, pb = [p for p in pts if p in da], [p for p in pts if p in db]
    if pa and pb and pa!=pb:
        return 'non_dup', f'保护类型不同（规则12）'
    
    # 规则13: 螺纹
    for pa, pb in [('正牙','反牙'),('右旋','左旋')]:
        if (pa in da and pb in db) or (pb in da and pa in db):
            return 'non_dup', f'螺纹方向不同（规则13）'
    
    # 规则14: 版本
    va, vb = re.findall(r'\b(\d+[A-Za-z])\b', da), re.findall(r'\b(\d+[A-Za-z])\b', db)
    if va and vb and set(va)!=set(vb):
        na2 = re.sub(r'\b\d+[A-Za-z]\b','X',da)
        nb2 = re.sub(r'\b\d+[A-Za-z]\b','X',db)
        if normalize(na2)==normalize(nb2):
            return 'non_dup', f'版本不同（规则14）'
    
    # 规则15: 脱扣方式
    for pa, pb in [('TMD','MA'),('热磁','仅电磁')]:
        if (pa in da and pb in db) or (pb in da and pa in db):
            return 'non_dup', f'脱扣方式不同（规则15）'
    
    # 规则16: 脱扣单元
    for pa, pb in [('LSI','TMA'),('LSI','LI'),('LSI','LPI'),('TMF','MA')]:
        if (pa in da and pb in db) or (pb in da and pa in db):
            return 'non_dup', f'脱扣单元不同（规则16）'
    
    # 规则17: 配件
    parts = ['安全挂锁','相间隔板','防护罩','灭弧罩','手柄','操作机构']
    pa, pb = [p for p in parts if p in da], [p for p in parts if p in db]
    if pa and pb and pa!=pb:
        return 'non_dup', f'配件不同（规则17）'
    
    # 规则18: 过电压保护器
    m1, m2 = re.search(r'(TBP-[A-Z])', da), re.search(r'(TBP-[A-Z])', db)
    if m1 and m2 and m1.group(1)!=m2.group(1):
        return 'non_dup', f'过电压保护器型号不同（规则18）'
    
    # 规则19: 型号系列
    for pa, pb in [('CM3E','CM3'),('CDM3E','CDM3'),('NSX','NS'),('EZD','EZF')]:
        if (pa in da and pb in db) or (pb in da and pa in db):
            return 'non_dup', f'型号系列不同（规则19）'
    
    # 规则20: RV vs BVR/BV
    for pa, pb in [('RV','BVR'),('RV','BV')]:
        if (pa in da and pb in db) or (pb in da and pa in db):
            return 'non_dup', f'电线类型不同（规则20）'
    
    # 确认重复: 标准化后相同
    if norms[i] == norms[j] or deeps[i] == deeps[j]:
        reason = '描述标准化后完全相同' if norms[i]==norms[j] else '描述深度标准化后相同'
        return 'dup', reason
    
    # 确认重复: 1N vs 1P+N
    na_r = norms[i].replace('1N','1P+N')
    if na_r == norms[j]:
        return 'dup', '1N vs 1P+N'
    
    # 确认重复: 同前缀+同制造商
    ca, cb = str(ra['物料编号']), str(rb['物料编号'])
    pa2, pb2 = re.match(r'([A-Za-z]+)', ca), re.match(r'([A-Za-z]+)', cb)
    if pa2 and pb2 and pa2.group(1)==pb2.group(1) and ma==mb and ma:
        return 'dup', f'同前缀{pa2.group(1)}+同制造商'
    
    return 'pending', ''

confirmed_dup = []
non_dup = []
pending_pairs = []

for ia, ib in all_pairs:
    cat, reason = apply_rules(ia, ib)
    
    ra = data.iloc[ia]
    rb = data.iloc[ib]
    
    info = {
        'idx_a': ia, 'idx_b': ib,
        'reason': reason,
        'ra': {k: ra[k] for k in key_cols},
        'rb': {k: rb[k] for k in key_cols},
    }
    
    if cat == 'non_dup':
        non_dup.append(info)
    elif cat == 'dup':
        confirmed_dup.append(info)
    else:
        pending_pairs.append(info)

print(f"  确认重复: {len(confirmed_dup)}")
print(f"  非重复: {len(non_dup)}")
print(f"  待人工确认: {len(pending_pairs)}")
print(f"  耗时: {time.time()-start:.1f}s")

# 5. 保存
pd_data = []
for p in pending_pairs:
    ra, rb = p['ra'], p['rb']
    pd_data.append({
        'idx_a': p['idx_a'], 'idx_b': p['idx_b'],
        'desc_a': ra['物料描述'], 'desc_b': rb['物料描述'],
        'code_a': ra['物料编号'], 'code_b': rb['物料编号'],
        'name_a': ra['物料名称'], 'name_b': rb['物料名称'],
        'mfr_a': ra['制造商'], 'mfr_b': rb['制造商'],
        'cat': ra['物料类别'],
        'subcat_a': ra['物料子类别'], 'subcat_b': rb['物料子类别'],
        'source_a': ra['物料来源'], 'source_b': rb['物料来源'],
        'price_a': ra['标准价格'], 'price_b': rb['标准价格'],
        'unit_a': ra['主计量单位'], 'unit_b': rb['主计量单位'],
        'lead_a': ra['提前期'], 'lead_b': rb['提前期'],
    })

with open('IN3数据/pending_pairs.json', 'w', encoding='utf-8') as f:
    json.dump(pd_data, f, ensure_ascii=False, indent=2)

with open('IN3数据/classified_pairs.pkl', 'wb') as f:
    pickle.dump({
        'confirmed_dup': confirmed_dup,
        'non_dup': non_dup,
        'pending': pending_pairs,
        'data': data,
    }, f)

summary = {
    'total_materials': len(data),
    'total_suspicious': len(all_pairs),
    'confirmed_dup': len(confirmed_dup),
    'non_dup': len(non_dup),
    'pending': len(pending_pairs),
}
with open('IN3数据/classification_summary.json', 'w', encoding='utf-8') as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)

print(f"\n✓ 分析完成!")
print(f"  物料总数: {len(data)}")
print(f"  可疑重复对: {len(all_pairs)}")
print(f"  确认重复: {len(confirmed_dup)}")
print(f"  非重复: {len(non_dup)}")
print(f"  待人工确认: {len(pending_pairs)}")
print(f"  总耗时: {time.time()-start:.1f}s")
