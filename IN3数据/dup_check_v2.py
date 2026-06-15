#!/usr/bin/env python3
"""
IN3 物料重复检查 v2 - 高效版
- 策略：同名物料中，按描述精确匹配+排除规则分类
- 不做名称相似度匹配（太慢），只做同名匹配
- 大组按描述+制造商分组后再配对
"""
import pandas as pd
import numpy as np
import re
import json
import sys
from difflib import SequenceMatcher
from collections import defaultdict
import time

print(f"[{time.strftime('%H:%M:%S')}] 开始物料重复检查...", flush=True)

# ====== 1. 读取数据 ======
INPUT_FILE = '物料主数据导出结果-20260905161742956.xlsx'
df = pd.read_excel(INPUT_FILE, sheet_name='物料主数据')
print(f"总物料数: {len(df)}, 列数: {len(df.columns)}", flush=True)

# ====== 2. 过滤 ======
CATEGORIES_TO_CHECK = ['电器元件', '辅材', '结构件', '紧固件', '工、器具', '机械配件', '气动配件', '钢材原料', '外购成套']
df_check = df[df['物料类别'].isin(CATEGORIES_TO_CHECK)].copy()
print(f"检查范围: {len(df_check)} 条物料（排除成品柜 {len(df) - len(df_check)} 条）", flush=True)

# ====== 3. 数据清洗 ======
def clean_text(s):
    if pd.isna(s):
        return ''
    s = str(s).strip()
    s = s.replace('\u3000', '').replace('\xa0', '')
    s = re.sub(r'\s+', ' ', s)
    return s

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

# 按 (名称, 描述) 分组，找出描述完全相同的物料对
desc_groups = defaultdict(list)
for idx in df_check.index:
    key = (df_check.loc[idx, '_name'], df_check.loc[idx, '_desc'])
    if key[0] and key[1]:
        desc_groups[key].append(idx)

print(f"唯一 (名称,描述) 组合数: {len(desc_groups)}", flush=True)

# 只保留有多个物料的组合（即同名同描述的多条物料）
dup_desc_groups = {k: v for k, v in desc_groups.items() if len(v) > 1}
print(f"同名同描述的多物料组数: {len(dup_desc_groups)}", flush=True)

# 生成候选对
candidate_pairs = []
for key, indices in dup_desc_groups.items():
    for i in range(len(indices)):
        for j in range(i+1, len(indices)):
            candidate_pairs.append((indices[i], indices[j]))

print(f"同名同描述候选对数: {len(candidate_pairs)}", flush=True)

# 额外：同名不同描述但描述高度相似的（仅对小组做）
name_groups = defaultdict(list)
for idx in df_check.index:
    name = df_check.loc[idx, '_name']
    if name:
        name_groups[name].append(idx)

# 对同名的物料，如果描述不完全相同但很相似
similar_pairs = 0
for name, indices in name_groups.items():
    if len(indices) < 2 or len(indices) > 200:
        continue
    # 按描述分组
    desc_map = defaultdict(list)
    for idx in indices:
        desc = df_check.loc[idx, '_desc']
        desc_map[desc].append(idx)
    # 不同描述组之间比较
    unique_descs = list(desc_map.keys())
    if len(unique_descs) <= 1:
        continue  # 已经在上面处理了
    for i in range(len(unique_descs)):
        for j in range(i+1, len(unique_descs)):
            d1, d2 = unique_descs[i], unique_descs[j]
            if not d1 or not d2:
                continue
            ratio = SequenceMatcher(None, d1, d2).ratio()
            if ratio > 0.85:
                for ia in desc_map[d1]:
                    for ib in desc_map[d2]:
                        pair = (min(ia, ib), max(ia, ib))
                        if pair not in candidate_pairs:
                            candidate_pairs.append(pair)
                            similar_pairs += 1

print(f"相似描述新增候选对数: {similar_pairs}", flush=True)
print(f"总候选对数: {len(candidate_pairs)}", flush=True)

# ====== 5. 规则分类 ======
print(f"[{time.strftime('%H:%M:%S')}] 规则分类...", flush=True)

def classify_pair(a, b):
    if a['id'] == b['id']:
        return ('same_item', '物料编号相同')
    if '甲供' in a['source'] or '甲供' in b['source']:
        return ('not_dup', '甲供件不算重复')
    if (a['manufacturer'] and not b['manufacturer']) or (not a['manufacturer'] and b['manufacturer']):
        return ('not_dup', '制造商一有一无')
    dir_pairs = [('左操','右操'),('左侧','右侧'),('左进','右进'),('上进','下进'),
                 ('左进线','右进线'),('上进线','下进线'),('上出线','下出线')]
    for d1, d2 in dir_pairs:
        if (d1 in a['desc'] and d2 in b['desc']) or (d2 in a['desc'] and d1 in b['desc']):
            return ('not_dup', f'安装方向不同({d1}/{d2})')
    brk_a = re.findall(r'(\d+)\s*[kK][aA]', a['desc'])
    brk_b = re.findall(r'(\d+)\s*[kK][aA]', b['desc'])
    if brk_a and brk_b and set(brk_a) != set(brk_b):
        return ('not_dup', f'分断能力不同')
    for curve in ['B曲线','C曲线','D曲线','K曲线','Z曲线','B型','C型','D型','K型','Z型']:
        if (curve in a['desc']) != (curve in b['desc']):
            return ('not_dup', '脱扣曲线不同')
    pole_a = re.findall(r'(\d+)\s*[Pp]', a['desc'])
    pole_b = re.findall(r'(\d+)\s*[Pp]', b['desc'])
    if pole_a and pole_b and set(pole_a) != set(pole_b):
        return ('not_dup', f'极数不同')
    colors = ['红色','蓝色','绿色','黄色','白色','黑色','灰色','橙色']
    for c in colors:
        if (c in a['desc'] or c in a['name']) != (c in b['desc'] or c in b['name']):
            return ('not_dup', f'颜色不同')
    for lt in ['电磁式','电子式','AC型','A型']:
        if (lt in a['desc']) != (lt in b['desc']):
            return ('not_dup', f'漏电类型不同')
    if ('带' in a['desc'] and '不带' in b['desc']) or ('不带' in a['desc'] and '带' in b['desc']):
        return ('not_dup', '带附件vs不带')
    ratio_a = re.findall(r'(\d+)/(\d+)', a['desc'])
    ratio_b = re.findall(r'(\d+)/(\d+)', b['desc'])
    if ratio_a and ratio_b and set(ratio_a) != set(ratio_b):
        return ('not_dup', f'互感器变比不同')
    wire_types = ['BV','BVR','RVV','RVVP','KVV','KVVP','YJV','NH-YJV']
    for wt in wire_types:
        if (wt in a['desc']) != (wt in b['desc']):
            return ('not_dup', f'电线类型不同')
    ip_a = re.findall(r'IP\d+', a['desc'])
    ip_b = re.findall(r'IP\d+', b['desc'])
    if ip_a and ip_b and set(ip_a) != set(ip_b):
        return ('not_dup', f'保护等级不同')
    if ('左旋' in a['desc'] and '右旋' in b['desc']) or ('右旋' in a['desc'] and '左旋' in b['desc']):
        return ('not_dup', '螺纹方向不同')
    model_a = re.match(r'^([A-Za-z][A-Za-z0-9\-]+)', a['desc'])
    model_b = re.match(r'^([A-Za-z][A-Za-z0-9\-]+)', b['desc'])
    if model_a and model_b and model_a.group(1) != model_b.group(1):
        return ('not_dup', f'型号系列不同')
    cur_a = re.findall(r'(\d+)\s*[Aa]', a['desc'])
    cur_b = re.findall(r'(\d+)\s*[Aa]', b['desc'])
    if cur_a and cur_b and set(cur_a) != set(cur_b):
        return ('not_dup', f'额定电流不同')
    # 通过所有排除规则
    if a['desc'] == b['desc'] and a['name'] == b['name']:
        if a['manufacturer'] == b['manufacturer']:
            return ('likely_dup', '名称描述制造商均相同')
        else:
            return ('likely_dup', '名称描述相同制造商不同')
    return ('likely_dup', f'描述高度相似')

categories = defaultdict(list)
for idx_a, idx_b in candidate_pairs:
    a = {
        'id': df_check.loc[idx_a, '*物料编号'],
        'name': df_check.loc[idx_a, '_name'],
        'desc': df_check.loc[idx_a, '_desc'],
        'category': df_check.loc[idx_a, '_category'],
        'subcategory': df_check.loc[idx_a, '_subcategory'],
        'manufacturer': df_check.loc[idx_a, '_manufacturer'],
        'source': df_check.loc[idx_a, '_source'],
        'unit': df_check.loc[idx_a, '_unit'],
    }
    b = {
        'id': df_check.loc[idx_b, '*物料编号'],
        'name': df_check.loc[idx_b, '_name'],
        'desc': df_check.loc[idx_b, '_desc'],
        'category': df_check.loc[idx_b, '_category'],
        'subcategory': df_check.loc[idx_b, '_subcategory'],
        'manufacturer': df_check.loc[idx_b, '_manufacturer'],
        'source': df_check.loc[idx_b, '_source'],
        'unit': df_check.loc[idx_b, '_unit'],
    }
    cat, reason = classify_pair(a, b)
    categories[cat].append({'a': a, 'b': b, 'reason': reason})

print(f"\n=== 分类结果 ===", flush=True)
total_classified = 0
for cat, pairs in sorted(categories.items(), key=lambda x: -len(x[1])):
    print(f"  {cat}: {len(pairs)} 对", flush=True)
    total_classified += len(pairs)

print(f"\n  总计分类: {total_classified} 对", flush=True)

# 保存
with open('classification_summary_v2.json', 'w', encoding='utf-8') as f:
    json.dump({cat: len(pairs) for cat, pairs in categories.items()}, f, ensure_ascii=False, indent=2)

# 保存确认重复对
dup_pairs = categories.get('likely_dup', [])
with open('confirmed_dup_pairs_v2.json', 'w', encoding='utf-8') as f:
    json.dump(dup_pairs, f, ensure_ascii=False, indent=2)

# 保存非重复对（含排除原因）
not_dup = categories.get('not_dup', [])
with open('not_dup_pairs_v2.json', 'w', encoding='utf-8') as f:
    json.dump(not_dup, f, ensure_ascii=False, indent=2)

print(f"\n[{time.strftime('%H:%M:%S')}] 分析完成！", flush=True)
print(f"  ✅ 确认重复: {len(dup_pairs)} 对", flush=True)
print(f"  ❌ 非重复（规则排除）: {len(not_dup)} 对", flush=True)
