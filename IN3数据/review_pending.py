#!/usr/bin/env python3
"""审查待确认配对"""
import json
import re

with open('IN3数据/pending_pairs.json') as f:
    pairs = json.load(f)

confirmed = []
pending = []
excluded = []

for i, p in enumerate(pairs):
    a = p['A']
    b = p['B']
    adesc = (a.get('物料描述', '') or '').strip()
    bdesc = (b.get('物料描述', '') or '').strip()
    aname = (a.get('物料名称', '') or '').strip()
    bname = (b.get('物料名称', '') or '').strip()
    acode = (a.get('物料编号', '') or '').strip()
    bcode = (b.get('物料编号', '') or '').strip()
    amfr = (a.get('制造商', '') or '').strip()
    bmfr = (b.get('制造商', '') or '').strip()

    # Manufacturer difference check
    if amfr and bmfr and amfr != bmfr:
        excluded.append({'A': a, 'B': b, 'reason': f'制造商不同: {amfr} vs {bmfr}'})
        continue
    if (amfr and not bmfr) or (not amfr and bmfr):
        excluded.append({'A': a, 'B': b, 'reason': f'制造商有vs无: {amfr} vs {bmfr}'})
        continue

    # Determine diff pattern
    if adesc == bdesc:
        if aname != bname:
            pending.append({'A': a, 'B': b, 'reason': f'描述相同，名称不同: {aname} vs {bname}'})
            continue
        confirmed.append({'A': a, 'B': b, 'reason': '描述和名称完全相同'})
        continue

    # Build diff_text
    if adesc in bdesc:
        extra_b = bdesc.replace(adesc, '').strip()
        diff_text = f'A subset, B has: {extra_b}'
        extra = extra_b
        extra_side = 'B'
    elif bdesc in adesc:
        extra_a = adesc.replace(bdesc, '').strip()
        diff_text = f'B subset, A has: {extra_a}'
        extra = extra_a
        extra_side = 'A'
    else:
        diff_text = f'diff: A={adesc[:60]} B={bdesc[:60]}'
        extra = ''
        extra_side = ''

    # Apply exclusion rules
    
    # 带SD接点 → 附件差异
    if 'SD接点' in diff_text:
        excluded.append({'A': a, 'B': b, 'reason': '附件差异: 带SD接点 vs 不带'})
        continue
    
    # 功能/附件差异
    if any(x in diff_text for x in ['带遥信', '带底座', '套热缩套管', '套热缩', '带自检功能', '带绕片',
                                      '带双向计量', '配一开关量']):
        excluded.append({'A': a, 'B': b, 'reason': f'功能/附件差异: {diff_text}'})
        continue
    
    # 配置相间隔板/TFK 配相间隔板
    if '相间隔板' in diff_text:
        excluded.append({'A': a, 'B': b, 'reason': f'附件差异: {diff_text}'})
        continue
    
    # 二级能效
    if '二级能效' in diff_text:
        excluded.append({'A': a, 'B': b, 'reason': '能效等级差异'})
        continue
    
    # 外观/颜色差异
    if any(x in diff_text for x in ['交通红', '镜面', '丙烯酸']):
        excluded.append({'A': a, 'B': b, 'reason': f'外观/颜色差异: {diff_text}'})
        continue
    
    # 简单颜色词差异
    for c in ['红', '黄', '黑', '白']:
        if diff_text.strip() in [f'A_has_extra: {c}', f'B_has_extra: {c}']:
            excluded.append({'A': a, 'B': b, 'reason': f'颜色差异: {diff_text}'})
            break
    else:
        # 煤改电
        if '煤改电' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '特殊版本: 煤改电'})
            continue
        
        # 柜外操作
        if '柜外操作' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '安装方式差异: 柜外操作'})
            continue
        
        # 侧装式
        if '侧装式' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '安装方式差异: 侧装式'})
            continue
        
        # 抗干扰
        if '抗干扰' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '功能差异: 抗干扰型'})
            continue
        
        # NA suffix on breakers (neutral position)
        if 'A_has_extra: NA' in diff_text or 'B subset, A has: NA' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '规格差异: NA后缀(中性线位置)'})
            continue
        
        # 插头/插座
        if '插头' in diff_text or '插座' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': f'功能差异: {diff_text}'})
            continue
        
        # PR 插拔式
        if '插拔式' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '安装方式差异: 插拔式 vs 固定式'})
            continue
        
        # 独立式
        if '独立式' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '安装方式差异: 独立式'})
            continue
        
        # 重型
        if '重型' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '规格差异: 重型 vs 普通'})
            continue
        
        # 左操/右操
        if '左操' in diff_text or '右操' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': f'方向差异: {diff_text}'})
            continue
        
        # L型/一字型/电缆头 → 形状差异
        if any(x in diff_text for x in ['L型', '一字型', '电缆头']):
            excluded.append({'A': a, 'B': b, 'reason': f'形状/类型差异: {diff_text}'})
            continue
        
        # 主动 vs 被动
        if ('主动' in diff_text and '被动' in diff_text):
            excluded.append({'A': a, 'B': b, 'reason': '功能差异: 主动 vs 被动'})
            continue
        
        # 万向 vs 定向
        if '万向' in diff_text or '定向' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '形状差异: 万向轮 vs 定向轮'})
            continue
        
        # 铜触臂/铝触臂 → 材质差异
        if '触臂' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': f'材质差异: {diff_text}'})
            continue
        
        # 欠压/脱扣器
        if '欠压' in diff_text or '脱扣器' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': f'附件差异: {diff_text}'})
            continue
        
        # 分闸锁 vs 其他
        if '分闸锁' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': f'功能差异: {diff_text}'})
            continue
        
        # 可升降
        if '可升降' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': f'功能差异: {diff_text}'})
            continue
        
        # 触点数差异
        if ('三开三闭' in diff_text and '五开五闭' in diff_text) or \
           ('三开三闭' in diff_text and '4开4闭' in diff_text):
            excluded.append({'A': a, 'B': b, 'reason': '触点配置差异'})
            continue
        
        # 三相四线 vs 三相三线
        if '三相四相' in diff_text or '三相三线' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': f'接线方式差异: {diff_text}'})
            continue
        
        # 用于电缆
        if '用于电缆' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '用途差异: 用于电缆'})
            continue
        
        # 导热油 vs 气体
        if '导热油' in adesc and '气体' in bdesc:
            excluded.append({'A': a, 'B': b, 'reason': '介质差异: 导热油 vs 气体'})
            continue
        if '导热油' in bdesc and '气体' in adesc:
            excluded.append({'A': a, 'B': b, 'reason': '介质差异: 导热油 vs 气体'})
            continue
        
        # 高压室/低压室/变压器室
        if any(x in diff_text for x in ['高压室', '低压室', '变压器室']):
            excluded.append({'A': a, 'B': b, 'reason': f'位置差异: {diff_text}'})
            continue
        
        # 止步
        if '止步' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': f'内容差异: {diff_text}'})
            continue
        
        # 高强度
        if '高强度' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '规格差异: 高强度'})
            continue
        
        # 半圆/半
        if diff_text.strip() == 'A_has_extra: 半' or '半圆' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '形状差异: 半圆/半… vs 圆/全'})
            continue
        
        # 不带风机
        if '不带风机' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '功能差异: 不带风机'})
            continue
        
        # 含盖板，隔板
        if '含盖板' in diff_text or '隔板' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': f'附件差异: {diff_text}'})
            continue
        
        # 老练/老炼
        if '老练' in diff_text or '老炼' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': f'功能差异: {diff_text}'})
            continue
        
        # AC型
        if 'AC型' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '类型差异: AC型'})
            continue
        
        # +ACS
        if '+ACS' in diff_text or 'ACS' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': f'附件差异: {diff_text}'})
            continue
        
        # 控制接触器
        if '控制接触器' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': f'配件差异: {diff_text}'})
            continue
        
        # 非标
        if '非标' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': f'规格差异: {diff_text}'})
            continue
        
        # 蓄电池
        if '蓄电池' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '功能差异: 带蓄电池'})
            continue
        
        # 图纸
        if '图纸' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '规格差异: 按图纸定制'})
            continue
        
        # 6kA
        if '6kA' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '分断能力差异: 6kA'})
            continue
        
        # 三锁两钥匙
        if '三锁' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '附件差异: 三锁两钥匙'})
            continue
        
        # 碳钢镀锌
        if '碳钢镀锌' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '材质差异: 碳钢镀锌'})
            continue
        
        # 高档焊接
        if '高档焊接' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '工艺差异: 高档焊接'})
            continue
        
        # 变光
        if '变光' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '功能差异: 变光'})
            continue
        
        # 长款
        if '长款' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '尺寸差异: 长款'})
            continue
        
        # FM suffix
        if diff_text.strip() == 'B_has_extra: FM':
            excluded.append({'A': a, 'B': b, 'reason': '型号差异: FM后缀'})
            continue
        
        # DT- prefix
        if 'DT-' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': f'型号差异: {diff_text}'})
            continue
        
        # P suffix on breakers
        if ('A_has_extra: P' in diff_text or 'B subset, A has: P' in diff_text) and '断路器' in aname:
            excluded.append({'A': a, 'B': b, 'reason': '规格差异: P后缀'})
            continue
        
        # 母线侧接地
        if '接地' in diff_text and '触臂' not in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': f'功能差异: {diff_text}'})
            continue
        
        # 公头
        if '公头' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '类型差异: 公头'})
            continue
        
        # 低压产品
        if '低压产品' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '产品系列差异: 低压 vs 高压'})
            continue
        
        # 安装孔/开孔尺寸
        if '安装孔' in diff_text or '开孔尺寸' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': f'尺寸差异: {diff_text}'})
            continue
        
        # 调到
        if '调到' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '参数差异: 已调定值'})
            continue
        
        # F suffix on 3VA breakers
        if diff_text.strip() == 'A_has_extra: F' and '3VA' in adesc:
            excluded.append({'A': a, 'B': b, 'reason': '型号差异: F后缀'})
            continue
        
        # F suffix on SmartPQS/WG
        if diff_text.strip() == 'B subset, A has: F' and ('SmartPQS' in adesc or 'WG' in adesc):
            excluded.append({'A': a, 'B': b, 'reason': '型号差异: F后缀'})
            continue
        
        # RS712C vs RS712 → 型号差异(C后缀)
        if 'RS712C' in diff_text and 'RS712' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '型号差异: RS712C vs RS712'})
            continue
        
        # ZC- prefix
        if 'ZC-' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': f'型号前缀差异: {diff_text}'})
            continue
        
        # 圆钢 光轴 → 材质/形状差异
        if '光轴' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '形状差异: 光轴 vs 普通'})
            continue
        
        # 足厚度 → 规格差异
        if '足厚度' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '规格差异: 足厚度 vs 标称'})
            continue
        
        # 6# → 规格
        if '6#' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '规格差异: 6#'})
            continue
        
        # 电操II型 → 功能差异
        if '电操' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': f'附件差异: {diff_text}'})
            continue
        
        # SZ → 规格差异
        if diff_text.strip() == 'A_has_extra: SZ':
            excluded.append({'A': a, 'B': b, 'reason': '规格差异: SZ后缀'})
            continue
        if 'SZ 250A' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '规格差异: SZ 250A'})
            continue
        
        # 配罩
        if '配罩' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '附件差异: 配罩'})
            continue
        
        # 平方 → 单位差异
        if diff_text.strip() == 'B_has_extra: 平方':
            excluded.append({'A': a, 'B': b, 'reason': '单位标注差异'})
            continue
        
        # F-SC vs SC → 前缀差异
        if 'F-SC' in adesc and 'SC' in bdesc and 'F-SC' not in bdesc:
            excluded.append({'A': a, 'B': b, 'reason': '型号差异: F-SC前缀'})
            continue
        
        # D-URTK vs URTK → 前缀差异
        if 'D-URTK' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '型号差异: D-URTK vs URTK'})
            continue
        
        # FBI URTK vs URTK → 前缀差异
        if 'FBI' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '型号差异: FBI前缀'})
            continue
        
        # DT95 vs DT-95平方 → 规格差异
        if 'DT95' in diff_text and 'DT-95' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '型号差异: DT95 vs DT-95'})
            continue
        
        # 高压计量柜门用/带护套 → 用途差异
        if '高压计量柜门用' in diff_text or '带护套' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': f'用途差异: {diff_text}'})
            continue
        
        # 10VA → 规格差异
        if diff_text.strip() == 'A_has_extra: 10VA':
            excluded.append({'A': a, 'B': b, 'reason': '规格差异: 10VA'})
            continue
        
        # 抗晃电 → 功能差异
        if '抗晃电' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '功能差异: 抗晃电'})
            continue
        
        # 配罩 on B side
        if '配罩' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '附件差异: 配罩'})
            continue
        
        # JDZX9-10 with different ratios → 需检查
        if 'JDZX9' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': f'参数差异: {diff_text}'})
            continue
        
        # ZL805 vs ZL-805 → format difference (confirmed dup)
        if ('ZL805' in adesc and 'ZL-805' in bdesc) or ('ZL-805' in adesc and 'ZL805' in bdesc):
            confirmed.append({'A': a, 'B': b, 'reason': '格式差异: ZL805 vs ZL-805(仅连字符差异)'})
            continue
        
        # ZL803百叶窗 vs ZL-803 → format diff (confirmed dup)
        if ('ZL803' in adesc and 'ZL-803' in bdesc) or ('ZL-803' in adesc and 'ZL803' in bdesc):
            confirmed.append({'A': a, 'B': b, 'reason': '格式差异: ZL803 vs ZL-803(仅连字符差异)'})
            continue
        
        # NXB-63/2P vs NXB-63 2P → format diff (confirmed dup)
        if 'NXB-63' in adesc and 'NXB-63' in bdesc:
            confirmed.append({'A': a, 'B': b, 'reason': '格式差异: NXB-63/2P vs NXB-63 2P(仅斜杠差异)'})
            continue
        
        # NSX100F TMD F 80 3P/ vs 3P3D/ → format diff
        if 'NSX100F' in adesc and 'NSX100F' in bdesc:
            confirmed.append({'A': a, 'B': b, 'reason': '格式差异: 3P/ vs 3P3D/(简写差异)'})
            continue
        
        # RAL9005 vs RAL-9005 → format diff
        if ('RAL9005' in adesc and 'RAL-9005' in bdesc) or ('RAL-9005' in adesc and 'RAL9005' in bdesc):
            confirmed.append({'A': a, 'B': b, 'reason': '格式差异: RAL9005 vs RAL-9005(仅连字符差异)'})
            continue
        
        # UK-6N vs UK 6 N → format diff
        if 'UK-6N' in diff_text or 'UK 6 N' in diff_text:
            confirmed.append({'A': a, 'B': b, 'reason': '格式差异: UK-6N vs UK 6 N(仅连字符/空格差异)'})
            continue
        
        # iPRF1 12.5r vs iPRF1 12.5 → 型号差异(r后缀)
        if 'iPRF1' in diff_text and 'r' in diff_text.lower():
            excluded.append({'A': a, 'B': b, 'reason': '型号差异: r后缀'})
            continue
        
        # iPRD1 20r vs iPRD1 20 → 型号差异
        if 'iPRD1' in diff_text and 'r' in diff_text.lower():
            excluded.append({'A': a, 'B': b, 'reason': '型号差异: r后缀'})
            continue
        
        # DXN8B T vs Q → 型号差异
        if 'DXN8B' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '型号差异: T型 vs Q型'})
            continue
        
        # AMC72L 三相 vs 单相 → 相数差异
        if '三相' in diff_text and '单相' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '相数差异: 三相 vs 单相'})
            continue
        
        # iSCB2 spacing → format diff
        if 'iSCB2' in adesc and 'iSCB2' in bdesc:
            confirmed.append({'A': a, 'B': b, 'reason': '格式差异: iSCB2 多余空格'})
            continue
        
        # LKZB-∅120 vs LKZB-Φ 120 → format diff
        if 'LKZB' in diff_text:
            confirmed.append({'A': a, 'B': b, 'reason': '格式差异: ∅ vs Φ(符号差异)'})
            continue
        
        # DTS1946-L vs DTS1946 → 型号差异
        if 'DTS1946' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '型号差异: DTS1946-L vs DTS1946'})
            continue
        
        # PP-30 vs PP30 → format diff
        if ('PP-30' in adesc and 'PP30' in bdesc) or ('PP30' in adesc and 'PP-30' in bdesc):
            confirmed.append({'A': a, 'B': b, 'reason': '格式差异: PP-30 vs PP30(仅连字符)'})
            continue
        
        # II/III suffix → version/规格差异
        if diff_text.strip() in ['A_has_extra: II', 'B_has_extra: III']:
            excluded.append({'A': a, 'B': b, 'reason': f'版本差异: {diff_text}'})
            continue
        
        # G3/4外螺纹 → 接口差异
        if '外螺纹' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': f'接口差异: {diff_text}'})
            continue
        
        # 配电柜 → 用途差异
        if '配电柜' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': f'用途差异: {diff_text}'})
            continue
        
        # 导热油用 → 介质差异
        if '导热油用' in diff_text and '气体' not in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': f'介质差异: {diff_text}'})
            continue
        
        # 穿双排 → 规格差异
        if '穿双排' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '规格差异: 穿双排'})
            continue
        
        # 智能操控装置转换开关 → 配件差异
        if '智能操控' in diff_text or '转换开关' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': f'配件差异: {diff_text}'})
            continue
        
        # 800宽 vs 800宽630A → format desc diff - need to check
        # FB 10-RTK/S vs FB 10- RTK/S → format (space)
        if 'FB 10' in diff_text:
            confirmed.append({'A': a, 'B': b, 'reason': '格式差异: 空格差异'})
            continue
        
        # 十字盘头自攻螺钉 → 螺丝类型差异
        if '十字盘头' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '螺丝类型差异'})
            continue
        
        # BH-0.66 II/III suffix → 版本差异
        if ('BH-0.66' in diff_text and ('II' in diff_text or 'III' in diff_text)) or \
           ('3KC2' in diff_text and ('II' in diff_text or 'III' in diff_text)) or \
           diff_text.strip() in ['A_has_extra: II', 'B_has_extra: III']:
            excluded.append({'A': a, 'B': b, 'reason': f'版本差异: {diff_text}'})
            continue
        
        # 10VA → 规格差异
        if '10VA' in diff_text:
            excluded.append({'A': a, 'B': b, 'reason': '规格差异: 10VA容量标注'})
            continue
        
        # 简单颜色差异(含黑色)
        for c in ['黄', '红', '黑', '白', '黑色']:
            if diff_text.strip() in [f'A_has_extra: {c}', f'B_has_extra: {c}', 
                                      f'B subset, A has: {c}', f'A subset, B has: {c}']:
                excluded.append({'A': a, 'B': b, 'reason': f'颜色差异: {c}'})
                break
        else:
            # FM suffix on SPD
            if 'FM' in diff_text and 'TB80' in diff_text:
                excluded.append({'A': a, 'B': b, 'reason': '型号差异: FM后缀'})
                continue
            
            # -J suffix
            if diff_text.strip() == 'A subset, B has: -J' or '-J' in diff_text:
                excluded.append({'A': a, 'B': b, 'reason': '型号差异: J后缀'})
                continue
            
            # 三相三相
            if '三相三相' in diff_text:
                excluded.append({'A': a, 'B': b, 'reason': '接线方式差异'})
                continue
            
            # 平方
            if diff_text.strip() in ['B_has_extra: 平方', 'A subset, B has: 平方']:
                excluded.append({'A': a, 'B': b, 'reason': '单位标注差异: 平方'})
                continue
            
            # SZ suffix
            if 'SZ' in diff_text:
                excluded.append({'A': a, 'B': b, 'reason': '规格差异: SZ后缀'})
                continue
            
            # 玻璃 vs 小母线端子 (名称语义不同)
            if aname != bname and adesc == bdesc:
                pending.append({'A': a, 'B': b, 'reason': f'描述相同，名称语义不同: {aname} vs {bname}'})
                continue
            
            # Not matched → pending
            pending.append({'A': a, 'B': b, 'reason': f'需人工确认: {diff_text}'})
            continue

print(f'确认重复: {len(confirmed)}')
print(f'排除非重复: {len(excluded)}')
print(f'仍待确认: {len(pending)}')
print()
print('--- 确认重复 ---')
for j, pp in enumerate(confirmed):
    ad = (pp['A'].get('物料描述', '') or '')[:60]
    bd = (pp['B'].get('物料描述', '') or '')[:60]
    print(f'{j+1}. {pp["reason"]}')
    print(f'   A: {ad}')
    print(f'   B: {bd}')
print()
print('--- 仍待确认 ---')
for j, pp in enumerate(pending):
    ad = (pp['A'].get('物料描述', '') or '')[:80]
    bd = (pp['B'].get('物料描述', '') or '')[:80]
    print(f'{j+1}. {pp["reason"]}')
    print(f'   A: {ad}')
    print(f'   B: {bd}')
    print()
