#!/usr/bin/env python3
"""
AI 批量审查物料重复候选对
读取 ai_review_candidates_0601.json，逐批发送给 AI 模型判断，
输出结果到 ai_review_results_0601.json
"""
import json
import os
import sys
import time

BATCH_SIZE = 100
INPUT_FILE = sys.argv[1] if len(sys.argv) > 1 else 'ai_review_candidates_0601.json'
OUTPUT_FILE = INPUT_FILE.replace('.json', '_results.json')

SYSTEM_PROMPT = """你是电气设备物料重复检查专家。你的任务是判断每对物料是否重复。

## 判断规则（严格遵守）

### 非重复规则（只要满足任一条 = 非重复）：
1. 型号中任何数字或字母不同，且该差异代表具体规格参数（电流、电压、尺寸、分断能力、极数、脱扣曲线、脱扣方式等）= 非重复
   - 例：NSX160**H** vs NSX160**F**（H/F是分断能力等级不同）
   - 例：NDM2-250**L** vs NDM2-250**C**（L/C是分断能力不同）
   - 例：5SY4 2P **C**20 vs 5SY4 2P **D**20（C/D是脱扣曲线不同）
   - 例：RMM1-160**S** vs RMM1-160**H**（S/H/N是分断能力不同）
   - 例：NDBHLE-63/4P/**C**16A vs NDBHLE-63/4P/**D**16A（C/D脱扣曲线不同）
2. 制造商不同（两者都有制造商且不是同一家）= 非重复
3. 极数不同 = 非重复
4. 额定电流/电压数值不同 = 非重复
5. 漏电类型不同（AC型/A型等）= 非重复
6. 脱扣方式不同（热磁式 vs 电磁式/MA vs TMD）= 非重复
7. 附件配置不同（带辅助/报警/分励 vs 不带）= 非重复
8. 安装方式不同（固定式 vs 插入式/抽屉式）= 非重复
9. 接线方式不同（板前/板后/前置）= 非重复
10. 表面处理不同 = 非重复
11. 材质不同 = 非重复
12. 颜色不同 = 非重复
13. 尺寸数值不同 = 非重复

### 确认重复规则（只有以下情况 = 确认重复）：
- 描述仅格式差异：空格/大小写/全角半角/连字符/斜杠/括号样式/分隔符差异
- 型号完全相同，仅表述方式不同（如 "NSX100F TMD F 63 3P/" vs "NSX100F TMD 63A 3P"，型号核心参数完全一致）
- 仅计量单位标注差异（如 "25KG/支" vs "25KG"）

### 待人工确认：
- 名称不同但可能是同一种东西（如接触器 vs 交流接触器）
- 无法确定型号中某个字母是否代表规格差异

## 输出格式
对每对返回 JSON 数组，每个元素：
{"index": N, "verdict": "dup"|"nondup"|"unsure", "reason": "简短原因"}

只返回 JSON 数组，不要其他文字。"""

def load_candidates():
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_results(results):
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

def format_batch(batch, start_idx):
    """Format a batch of pairs for AI review"""
    lines = []
    for i, c in enumerate(batch):
        idx = start_idx + i
        lines.append(f"#{idx}")
        lines.append(f"A: [{c['a']['code']}] {c['a']['name']} | 描述: {c['a']['desc']} | 制造商: {c['a']['mfr']}")
        lines.append(f"B: [{c['b']['code']}] {c['b']['name']} | 描述: {c['b']['desc']} | 制造商: {c['b']['mfr']}")
        lines.append("")
    return '\n'.join(lines)

def call_ai(prompt):
    """Call AI model via subprocess using OpenClaw's model"""
    import subprocess
    # Use a simple approach: write prompt to temp file and use curl
    # Actually, we'll use the openai-compatible API
    try:
        import urllib.request
        import json as j
        
        # We'll write the prompt to a file and let the caller process it
        return None
    except Exception as e:
        print(f"Error calling AI: {e}", file=sys.stderr)
        return None

def process_with_rules_only(candidates):
    """Fallback: apply comprehensive rule-based filtering"""
    import re
    
    results = []
    for i, c in enumerate(candidates):
        a, b = c['a'], c['b']
        da, db = a['desc'], b['desc']
        na, nb = a['name'], b['name']
        ma, mb = a['mfr'], b['mfr']
        
        verdict = "unsure"
        reason = ""
        
        # Check manufacturer difference
        if ma and mb and ma != mb:
            # Normalize
            def norm_mfr(s):
                return s.replace('（中国）有限公司','').replace('(中国)有限公司','').replace('有限公司','').replace('股份','').replace('有限责任','')
            if norm_mfr(ma) != norm_mfr(mb) and not (norm_mfr(ma) in norm_mfr(mb) or norm_mfr(mb) in norm_mfr(ma)):
                verdict = "nondup"
                reason = f"制造商不同: {ma} vs {mb}"
                results.append({"index": i, "verdict": verdict, "reason": reason})
                continue
        
        # Extract model numbers and compare
        # For common patterns like NSX160H, NDM2-250L, RMM1-160S
        # The letter after the number often indicates breaking capacity
        model_patterns = [
            # NSX/NSE/NS pattern: NSX###X where X=F/H/N/S
            (r'(NSX?[\s-]*\d+)([FHNS])', r'(NSX?[\s-]*\d+)([FHNS])'),
            # NDM2 pattern: NDM2-###X
            (r'(NDM2-\d+)([CFHLMNS])', r'(NDM2-\d+)([CFHLMNS])'),
            # BM3 pattern: BM3-###X
            (r'(BM3-\d+)([LM])', r'(BM3-\d+)([LM])'),
            # NXM pattern: NXM-###X
            (r'(NXM-?\d+)([SHN])', r'(NXM-?\d+)([SHN])'),
            # RMM1 pattern: RMM1-###X
            (r'(RMM1-\d+)([SFHN])', r'(RMM1-\d+)([SFHN])'),
            # D1N/D1C/D3N/D3C/D3S
            (r'(D[13])([NCS])', r'(D[13])([NCS])'),
            # 3VC8 pattern
            (r'(3VC8)', r'(3VC8)'),
        ]
        
        found_diff = False
        for pa, pb in model_patterns:
            ma_match = re.search(pa, da)
            mb_match = re.search(pb, db)
            if ma_match and mb_match:
                # Check if prefix matches but suffix differs
                if len(ma_match.groups()) >= 2 and len(mb_match.groups()) >= 2:
                    if ma_match.group(1) == mb_match.group(1) and ma_match.group(2) != mb_match.group(2):
                        verdict = "nondup"
                        reason = f"型号中分断能力/等级不同: {ma_match.group(0)} vs {mb_match.group(0)}"
                        found_diff = True
                        break
        
        if found_diff:
            results.append({"index": i, "verdict": verdict, "reason": reason})
            continue
        
        # Check trip curve: C vs D
        c_in_a = re.findall(r'\bC(\d+)A?\b', da)
        d_in_a = re.findall(r'\bD(\d+)A?\b', da)
        c_in_b = re.findall(r'\bC(\d+)A?\b', db)
        d_in_b = re.findall(r'\bD(\d+)A?\b', db)
        
        if c_in_a and d_in_b and c_in_a == d_in_b:
            verdict = "nondup"
            reason = f"脱扣曲线不同: C型 vs D型 (电流{c_in_a[0]}A)"
            results.append({"index": i, "verdict": verdict, "reason": reason})
            continue
        if d_in_a and c_in_b and d_in_a == c_in_b:
            verdict = "nondup"
            reason = f"脱扣曲线不同: D型 vs C型 (电流{d_in_a[0]}A)"
            results.append({"index": i, "verdict": verdict, "reason": reason})
            continue
        
        # Check trip method: TMD vs MA, 热磁 vs 电磁
        if ('TMD' in da and 'MA' in db) or ('MA' in da and 'TMD' in db):
            verdict = "nondup"
            reason = "脱扣方式不同: TMD(热磁) vs MA(仅电磁)"
            results.append({"index": i, "verdict": verdict, "reason": reason})
            continue
        if '热磁式' in da and '电磁式' in db:
            verdict = "nondup"
            reason = "脱扣方式不同: 热磁式 vs 电磁式"
            results.append({"index": i, "verdict": verdict, "reason": reason})
            continue
        if '电磁式' in da and '热磁式' in db:
            verdict = "nondup"
            reason = "脱扣方式不同: 电磁式 vs 热磁式"
            results.append({"index": i, "verdict": verdict, "reason": reason})
            continue
        
        # Check accessories difference
        acc_keywords = ['辅助', '报警', '分励', 'OF', 'SOR', 'MX', 'MN', '门框', '电磁锁', '相间隔板']
        a_has_acc = any(kw in da for kw in acc_keywords)
        b_has_acc = any(kw in db for kw in acc_keywords)
        if a_has_acc != b_has_acc:
            verdict = "nondup"
            a_acc = [kw for kw in acc_keywords if kw in da]
            b_acc = [kw for kw in acc_keywords if kw in db]
            reason = f"附件配置不同: A有{a_acc}, B有{b_acc}"
            results.append({"index": i, "verdict": verdict, "reason": reason})
            continue
        
        # Check installation: 固定式 vs 插入式
        if ('固定式' in da and '插入式' in db) or ('插入式' in da and '固定式' in db):
            verdict = "nondup"
            reason = "安装方式不同: 固定式 vs 插入式"
            results.append({"index": i, "verdict": verdict, "reason": reason})
            continue
        
        # Check wiring: 板前 vs 板后
        if ('板前' in da and '板后' in db) or ('板后' in da and '板前' in db):
            verdict = "nondup"
            reason = "接线方式不同: 板前 vs 板后"
            results.append({"index": i, "verdict": verdict, "reason": reason})
            continue
        
        # Check leakage type
        if 'AC型' in da and 'AC型' not in db and 'A型' not in db:
            # One specifies AC type, other doesn't - could be omission
            verdict = "unsure"
            reason = "漏电类型标注差异: AC型 vs 无标注"
        elif 'A型' in da and 'AC型' in db:
            verdict = "nondup"
            reason = "漏电类型不同: A型 vs AC型"
        
        # Default: still needs AI review
        if verdict == "unsure":
            reason = reason or "需AI审查"
        
        results.append({"index": i, "verdict": verdict, "reason": reason})
    
    return results

if __name__ == '__main__':
    candidates = load_candidates()
    print(f'Loaded {len(candidates)} candidates')
    
    # Apply enhanced rules first
    results = process_with_rules_only(candidates)
    
    # Count
    dup_count = sum(1 for r in results if r['verdict'] == 'dup')
    nondup_count = sum(1 for r in results if r['verdict'] == 'nondup')
    unsure_count = sum(1 for r in results if r['verdict'] == 'unsure')
    
    print(f'Rule-based results:')
    print(f'  Confirmed dup: {dup_count}')
    print(f'  Non-dup: {nondup_count}')
    print(f'  Still unsure (need AI): {unsure_count}')
    
    # Save results
    save_results(results)
    
    # Save unsure ones for actual AI processing
    unsure_pairs = [candidates[r['index']] for r in results if r['verdict'] == 'unsure']
    unsure_file = INPUT_FILE.replace('.json', '_unsure.json')
    with open(unsure_file, 'w', encoding='utf-8') as f:
        json.dump(unsure_pairs, f, ensure_ascii=False)
    print(f'Saved {len(unsure_pairs)} unsure pairs to {unsure_file}')
