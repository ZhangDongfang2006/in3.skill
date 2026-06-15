#!/usr/bin/env python3
"""AI review of pending pairs - 20260610"""
import json

with open('IN3数据/pending_review_20260610.json', 'r', encoding='utf-8') as f:
    pending = json.load(f)

confirmed = []
excluded = []
still_pending = []

for i, pair in enumerate(pending):
    a, b = pair['A'], pair['B']
    a_code = a.get('物料编号', '')
    b_code = b.get('物料编号', '')
    a_name = a.get('物料名称', '')
    b_name = b.get('物料名称', '')
    a_desc = (a.get('物料描述', '') or '').strip()
    b_desc = (b.get('物料描述', '') or '').strip()
    a_mfr = (a.get('制造商', '') or '').strip()
    b_mfr = (b.get('制造商', '') or '').strip()
    
    idx = i + 1
    reason = ''
    verdict = 'pending'
    
    if idx == 1:
        verdict = 'confirmed'; reason = '描述差异仅"独立式"附加标注，同制造商'
    elif idx == 2:
        verdict = 'confirmed'; reason = '描述差异仅"二级能效"附加标注'
    elif idx == 3:
        verdict = 'confirmed'; reason = '描述差异仅"二级能效"附加标注'
    elif idx == 4:
        verdict = 'confirmed'; reason = '描述差异仅"二级能效"附加标注'
    elif idx == 5:
        verdict = 'confirmed'; reason = '描述差异仅"二级能效"附加标注'
    elif idx == 6:
        verdict = 'confirmed'; reason = '描述差异仅"二级能效"附加标注'
    elif idx == 7:
        verdict = 'confirmed'; reason = '描述差异仅"二级能效"附加标注'
    elif idx == 8:
        verdict = 'confirmed'; reason = '描述差异仅"二级能效"附加标注'
    elif idx == 9:
        verdict = 'confirmed'; reason = '描述差异仅"带绕片"附加标注'
    elif idx == 10:
        verdict = 'confirmed'; reason = '描述差异仅"重型"附加标注'
    elif idx == 11:
        verdict = 'pending'; reason = 'RS712C(NGTC2) vs RS712(NGT2) 型号差异，需搜索确认'
    elif idx == 12:
        verdict = 'excluded'; reason = 'ZC-YJV为阻燃电缆 vs YJV为普通电缆，功能差异'
    elif idx == 13:
        verdict = 'pending'; reason = '安装方式差异（柜外操作 vs 无标注）'
    elif idx == 14:
        verdict = 'pending'; reason = '安装方式差异（柜外操作 vs 无标注）'
    elif idx == 15:
        verdict = 'excluded'; reason = '表面处理差异（镜面 vs 无），不同物料'
    elif idx == 16:
        verdict = 'excluded'; reason = '表面处理差异（镜面 vs 无），不同物料'
    elif idx == 17:
        verdict = 'confirmed'; reason = '描述差异仅"调到45A"设定说明'
    elif idx == 18:
        verdict = 'excluded'; reason = '加工形态差异（光轴 vs 无），不同物料'
    elif idx == 19:
        verdict = 'confirmed'; reason = '描述差异仅"套热缩"附加标注'
    elif idx == 20:
        verdict = 'confirmed'; reason = '描述差异仅"套热缩套管"附加标注'
    elif idx == 21:
        verdict = 'confirmed'; reason = '描述差异仅"套热缩套管"附加标注'
    elif idx == 22:
        verdict = 'confirmed'; reason = '描述差异仅"套热缩套管"附加标注'
    elif idx == 23:
        verdict = 'confirmed'; reason = '描述差异仅"套热缩套管"附加标注'
    elif idx == 24:
        verdict = 'confirmed'; reason = '描述差异仅"（足厚度）"质量标注'
    elif idx == 25:
        verdict = 'confirmed'; reason = '描述差异仅"AC型"漏电类型附加标注'
    elif idx == 26:
        verdict = 'excluded'; reason = '附件差异（配置相间隔板 vs 无）'
    elif idx == 27:
        verdict = 'excluded'; reason = '附件差异（配置相间隔板 vs 无）'
    elif idx == 28:
        verdict = 'excluded'; reason = '附件差异（配置相间隔板 vs 无）'
    elif idx == 29:
        verdict = 'excluded'; reason = '附件差异（配置相间隔板 vs 无）'
    elif idx == 30:
        verdict = 'pending'; reason = '3P/ vs 3P3D/ 规格差异，需搜索确认'
    elif idx == 31:
        verdict = 'pending'; reason = '型号后缀差异（P vs 无），需确认含义'
    elif idx == 32:
        verdict = 'excluded'; reason = '安装方式差异（普通 vs PR插拔式）'
    elif idx == 33:
        verdict = 'excluded'; reason = '安装方式差异（PR插拔式 vs 普通）'
    elif idx == 34:
        verdict = 'excluded'; reason = '附件/功能差异（无欠压 vs 有欠压瞬时）'
    elif idx == 35:
        verdict = 'excluded'; reason = '附件差异（无 vs 三锁两钥匙）'
    elif idx == 36:
        verdict = 'excluded'; reason = '附件差异（无ACS/H-CP-EXT vs 有）'
    elif idx == 37:
        verdict = 'excluded'; reason = '附件差异（有ACS/H-CP-EXT vs 无）'
    elif idx == 38:
        verdict = 'excluded'; reason = '附件差异（有ACS/H-CP-EXT vs 无）'
    elif idx == 39:
        verdict = 'pending'; reason = '型号后缀差异（3F vs 3），需搜索确认'
    elif idx == 40:
        verdict = 'excluded'; reason = '插座 vs 未标注，不同部件'
    elif idx == 41:
        verdict = 'excluded'; reason = '插头 vs 未标注，不同部件'
    elif idx == 42:
        verdict = 'excluded'; reason = '插座 vs 未标注，不同部件'
    elif idx == 43:
        verdict = 'excluded'; reason = '插头 vs 未标注，不同部件'
    elif idx == 44:
        verdict = 'pending'; reason = '附件差异（无配罩 vs 有配罩）'
    elif idx == 45:
        verdict = 'pending'; reason = '名称表述差异，需确认是否同一种油漆'
    elif idx == 46:
        verdict = 'pending'; reason = '型号后缀差异（-FD vs 无），需搜索确认'
    elif idx == 47:
        verdict = 'confirmed'; reason = '描述差异仅"（不带风机）"说明标注'
    elif idx == 48:
        verdict = 'excluded'; reason = '功能差异（无 vs 带双向计量功能及四象限）'
    elif idx == 49:
        verdict = 'excluded'; reason = '功能差异（无 vs 配一开关量输入）'
    elif idx == 50:
        verdict = 'pending'; reason = '规格后缀差异（II vs 无），需确认含义'
    elif idx == 51:
        verdict = 'excluded'; reason = '附件差异（带SD接点 vs 不带）'
    elif idx == 52:
        verdict = 'excluded'; reason = '附件差异（带SD接点 vs 不带）'
    elif idx == 53:
        verdict = 'excluded'; reason = '附件差异（带SD接点 vs 不带）'
    elif idx == 54:
        verdict = 'excluded'; reason = '附件差异（带SD接点 vs 不带）'
    elif idx == 55:
        verdict = 'excluded'; reason = '附件差异（带SD接点 vs 不带）'
    elif idx == 56:
        verdict = 'excluded'; reason = '附件差异（带SD接点 vs 不带）'
    elif idx == 57:
        verdict = 'confirmed'; reason = '描述差异仅"6kA"分断能力附加标注'
    elif idx == 58:
        verdict = 'confirmed'; reason = '格式差异（/2P vs 空格2P，C10A vs C10）'
    elif idx == 59:
        verdict = 'confirmed'; reason = '格式差异（/4P vs 空格4P，C63A vs C63）'
    elif idx == 60:
        verdict = 'excluded'; reason = '应用场景差异（普通 vs 煤改电专用）'
    elif idx == 61:
        verdict = 'excluded'; reason = '应用场景差异（普通 vs 煤改电专用）'
    elif idx == 62:
        verdict = 'pending'; reason = '型号后缀差异（NA vs 无），需搜索确认'
    elif idx == 63:
        verdict = 'pending'; reason = '型号后缀差异（NA vs 无），需搜索确认'
    elif idx == 64:
        verdict = 'pending'; reason = '型号后缀差异（NA vs 无），需搜索确认'
    elif idx == 65:
        verdict = 'excluded'; reason = '功能差异（抗干扰型 vs 普通）'
    elif idx == 66:
        verdict = 'excluded'; reason = '功能差异（抗干扰型 vs 普通）'
    elif idx == 67:
        verdict = 'excluded'; reason = '功能差异（抗干扰型 vs 普通）'
    elif idx == 68:
        verdict = 'excluded'; reason = '功能差异（抗干扰型 vs 普通）'
    elif idx == 69:
        verdict = 'confirmed'; reason = '描述差异仅"10VA"容量附加标注'
    elif idx == 70:
        verdict = 'excluded'; reason = '功能差异（抗晃电 vs 无）'
    elif idx == 71:
        verdict = 'excluded'; reason = '功能差异（抗晃电 vs 无）'
    elif idx == 72:
        verdict = 'excluded'; reason = '功能/试验差异（无 vs 老练试验 切电容）'
    elif idx == 73:
        verdict = 'excluded'; reason = '功能/试验差异（无 vs 灭弧室老炼）'
    elif idx == 74:
        verdict = 'excluded'; reason = '内容差异（止步高压危险 vs 高压危险）'
    elif idx == 75:
        verdict = 'excluded'; reason = '内容差异（变压器室高压危险 vs 高压危险）'
    elif idx == 76:
        verdict = 'excluded'; reason = '内容差异（高压室高压危险 vs 高压危险）'
    elif idx == 77:
        verdict = 'excluded'; reason = '内容差异（低压室有电危险 vs 有电危险）'
    elif idx == 78:
        verdict = 'excluded'; reason = '附件差异（无 vs TFK配相间隔板）'
    elif idx == 79:
        verdict = 'excluded'; reason = '附件差异（TFK配相间隔板 vs 无）'
    elif idx == 80:
        verdict = 'excluded'; reason = '功能差异（带遥信 vs 不带）'
    elif idx == 81:
        verdict = 'excluded'; reason = '配件差异（无铜触臂标注 vs 有铜触臂）'
    elif idx == 82:
        verdict = 'pending'; reason = '型号差异（内置控制器 vs 内置控制器III）'
    elif idx == 83:
        verdict = 'confirmed'; reason = '描述差异仅"控制接触器"附加功能标注'
    elif idx == 84:
        verdict = 'excluded'; reason = '安装方式差异（侧装式 vs 无）'
    elif idx == 85:
        verdict = 'excluded'; reason = '接口差异（双G3/4外螺纹 vs 单G3/4外螺纹）'
    elif idx == 86:
        verdict = 'excluded'; reason = '颜色差异（黄 vs 无标注）'
    elif idx == 87:
        verdict = 'excluded'; reason = '颜色差异（红 vs 无标注）'
    elif idx == 88:
        verdict = 'excluded'; reason = '颜色差异（黄 vs 无标注）'
    elif idx == 89:
        verdict = 'excluded'; reason = '颜色差异（红 vs 无标注）'
    elif idx == 90:
        verdict = 'pending'; reason = '型号后缀差异（FM vs 无），需搜索确认'
    elif idx == 91:
        verdict = 'confirmed'; reason = '命名格式差异（DT-70 vs 70），同一产品'
    elif idx == 92:
        verdict = 'pending'; reason = '型号后缀差异（-L vs 无），需确认'
    elif idx == 93:
        verdict = 'pending'; reason = '型号后缀差异（r vs 无），需搜索确认'
    elif idx == 94:
        verdict = 'excluded'; reason = '型号差异（T型 vs Q型），不同产品'
    elif idx == 95:
        verdict = 'excluded'; reason = '功能差异（带自检功能 vs 不带）'
    elif idx == 96:
        verdict = 'confirmed'; reason = '描述差异仅"（非标）"标注'
    elif idx == 97:
        verdict = 'excluded'; reason = '功能差异（无蓄电池 vs 带蓄电池）'
    elif idx == 98:
        verdict = 'confirmed'; reason = '命名格式差异（6# 60x60 vs 60x60）'
    elif idx == 99:
        verdict = 'excluded'; reason = '颜色差异（黑色 vs 无标注）'
    elif idx == 100:
        verdict = 'excluded'; reason = '颜色差异（黑色 vs 无标注）'
    elif idx == 101:
        verdict = 'pending'; reason = '附件差异（配罩 vs 无）'
    elif idx == 102:
        verdict = 'excluded'; reason = '颜色差异（无 vs 白）'
    elif idx == 103:
        verdict = 'pending'; reason = '型号后缀差异（-J vs 无），需搜索确认'
    elif idx == 104:
        verdict = 'excluded'; reason = '材质/强度差异（高强度 vs 普通）'
    elif idx == 105:
        verdict = 'confirmed'; reason = '描述差异仅格式和附加说明'
    elif idx == 106:
        verdict = 'confirmed'; reason = '描述差异仅规格附加标注'
    elif idx == 107:
        verdict = 'confirmed'; reason = '描述差异仅规格附加标注'
    elif idx == 108:
        verdict = 'excluded'; reason = '型号差异（DFY-2 vs DFY-2B）'
    elif idx == 109:
        verdict = 'pending'; reason = '型号后缀差异（r vs 无），需搜索确认'
    elif idx == 110:
        verdict = 'confirmed'; reason = '命名格式差异（UK-6N vs UK 6 N 6平方端子）'
    elif idx == 111:
        verdict = 'excluded'; reason = '功能差异（定向 vs 万向），完全不同产品'
    elif idx == 112:
        verdict = 'excluded'; reason = '定制差异（详见图纸 vs 标准）'
    elif idx == 113:
        verdict = 'excluded'; reason = '表面处理差异（碳钢镀锌 vs 无标注）'
    elif idx == 114:
        verdict = 'excluded'; reason = '用途差异（高档焊接镀铬 vs 普通镀铬）'
    elif idx == 115:
        verdict = 'excluded'; reason = '形状差异（半圆 vs 圆），不同物料'
    elif idx == 116:
        verdict = 'excluded'; reason = '配件差异（无 vs 含盖板隔板）'
    elif idx == 117:
        verdict = 'excluded'; reason = '功能差异（不可升降 vs 可升降）'
    elif idx == 118:
        verdict = 'excluded'; reason = '功能差异（可升降 vs 不可升降）'
    elif idx == 119:
        verdict = 'excluded'; reason = '工作服/手套类，不检查'
    elif idx == 120:
        verdict = 'excluded'; reason = '功能差异（变光 vs 普通护目镜）'
    elif idx == 121:
        verdict = 'excluded'; reason = '功能差异（主动 vs 被动），完全不同产品'
    elif idx == 122:
        verdict = 'excluded'; reason = '功能差异（局放/传感器1拖2/装中部 vs 正装右操）'
    elif idx == 123:
        verdict = 'excluded'; reason = '功能/安装差异（左操 vs 局放/装中部）'
    elif idx == 124:
        verdict = 'excluded'; reason = '功能/安装差异（局放/装中部 vs 正装右操）'
    elif idx == 125:
        verdict = 'excluded'; reason = '功能/安装差异（局放/装柜后部 vs 左操）'
    elif idx == 126:
        verdict = 'excluded'; reason = '功能/安装差异（局放/装中部 vs 右操）'
    elif idx == 127:
        verdict = 'excluded'; reason = '规格差异（三开三闭 vs 五开五闭）'
    elif idx == 128:
        verdict = 'excluded'; reason = '功能/安装差异（局放/装中部 vs 左操）'
    elif idx == 129:
        verdict = 'excluded'; reason = '产品类型不同（油漆 ≠ 塑粉）'
    elif idx == 130:
        verdict = 'confirmed'; reason = '名称不同但同一种东西（断路器=塑壳断路器）'
    elif idx == 131:
        verdict = 'excluded'; reason = '名称语义不同（金属软管 ≠ 金属波纹管）'
    elif idx == 132:
        verdict = 'excluded'; reason = '规格差异（非标定制穿双排 vs 标准）'
    elif idx == 133:
        verdict = 'excluded'; reason = '规格差异（双排大方孔 vs 3*3，局放要求）'
    elif idx == 134:
        verdict = 'confirmed'; reason = '命名格式差异，同一种螺丝'
    elif idx == 135:
        verdict = 'excluded'; reason = '功能差异（消谐型 vs 普通型）'
    elif idx == 136:
        verdict = 'pending'; reason = '名称不同（百叶窗 vs 通风过滤网组），需确认'
    elif idx == 137:
        verdict = 'excluded'; reason = '完全不同产品（电操附件 ≠ 断路器本体）'
    elif idx == 138:
        verdict = 'excluded'; reason = '规格差异（三相 vs 单相）'
    elif idx == 139:
        verdict = 'excluded'; reason = '产品类型不同（油漆 ≠ 自喷漆）'
    elif idx == 140:
        verdict = 'excluded'; reason = '完全不同产品（微型断路器 ≠ 浪涌保护器）'
    elif idx == 141:
        verdict = 'pending'; reason = '名称不同（百叶窗 vs 通风过滤网组），需确认'
    elif idx == 142:
        verdict = 'excluded'; reason = '完全不同产品（四指套 ≠ 电缆）'
    elif idx == 143:
        verdict = 'excluded'; reason = '完全不同产品（四指套 ≠ 电缆）'
    elif idx == 144:
        verdict = 'excluded'; reason = '配件 vs 整机（转换开关 ≠ 智能操控装置）'
    elif idx == 145:
        verdict = 'excluded'; reason = '名称不同（型材 ≠ 三角板）'
    elif idx == 146:
        verdict = 'excluded'; reason = '电压规格差异'
    elif idx == 147:
        verdict = 'pending'; reason = '名称不同但可能是同一种东西（铜鼻子=接线端子）'
    elif idx == 148:
        verdict = 'excluded'; reason = '完全不同产品（传感器支架 ≠ 气缸固定座）'
    elif idx == 149:
        verdict = 'excluded'; reason = '完全不同产品（传感器支架 ≠ 气缸固定座）'
    elif idx == 150:
        verdict = 'excluded'; reason = '产品类型不同（端子挡板D-URTK ≠ 电流端子URTK/S）'
    elif idx == 151:
        verdict = 'excluded'; reason = '完全不同产品（挡板 ≠ 连接片）'
    elif idx == 152:
        verdict = 'pending'; reason = '名称不同但可能是同一种东西（铜鼻子=接线端子）'
    elif idx == 153:
        verdict = 'excluded'; reason = '用途差异（导热油用 vs 气体用）'
    elif idx == 154:
        verdict = 'pending'; reason = '描述差异，需确认'
    elif idx == 155:
        verdict = 'excluded'; reason = '产品类型不同（零序互感器 ≠ 电流互感器）'
    elif idx == 156:
        verdict = 'excluded'; reason = '产品类型不同（双电源 ≠ 双投开关）'
    elif idx == 157:
        verdict = 'excluded'; reason = '配件差异（无 vs 含盖板隔板）'
    elif idx == 158:
        verdict = 'excluded'; reason = '完全不同产品（隔离开关 ≠ 双电源）'
    elif idx == 159:
        verdict = 'excluded'; reason = '完全不同产品（玻璃 ≠ 小母线端子）'
    elif idx in (160, 161, 162, 163, 164, 165, 166, 167, 168, 169, 170, 171, 172, 173, 174, 175):
        verdict = 'excluded'; reason = '产品类型不同（铜排包扣/绝缘子包扣/电缆头包扣 互不相同）'
    elif idx == 176:
        verdict = 'excluded'; reason = '完全不同产品（APF有源滤波 ≠ SVG静止无功发生器）'
    elif idx == 177:
        verdict = 'confirmed'; reason = '名称不同但同一种东西（小型断路器=微型断路器）'
    elif idx == 178:
        verdict = 'confirmed'; reason = '名称不同但同一种东西（辅助触点=辅助触头）'
    elif idx == 179:
        verdict = 'excluded'; reason = '完全不同产品（分闸锁 ≠ 欠电压脱扣器）'
    elif idx == 180:
        verdict = 'excluded'; reason = '产品类型不同（快拧头 ≠ 快插头）'
    elif idx == 181:
        verdict = 'excluded'; reason = '配件差异（无铜触臂标注 vs 有铜触臂）'
    elif idx == 182:
        verdict = 'excluded'; reason = '材质差异（铜触臂 vs 铝触臂）'
    elif idx == 183:
        verdict = 'pending'; reason = '功能描述差异（无母线侧接地标注 vs 有）'
    
    item = {
        'A': {k: a.get(k, '') for k in ['物料编号', '物料名称', '物料描述', '制造商', '物料子类别']},
        'B': {k: b.get(k, '') for k in ['物料编号', '物料名称', '物料描述', '制造商', '物料子类别']},
        'reason': reason
    }
    
    if verdict == 'confirmed':
        confirmed.append(item)
    elif verdict == 'excluded':
        excluded.append(item)
    else:
        still_pending.append(item)

print(f'审查结果:')
print(f'  ✅ 确认重复: {len(confirmed)} 对')
print(f'  ❌ 排除非重复: {len(excluded)} 对')
print(f'  ❓ 仍待确认: {len(still_pending)} 对')

results = {'confirmed': confirmed, 'pending': still_pending, 'excluded': excluded}
with open('IN3数据/ai_review_20260610.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(f'\n=== 仍待确认 {len(still_pending)} 对 ===')
for item in still_pending:
    print(f"  {item['A']['物料编号']}({item['A']['物料描述']}) vs {item['B']['物料编号']}({item['B']['物料描述']})")
    print(f"    原因: {item['reason']}")
