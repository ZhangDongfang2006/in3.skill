#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import re
import os

def normalize_name(name):
    """标准化物料名称，去掉常见公司后缀"""
    if not name:
        return ""
    name = str(name).strip()
    # 去掉常见公司后缀
    suffixes = ["有限公司", "(中国)", "股份", "有限责任公司", "集团", "公司"]
    for suffix in suffixes:
        name = name.replace(suffix, "")
    return name.strip()

def find_pairs(materials):
    """查找可能的重复配对"""
    pairs = []
    used_indices = set()
    
    # 按物料名称分组
    name_groups = {}
    for i, mat in enumerate(materials):
        if mat.get('物料名称'):
            name = mat['物料名称']
            if name not in name_groups:
                name_groups[name] = []
            name_groups[name].append(i)
    
    # 在同名组内查找重复
    for name, indices in name_groups.items():
        if len(indices) > 1:
            for i in range(len(indices)):
                for j in range(i + 1, len(indices)):
                    if indices[i] not in used_indices and indices[j] not in used_indices:
                        pairs.append((materials[indices[i]], materials[indices[j]]))
                        used_indices.add(indices[i])
                        used_indices.add(indices[j])
    
    # 按描述查找可能的重复
    desc_groups = {}
    for i, mat in enumerate(materials):
        if i not in used_indices and mat.get('物料描述'):
            desc = mat['物料描述']
            if desc not in desc_groups:
                desc_groups[desc] = []
            desc_groups[desc].append(i)
    
    # 在同描述组内查找重复
    for desc, indices in desc_groups.items():
        if len(indices) > 1:
            for i in range(len(indices)):
                for j in range(i + 1, len(indices)):
                    if indices[i] not in used_indices and indices[j] not in used_indices:
                        pairs.append((materials[indices[i]], materials[indices[j]]))
                        used_indices.add(indices[i])
                        used_indices.add(indices[j])
    
    return pairs

def load_materials(file_path):
    """加载物料数据"""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(file_path)
        ws = wb.active
        
        materials = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            if row[0]:  # 假设第一列是物料编号
                material = {
                    '物料编号': row[0],
                    '物料名称': row[1],
                    '物料描述': row[2],
                    '物料类别': row[3],
                    '物料子类别': row[4],
                    '制造商': row[5],
                    '物料来源': row[6],
                    '提前期': row[7],
                    '主计量单位': row[8],
                    '标准价格': row[9],
                    '创建人': row[10],
                    '创建日期': row[11],
                    '最近修改人': row[12],
                    '最近修改日期': row[13],
                    '备注': row[14] if len(row) > 14 else None
                }
                materials.append(material)
        
        return materials
    except Exception as e:
        print(f"加载物料数据失败: {e}")
        return []

def main():
    """主函数"""
    # 找最新导出文件
    data_dir = 'IN3数据'
    pattern = re.compile(r'物料主数据导出结果.*\.xlsx$')
    candidates = [(os.path.getmtime(os.path.join(data_dir, f)), os.path.join(data_dir, f)) 
                 for f in os.listdir(data_dir) if pattern.match(f) and 'v2' not in f.lower()]
    candidates.sort(reverse=True)
    
    if not candidates:
        print("没有找到导出文件")
        return
    
    latest = candidates[0][1]
    print(f'加载: {latest}')
    
    materials = load_materials(latest)
    pairs = find_pairs(materials)
    print(f'候选配对: {len(pairs)} 对')
    
    # 输出为 JSON 供 AI 审查
    output = []
    for a, b in pairs:
        output.append({
            'A': {k: v for k, v in a.items()},
            'B': {k: v for k, v in b.items()}
        })
    
    out_file = os.path.join(data_dir, 'candidate_pairs.json')
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f'已保存候选配对到: {out_file}')

if __name__ == '__main__':
    main()