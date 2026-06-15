# IN3 物料重复检查 - 完整任务指令

## Step 1：登录 IN3 并导出物料

1. 用 browser action=open 打开 https://in3.industrics.com/
2. 如果页面跳转到工作台，说明已登录，直接操作
3. 如果显示登录页，输入账号登录（企业：haiyue，账号：18392180970，密码：Start12345@）
4. 进入 系统管理 → 主数据管理 → 物料档案管理
5. ⚠️ 必须取消勾选「过滤成品/虚拟件」！用 `document.querySelectorAll('input[type=checkbox]')[2].click()` 切换
6. 点击搜索按钮，等物料列表加载
7. 点击「批量导出物料」按钮（只点一次！）
8. 到下载中心（https://in3.industrics.com/tc/list）等状态为「已成功」后获取下载链接
9. 用 curl 下载文件到 IN3数据/ 目录

注意：
- IN3 前端组件特殊，常规 aria ref 点击经常失败，优先用 evaluate + DOM 查询操作
- CDN 签名 URL 会过期，导出后尽快下载
- 用 openpyxl.load_workbook() 不带 read_only=True（IN3 导出 xlsx 有 dimension bug）

## Step 2：用 Python 做候选配对分组（不做任何排除判断！）

运行以下脚本，它只做配对分组，不做排除：

```bash
cd /Users/zhangdongfang/.openclaw/workspace-in3bot && python3 -c "
import sys
sys.path.insert(0, 'IN3数据')
from in3_dup_check import load_materials, find_pairs
import json, time, re, os

# 找最新导出
data_dir = 'IN3数据'
pattern = re.compile(r'物料主数据导出结果.*\.xlsx$')
candidates = [(os.path.getmtime(os.path.join(data_dir, f)), os.path.join(data_dir, f)) for f in os.listdir(data_dir) if pattern.match(f) and 'v2' not in f.lower()]
candidates.sort(reverse=True)
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
"
```

⚠️ 这步只做同名分组+描述分组，不做任何排除判断。所有候选配对都交给 Step 3 的 AI。

## Step 3：AI 逐对审查（最关键步骤！）

读取 IN3数据/candidate_pairs.json，逐对按以下规则判断。

### 白名单
先读取 IN3数据/物料非重复白名单.json，已确认非重复的配对直接跳过。

### 验证库
- 用 IN3数据/dongfang_confirmed_dup.json + dongfang_confirmed_nondup.json（Dongfang 人工核查）
- ⚠️ 禁止用自己生成的 `_已验证_` 文件（有大量误标）

### 查重规则（必须逐条遵循）：

**一、排除规则（以下情况不算重复）：**

1. **甲供件不算重复** — 物料来源/类别为「甲供件」的排除
2. **制造商不同 → 不算重复** — 统一名称后对比（去掉"有限公司""(中国)""股份"等后缀）
3. **制造商有 vs 无 = 非重复** — 一方有制造商、另一方无制造商，不算重复
4. **规格数字不同 → 不算重复** — 型号中的数字代表电流/规格（如 400A vs 630A）
5. **颜色不同 → 不同物料**（红/黄/绿/蓝等）
6. **极性不同 → 不同物料**（A型/B型/C型/N型/PE型）
7. **形状不同 → 不同物料**（圆/半圆、定向轮/万向轮、方形/圆形）
8. **有/无某功能 → 不同物料**（带通讯 vs 不带、带底座 vs 不带）
9. **大于/小于某规格 → 不同物料**
10. **安装方式不同 → 需确认**（左操/右操、平进/垂进、明装/暗装、壁挂/落地）
11. **方向不同 → 不同物料**（上进/下进、左操/右操、立式/卧式、内/外）
12. **材质不同 → 不同物料**（铜/铝、304/316、紫铜/黄铜）
13. **尺寸/参数不同 → 不同物料**（长宽高、直径、截面积、电流、电压、功率）
14. **型号系列不同 → 不同物料**（XCT9≠XCT6、RC4≠RC8）
15. **附件差异 → 不同物料**（失压/分励/辅助/报警等附件不同）
16. **表面处理不同 → 不同物料**（镀锌 vs 无、镀彩锌 vs 发黑、镀银 vs 无、不锈钢 vs 普通）
17. **柜型不同 → 不同物料**（GCK/GCS/MNS/KYN28）
18. **分闸 vs 合闸 → 不同物料**（功能完全不同）
19. **核心原则：先理解描述含义，不是纯字符串匹配！**
20. **核心原则：物料名称语义判断优先——不是同一种东西就不算重复**

**二、确认重复规则：**

1. **描述完全相同 + 同制造商 → 确认重复**
2. **数字相同 + 只有字母/符号差异 + 同制造商 → 确认重复**（如多/少一个字母、顺序不同、括号格式不同）
3. **名称表述不同但指同一种东西 → 确认重复**（如"798环氧富锌底漆" vs "环氧富锌底漆"、"角钢" vs "角铁"、"汇流零线排" vs "汇流端子"、"接触器" vs "交流接触器"、"螺母" vs "螺帽"）

**三、可疑重复验证流程：**
- 对每对可疑重复，用 web_search 搜索两个型号的官方描述
- 如果A和B都能搜到且描述一致 → 确认重复
- 如果A和B搜到的是不同型号/规格 → 排除
- 优先查找厂家官网或产品手册的型号命名规则

### 审查流程：
1. 读取 candidate_pairs.json
2. 先过滤白名单
3. 对每一对候选配对，按上述规则逐条判断：
   - 符合任何排除规则 → 排除（记录原因）
   - 符合确认重复规则 → 确认重复
   - 不确定 → 用 web_search 搜索验证
   - 搜索后仍无法判断 → 保留为「待确认」
4. 将结果保存为 JSON：IN3数据/review_results.json，格式：
   ```json
   {"confirmed": [{"A": {...}, "B": {...}, "reason": "..."}], "pending": [{"A": {...}, "B": {...}, "reason": "..."}]}
   ```

### ⚠️ 目标：
- 待确认降到 **个位数**（≤10对）
- 不要把几十对明显不相关的扔给 Dongfang！
- 每对物料都要经过你的判断，不能偷懒跳过
- 排除的也要记录原因，方便 Dongfang 复查

## Step 4：生成 Excel 并发送

用 Python 生成最终 Excel：
```python
import openpyxl
from openpyxl.styles import PatternFill, Font, Border, Side, Alignment
from openpyxl.utils import get_column_letter
import json

# 读取审查结果
with open('IN3数据/review_results.json', 'r') as f:
    results = json.load(f)

confirmed = results['confirmed']
pending = results['pending']

BLUE = PatternFill(start_color='E8F0FE', end_color='E8F0FE', fill_type='solid')
ORANGE = PatternFill(start_color='FFF3E0', end_color='FFF3E0', fill_type='solid')
YELLOW = PatternFill(start_color='FFFDE7', end_color='FFFDE7', fill_type='solid')
RED_FONT = Font(color='FF0000', size=10)
BLACK_FONT = Font(size=10)
thin = Side(style='thin', color='D0D0D0')
BORDER = Border(top=thin, left=thin, right=thin, bottom=thin)

FIELDS = [
    ('标记', 'label'), ('物料编号', 'code'), ('物料名称', 'name'),
    ('物料描述', 'desc'), ('物料类别', 'cat'), ('物料子类别', 'subcat'),
    ('制造商', 'manufacturer'), ('物料来源', 'source'), ('提前期', 'lead_time'),
    ('主计量单位', 'unit'), ('标准价格', 'price'), ('创建人', 'creator'),
    ('创建日期', 'create_date'), ('最近修改人', 'modifier'),
    ('最近修改日期', 'modify_date'), ('备注', 'remark'),
]
DIFF_FIELDS = {'name', 'desc', 'cat', 'subcat', 'manufacturer', 'source', 'lead_time', 'unit', 'price'}

def make_sheet(wb, title, data):
    ws = wb.create_sheet(title)
    for ci, (fname, _) in enumerate(FIELDS, 1):
        c = ws.cell(row=1, column=ci, value=fname)
        c.font = Font(bold=True, size=10)
    ri = 2
    for idx, item in enumerate(data, 1):
        a, b, reason = item['A'], item['B'], item.get('reason', '')
        for label, mat, fill in [(f'A-{idx}', a, BLUE), (f'B-{idx}', b, ORANGE)]:
            for ci, (_, key) in enumerate(FIELDS, 1):
                if key == 'label': val = label
                elif key == 'remark': val = reason
                else: val = mat.get(key, '')
                cell = ws.cell(row=ri, column=ci, value=val)
                cell.fill = fill
                cell.border = BORDER
                if key in DIFF_FIELDS:
                    va = str(a.get(key, '') or '').strip()
                    vb = str(b.get(key, '') or '').strip()
                    cell.font = RED_FONT if va != vb else BLACK_FONT
                else:
                    cell.font = BLACK_FONT
            ri += 1
    return ws

if confirmed or pending:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    if confirmed:
        make_sheet(wb, '确认重复', confirmed)
    if pending:
        make_sheet(wb, '待确认', pending)
    output_path = 'IN3数据/最终查重结果.xlsx'
    wb.save(output_path)
    print(f'已保存: {output_path}')
```

- 用 message 发送 xlsx 文件给 Dongfang（target: 8782649356, channel: telegram）
- 消息中说明：确认重复X对，待确认Y对（从N对候选中排除M对）
- **无结果（确认重复0 + 待确认0）→ 不发消息**

## 重要注意
- ⚠️ 绝对不要重启 Gateway！
- ⚠️ 网址是 industics（没有 r）！
- ⚠️ py 脚本只做配对分组，不做排除判断！所有判断由 AI 按规则执行！
- ⚠️ 严格遵守查重规则，不要自己发明新规则！
