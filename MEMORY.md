# MEMORY.md - Bot 8 IN3Bot 长期记忆

## 身份
- **Bot 编号：** Bot 8
- **名称：** IN3Bot 🏭
- **职责：** 执行海越慧工云 IN3 系统操作、物料重复检查

## 已停用的 Bot
- **Bot 2 (costcalc)** — 2026-06-13 停用，不给它发消息
- **Bot 3 (assistant)** — 2026-06-13 停用，不给它发消息

## 文件路径
- **工作文件夹：** `/Users/zhangdongfang/.openclaw/workspace-in3bot/`
- **共享文件夹（shared-windows）：** `/Users/zhangdongfang/shared-windows/` — Dongfang 的主要文件共享位置，包含项目资料、样本、招投标等

## 施耐德 Acti9 产品目录学习（2026-06-29）
- **来源文件：** `shared-windows/样本/A9 样本 (1).pdf`（328页）
- **品牌：** 施耐德电气（Schneider Electric）
- **产品线：** Acti9 — 第五代终端配电产品目录 2025
- **主要内容：**
  1. **小型断路器（MCB）：** iC65N/N-S/H/H-S/L 系列、iC60N DT 双端子、iC65L MA 单磁式、C60 UL489、C60N/H 海事专用、iDPNa/iDPNa-S/iDPNN/iDPNN-S/iDPNH/iDPNK2、C120H/H-S/L/L-S 高额定电流
  2. **直流小型断路器：** iC65N/H/L DC 系列、C120H DC、iC125F/E DC 系列
  3. **导轨式熔断器座：** A9SFUSE
  4. **隔离开关：** iINT125、iINT125-S
  5. **剩余电流动作保护（RCD）：** Vigi iC65/iDPN 系列、iID 电磁式（A/B类）、iDPNa Vigi+/iDPNN Vigi+ 等
  6. **电气和机械附件：** 脱扣附件（MN/MNs/MX/OF/SD）、iCNV 自恢复过欠压保护器、指示附件
  7. **控制类产品：** iCT 接触器、iCT+ LED 照明电子开关、iTL 脉冲开关、RCA 远程控制附件、ARA 自动重合控制附件
  8. **Reflex iC60N/H 集成控制断路器**
  9. **梳状母排/配电模块：** Multiclip、Distribloc 63A
  10. **工业防水插头插座：** 16A-125A 全系列
  11. **技术参考资料：** 脱扣曲线、限流曲线、级联表、保护选择性表、温度降容系数表
- **命名规则关键：**
  - 产品号格式如 A9F04120 = iC60N 1P C20A（A9=Acti9系列，F=断路器，04=1P，1=C曲线，20=20A）
  - 断路器分断能力等级：N=6kA、H=10kA、L=15kA
  - 脱扣曲线：B（照明）、C（配电）、D（动力）
  - 后缀含义：-S=紧凑型、DT=双端子、MA=单磁式、DC=直流、Vigi+=带漏电保护
- **用途：** 可作为物料查重和命名规范检查的品牌型号参考知识库

## Context Overflow 修复（2026-06-16）
- 全局已加 compaction (truncateAfterCompaction + maxActiveTranscriptBytes 5mb) 和 contextPruning (cache-ttl 10m)
- 如果再遇到 context overflow，用 /reset 重置 session

## IN3 系统信息
- **网址：** https://in3.industics.com/（⚠️ 注意：industics，没有 r！不是 industrics）
- **企业：** haiyue
- **账号：** 18392180970
- **密码：** Start12345@
- **旧账号（备用）：** haiyue / bftest，密码 Ind@123456

## 最新任务记录

### 每日采购价格分析（2026-06-29）
- **任务执行**：17:05-17:10完成
- **分析日期**：2026-06-27
- **关键发现**：钢板类价格异常偏高（偏离86%-90%），接触器采购价低于市场价格（-21%至-29%）
- **网上比价**：完成3个元器件类物料的网上比价（断路器附件、接触器CJX2s-5011、接触器CJX2S-8011）
- **报告生成**：Excel包含4个Sheet，已发送Telegram和飞书群
- **异常处理**：钢板类需核实供应商报价，接触器采购策略合理

## 经验教训（重要！）

### 核心原则
1. **查重任务必须汇报（Dongfang 2026-07-11 确认）** — 每次查重任务执行完后，**即使0重复0待确认也必须发消息告诉 Dongfang**，让他确认任务执行了。不能「无问题不发消息」
1. **下班规则（Dongfang 新规）** — 当 Dongfang 说「今天工作结束」「收工」「下班了」时，必须：① 检查未完成任务并汇报；② 有代码/文件变更的 git add/commit/push 上传 GitHub；③ 用 sessions_send 通知主控（agent:main:main）自己的状态
1. **主动汇报** — 任何任务超过 5 分钟必须用 message 主动汇报进度，每完成一个关键步骤就汇报一次，绝对不能等 Dongfang 来问
2. **记录每天经验** — 每次操作发现的新问题、新技巧、新坑，必须记录到 MEMORY.md 和 memory/YYYY-MM-DD.md
3. **持续自我进化** — 不断优化操作流程，减少出错，减少需要问 Dongfang 的情况

### IN3 系统操作经验
1. **登录** — 企业选 haiyue，账号 18392180970，密码 Start12345@，默认即填好的，直接点登录
2. **导出物料前** — 先检查下载中心是否已有今日导出文件，避免重复导出
3. **导出后等待** — 点击导出后需等 3-4 分钟文件才可下载，不要立即检查
4. **取消过滤成品/虚拟件** — 进入物料档案管理后，必须取消勾选「过滤成品/虚拟件」checkbox，否则导出的数据不完整
5. **IN3 浏览器操作** — IN3 前端组件特殊，常规 aria ref 点击经常失败，优先用 evaluate + DOM 查询操作
6. **物料列表页的 checkbox** — 用 `document.querySelectorAll('input[type=checkbox]')[2].click()` 来切换「过滤成品/虚拟件」
7. **只点一次导出** — 批量导出物料按钮只点一次，不要重复点击
8. **⚠️ xlsx dimension bug** — IN3 导出的 xlsx 文件 dimension 属性为 "A1"，openpyxl read_only 模式只返回1列。**必须用 `openpyxl.load_workbook()` 不带 read_only=True**
9. **CDN 签名 URL 会过期** — 导出后尽快从下载中心下载，签名 URL 有时效
10. **采购订单明细导出** — 必须在明细视图（不是单据视图）点击批量导出
11. **采购数据分析** — 不要用子代理下载文件，主 session 直接操作更高效
12. **⚠️ 任务完成后必须关闭浏览器** — 每次 IN3 操作完成后用 `browser stop` 关闭浏览器，避免资源占用
13. **每次导出必须重新导出全部数据** — 即使昨天导出过，今天也要重新导出，确保数据最新

### IN3 采购订单明细导出标准流程（2026-06-13 优化）

**完整步骤（每个工厂重复一次，先宁波再湖北）：**

**Step 1: 登录**
```
browser start
browser navigate url=https://in3.industics.com/home
```
⚠️ 网址是 industics（没有 r！）
如果页面已填好账号密码，直接点登录按钮
如果出现「账号绑定确定」弹窗，用 evaluate 点确定关闭

**Step 2: 导航到采购订单管理（直接用 URL，不走菜单！）**
```
browser navigate url=https://in3.industics.com/purchase/po/list
```
⚠️ 如果 URL 变化导致 404，fallback 用 DOM 选择器：
```javascript
// 先点击左侧「采购管理」展开子菜单
document.querySelectorAll('li.el-menu-item') → 找 textContent='采购管理' 的 → click()
// 再点击子菜单「采购订单管理(ME20)」
document.querySelectorAll('.vertical-menu-item') → 找 textContent='采购订单管理(ME20)' 的 → click()
```
⚠️ 菜单导航相关选择器（备用，仅在 URL 直达失败时使用）：
- 左侧一级菜单用 `.el-menu-item` 选择器
- 子菜单用 `.vertical-menu-item`（单数）选择器，不是 `.vertical-menu-items`（复数）
- 搜索框不要用（会修改 placeholder 而不是 value）

**Step 3: 配置筛选条件**
```javascript
// 1. 切换到明细视图
document.querySelectorAll('.el-tabs__item') → 找 '明细视图' → click()

// 2. 展开筛选条件（点「展开」按钮）
document.querySelectorAll('button') → 找 textContent='展开' → click()

// 3. 取消「只显示open PO」（必须！否则只有未完成的订单）
document.querySelectorAll('.el-checkbox') → 找 textContent='只显示open PO' + is-checked → click() 取消

// 4. 点「查询」刷新数据
document.querySelectorAll('button') → 找 textContent='查询' → click()
```
⚠️ 关键发现：
- 默认「只显示open PO」是勾选的，必须取消才能拿到全量数据（含历史价格）
- 价格异常分析需要全量数据（历史价格对比），只导出 open PO 会导致历史均价不准确

**Step 4: 批量导出**
```javascript
// 点击「批量导出」按钮 → 会出现下拉菜单
button textContent='批量导出' → click()
// 选择「导出全部字段」（不是「导出当前配置字段」）
document.querySelectorAll('.el-dropdown-menu__item') → 找 '导出全部字段' → click()
```
⚠️ 关键发现：批量导出按钮旁边有个下拉菜单（`<ul class="el-dropdown-menu">`），包含：
- 「导出全部字段」← 选这个，数据最完整
- 「导出当前配置字段」← 只导出当前显示的列

**Step 5: 切换工厂**
```javascript
// 切换到湖北工厂
input[placeholder='请选择工厂'] → click()
document.querySelectorAll('.el-select-dropdown__item') → 找 textContent 包含 '湖北' → click()
```
⚠️ 关键发现：切换工厂后页面会跳回首页（/home），需要重新执行 Step 2~4

**Step 6: 从下载中心下载文件**
```
browser navigate url=https://in3.industics.com/download/center
```
等导出完成（约2-3分钟）后刷新页面：
```javascript
[...document.querySelectorAll('button')].find(b => b.textContent.trim() === '刷新').click();
```
- 提取下载链接：`document.querySelectorAll('a[href*="tos-cdn"]')`，找任务名称='采购订单明细导出' + 今日日期
- 下载 URL 格式：`https://tos-cdn-01.industics.com/...`（⚠️ industics 没有 r！）
- 用 curl 下载并重命名：`采购订单明细-宁波-YYYYMMDD.xlsx`、`采购订单明细-湖北-YYYYMMDD.xlsx`

**Step 7: 清理**
```
browser stop  // 关闭浏览器，释放资源
```

**常见问题处理：**
- 弹窗「账号绑定确定」→ 点确定
- 弹窗「通知」→ 关闭抽屉（`.el-drawer__close-btn`）
- 页面没反应 → 等待2秒后重试，不要疯狂点击
- CDN下载失败 → 检查 URL 拼写（industics 不是 industrics）

### IN3 路由变更（2026-08-06 确认）
- **旧路由** `/purchase/po/list` 已 404
- **新路由** `/spm/purchase-order/list`
- **下载中心路由变更（2026-08-15 确认）**：旧路由 `/download/center` 已 404，新路由 `/tc/list`（完整 URL: `https://in3.industics.com/tc/list?current_page=1&page_size=20`），已在流程文档和 AGENTS.md 中更新
- **导航方式**：不能直接 navigate URL，必须菜单导航：
  1. evaluate 点击 `.el-menu-item` 中 textContent='采购管理' 的元素
  2. 等1秒，evaluate 在 `.menu-groups-container` 中找 `.menu-item-name` textContent='采购订单管理'，click 其 `.third-menu-item` 父元素
  3. 等2秒，URL 变为 `/spm/purchase-order/list`
- **工厂切换方法**（2026-08-06 Dongfang 确认）：
  - ⚠️ **首页没有切换工厂的选项！** 必须先进入下级菜单（如采购管理、销售管理等）后，才能看到工厂选择器
  1. 先菜单导航进入采购管理等下级页面
  2. evaluate 点击 `input[placeholder='请选择工厂']`
  3. 等1秒，evaluate 在 `.el-select-dropdown__list li` 或 `.el-scrollbar__view li` 中找 textContent 含「湖北」的，click()
  4. 切换后页面跳回 `/home`，需重新菜单导航到采购订单管理
- **工厂名称**：宁波工厂 / 孝昌工厂（湖北）

### 采购价格分析 cron 拆分（2026-08-06）
- **原 cron** `1ef6dc86` 拆成 2 个：
  - **Job 1** `daily-price-export`（1ef6dc86）19:00 — 只导出宁波+湖北，600s
  - **Job 2** `daily-price-analyze-send`（32266fc6）19:20 — 下载+分析+发送，900s
- **拆分原因**：单次 cron 7步完不成，snapshot 超大，工厂选择器卡住
- **关键改进**：Job 1 全程用 evaluate 操作 DOM，不用 snapshot；导航走菜单不走 URL

### 定时任务配置（2026-06-27 更新）
1. **delivery 必须明确指定** — 用 `channel: "telegram"`, `to: "8782649356"`, `accountId: "bot8"`，不要用 `channel: "last"` 自动解析
2. **企业名必须核实** — haiyue 是正式环境，bftest 是测试环境，不要写错
3. **IN3 浏览器代理配置（2026-05-18 最终方案）** — OpenClaw 浏览器用 `--proxy-auto-detect`（自动检测 macOS 系统代理/Clash Verge），配合 `ssrfPolicy.dangerouslyAllowPrivateNetwork: true`。配置在 `openclaw.json` 的 `browser.extraArgs` 中
4. **采购价格异常 cron（2026-05-30 优化）** —
   - Cron ID: `1ef6dc86-6501-447b-9677-14e7b88d4f9f`，每天19:00（周一到周六）（7/14从17:00改为19:00）
   - 流程：直接批量导出全量（不筛选日期）→ 下载 → 脚本筛选当天新增 vs 历史 → 偏离≥40%标记异常 → 通过 company bot 发 Excel 到飞书采购群
   - 飞书采购群 sessionKey: `agent:company:feishu:group:oc_498ec91554f3c3272cc6ae02ecf27557`
   - 只检查当天新增采购的价格偏离，不做历史交叉比对
   - 发送失败则通知 Dongfang
   - 分析脚本：`IN3数据/price_anomaly_daily.py`
   - **⚠️ 必须包含宁波+湖北两个工厂数据（2026-06-29 Dongfang 强调）**
   - cron 执行时必须确认两个工厂文件都已下载完成后才运行分析
   - 如果湖北文件未就绪，等待后再执行，不能只出宁波数据
   - IN3 切换工厂：登录后页面上方工厂选择栏，选「湖北」后重新导出
5. **物料查重 cron（2026-06-27 调整）** —
   - 每日增量查重: Cron ID `66c676e3-d106-4d66-9b2e-5f3dd4c39b09`，19:30（周一~周六）（7/14从17:30改为19:30）
   - 每周全量排查: Cron ID `92ddfa50-80b8-4ed1-8c0d-bdf0235345a5`，09:00（周六）（7/14从15:00改为09:00）
   - 增量模式：`in3_dup_check.py auto --incremental`，只查当天新建/修改 vs 全量历史
   - 全量模式：`in3_dup_check.py auto`，所有物料交叉比对
   - agentId: in3bot，delivery: telegram to 8782649356
6. **命名规范检查（2026-07-11 重组）** —
   - **已合并到增量查重 cron** (`66c676e3`, 17:30)，Step 3 调 naming_check.py
   - 原 cron `20235245` (17:45) **已禁用** — 原因：LLM 自己选文件导致用错昨天数据
   - naming_check.py 自动找最新物料文件，不要手动指定

### 物料重复检查经验
1. **⚠️ 核心规则（Dongfang 多次强调）** — 型号中不一致的数字或字母代表元器件特征（颜色、尺寸、方向、电流、电压等），只要型号中有任何数字/字母不同 = 非重复！不应进入待人工确认表
2. **只要有一项不同 = 非重复** — 形状、尺寸、颜色、材料、内/外，任一不同即非重复
3. **名称不同 + 描述一致 = 待人工确认** — 不能自动判断，需人工最终决定
4. **仅符号差异（× vs x）= 确认重复（命名不规范）** — 单独列出标注
5. **名称比较必须在 is_naming_mismatch 之前** — 否则名称不同的配对会被错误判为确认重复
6. **ultra_normalize 要保留数字间小数点** — 否则 RV 2.5 和 RV 25 会被搞成一样
7. **螺丝常识** — 头部形状（十字/一字/内六角/外六角/梅花）、表面处理（镀彩/镀白锌/发黑/不锈钢）、材质不同 = 不同螺丝
8. **电气常识** — 不同柜型（GCK/GCS/MNS/KYN28）、分闸vs合闸、静插件vs动插件、明装vs暗装 = 不同产品
9. **分析脚本（稳定版）：** `IN3数据/in3_dup_check.py` — CLI 工具，支持 `analyze`（分析）、`compare`（对比）、`auto`（自动）三个子命令，日期自动从文件名提取，不用每次改代码。旧版 `analyze_v3.py` 和 `compare_results.py` 已标记 `.legacy`
10. **语义不同 = 非重复（Dongfang 2026-05-21 强调）** — 对比物料名称时先判断是不是同一种东西：
    - 电烙铁 ≠ 熔锡炉（功能完全不同，绝非重复）
    - 油漆刷 ≠ 铲刀（完全不同的工具）
    - 工作服类可以忽略，不用管
    - **核心原则：不是同一种东西/不是同一个用途的物料，肯定不算重复物料**
10. **文件发送路径** — 需先 cp 到 `/Users/zhangdongfang/.openclaw/media/` 才能用 message 发送

### 物料检查性能优化
- 按物料类别+子类别+物料名称分组，组内按 ultra(desc) 分组比较
- 数字集合校验在同名组和跨名称组都执行
- 不导出非重复表，只有确认重复+待人工确认两个 sheet

### 2026-06-08 规则优化（Dongfang 反馈）
- **核心修复**：描述中数字集合差异 = 非重复（不再过滤通用数字如400）
- **核心修复**：sim≥0.9 太松导致大量误判 → 改为 sim≥0.97 + 数字一致才算确认重复
- **新增规则 #3a**：方向/位置互斥词（左vs右、上vs下、停电vs送电等）
- **新增规则 #3b**：AC vs DC 电压类型不同
- **新增规则 #13b**：名称/描述中颜色词互斥
- **新增规则 #35b**：+xxx 后缀差异（如+插入式）
- **修复规则 #40**：罗马数字支持 30I、30II 等后缀形式
- **效果**：确认重复从 84→11，待人工确认从 772→303→188（排除管道/气动/外包后），非重复排除从 7199→7352
- **排除类别**：成品柜、外购成套、管道配件、气动配件、外包服务
- **待办**：待人工确认 188 对还需 Dongfang 审核后进一步优化规则

### Excel 输出格式（必须严格遵守！）
- **直接用 `in3_dup_check.py analyze` 命令生成**，不要自己写 openpyxl 逻辑
- 脚本内置 `generate_excel()` 自动处理：A/B交替行、蓝/橙背景、差异字段红色、备注列、冻结窗格、自动筛选
- **禁止手动用 openpyxl 拼 Excel！直接调命令行**

### Dongfang 核查反馈排除规则（汇总）
**语义不同 = 非重复：** 电烙铁≠熔锡炉、油漆刷≠铲刀、工作服不管；分闸≠合闸
**表面处理差异 = 非重复：** 镀锌vs无、镀彩锌vs发黑、镀银vs无、不锈钢vs普通（名称+描述都要检查）
**形状/结构差异 = 非重复：** 常规vs加大、带花纹vs无、有孔vs盲板、整套vs面板套件、组合vs单独
**功能/操作差异 = 非重复：** 手摇vs手拉、左vs右导轨、户外vs普通、双/单/端子板/底板支架
**型号后缀不同 = 非重复：** CVS100NM≠CVS100N、MY4N-J≠MY4N、iC65N≠iC65N I
**带vs不带 = 非重复：** +底座vs无、变频vs无标注
**标注vs无标注 = 非重复：** 材质(铜制)、颜色(白)、铜排数量不同、功能位置标注不同
**型号系列不同 = 非重复：** LXK-≠LKZB-、LKH-≠LKZB-、WZPT-≠WZB-
**制造商有vs无 = 非重复**（一方有另一方没有）
**双开≠单开、接线方式WHR≠W**
- 05-23详细记录：`memory/物料核查反馈-20260523.md`

### Dongfang 反馈包含规则
- 多功能表/电能表/电度表 — 描述一样可能是重复，进待人工确认
- 确认重复规律：角钢=角铁、汇流零线排=汇流端子、接触器=交流接触器、螺母=螺帽、断路器=塑壳断路器、弹垫=弹簧垫片=弹簧垫圈、转换开关=万能转换开关

### Dongfang 反馈排除规则（2026-06-27 新增）
- 颜色不同（一方有颜色另一方没有）= 非重复：连接片黄/红 vs 无色
- **精度标注格式不同（2026-08-11 Dongfang 确认）** — 如 0.2S/0.2S vs 0.2S = 非重复（双绕组精度 vs 单绕组精度，电流互感器绕组配置不同）
- **精度后缀 S 差异 = 非重复（2026-08-29 Dongfang 确认）** — 0.5 vs 0.5S：S 代表不同功能（绕组），已加入 in3_dup_check.py 规则 #0c
- 传感器支架 ≠ 气缸固定座
- 铜排包扣 ≠ 绝缘子包扣 ≠ 电缆头包扣
- 油漆 ≠ 塑粉 ≠ 自喷漆
- 玻璃 ≠ 小母线端子、低压电缆四指套 ≠ 低压电缆、型材 ≠ 三角板
- 行程开关-护套 ≠ 行程开关（配套件 vs 主件）



## 物料重复检查
- **流程文档：** `IN3物料重复检查流程.md`（42条规则 #0-#41）
- **分析脚本（唯一脚本）：** `IN3数据/in3_dup_check.py` — CLI 工具，cron 直接用它
- **⚠️ 禁止再用 pre_review.py** — 已废弃，逻辑不同步，2026-06-02 Dongfang 确认只用 in3_dup_check.py
- **AI查重终版逻辑（2026-05-30 Dongfang确认，以后按此执行）：**
  1. 配对：同名物料 + 跨名称（去表面处理前缀后相同 或 明确同义词如电度表=电能表、角钢=角铁、接触器=交流接触器、螺母=螺帽、断路器=塑壳断路器等）
  2. 验证库：用 Dongfang 人工核查的「核查及处理结果」文件（`IN3数据/dongfang_confirmed_dup.json` + `dongfang_confirmed_nondup.json`），**禁止用**自己生成的 `_已验证_` 文件（有大量误标）
  3. 排除规则：制造商不同、制造商有vs无（一方有制造商另一方没有=非重复）、表面处理不同（必须同时检查名称+描述）、名称语义不同、附件/颜色/极数/柜型/方向差异等
  4. 确认重复：仅描述格式差异（空格/大小写/全角半角/级字/连字符/斜杠/前导零）
  5. **关键**：名称不同+非同义词的直接不配对（防止铜螺母vs方形螺母误配）
  6. **关键**：表面处理差异可能在名称里（如不锈钢外六角螺丝 vs 镀彩外六角螺丝，描述都是 M10×55）
- **周六全量任务新思路（2026-08-29 Dongfang 确认）** — 每周六全量查重不能把本周各日报告综合汇总（大多已被修正）。必须：①当天重新导出最新物料清单；②全量查重基于最新数据；③把本周增量查重/命名检查报告过的物料编号逐条在最新清单核验，只输出仍存在且仍有问题的「遗留未修正」项（generate_excel 规范文档）。已写入 cron 92ddfa50 提示词
- **最新结果：** 确认重复 6 对，待人工确认 30 对（2026-06-27）
- **同义词库（2026-06-27 新增）：** 脚本内置 NAME_SYNONYMS 同义词组 + 层1.5配对逻辑
  - 已加入：弹垫=弹簧垫片=弹簧垫圈、电度表=电能表、角钢=角铁、螺母=螺帽、接触器=交流接触器、断路器=塑壳断路器、汇流零线排=汇流端子、终端电能计量表=电能表
  - 修复了电度表/电能表被 type_pairs_chk 错误排除的 bug
  - 持续扩展中，遇到新的同义词可搜索确认后加入
- **定时任务：** 每天17:30增量查重（当天新建vs历史）+ 每周六15:00全量排查，agentId: in3bot
- **IN3 访问问题（已解决 2026-05-18）：** ① 网址拼错！正确是 `industics`（没有r）② OpenClaw 浏览器需配 `--proxy-auto-detect` + `dangerouslyAllowPrivateNetwork: true`
- **Dongfang 指示（2026-05-13）：** 每次定时任务先试登录 IN3，不行就跳过告知他
- **⚠️ 教训：** `可疑重复物料_已验证_v5.xlsx` 是 AI 生成非人工核查，有大量误标，不可用作验证库

## Notion Worklog 规则（2026-05-22 新增）
- 每次完成有实质成果的工作（物料检查、重复报告等），通过 `sessions_send` 通知 Bot 5（agentId: `projectbot`），让它写入 Notion Worklog
- 通知内容：完成了什么工作 + 简短摘要
- 琐碎操作不需要记录，只有有实质成果的才记

## 物料重复检查近期结果
- 2026-06-08：0对确认重复，0对待确认（17228条记录），规则优化效果显著
- 2026-08-15（周六全量）：确认重复 7 对，待人工确认 31 对（18639条记录）。确认重复含：塑壳断路器/触摸屏空格差异、水平母线框完全相同、互感器格式差异、同义词对（万能转换开关=转换开关、电度表=电能表）。报告已发送 Telegram

## 采购价格异常经验（2026-06-15）
- 公司选择器无法展开时，可用最近一次的历史数据文件代替导出
- 脚本 `price_anomaly_daily.py` 有容错机制，能自动查找最近数据文件

## 新物料网上比价Sheet字段要求（2026-06-21 Dongfang确认）
必须包含：物料编号、采购订单号、物料名称、规格描述、采购单价、采购数量、采购总金额、采购单位、供应商、采购申请人、**销售订单号、销售订单名称、合同编号、合同名称**
- 脚本已更新 `price_anomaly_daily.py`，新物料字典和 Sheet 3 列均已加入这些字段

## 发送文件经验（2026-06-18）
- **message 发 Excel 文件必须用 `media` 参数**，不能用 `filename` 参数（`filename` 只发文字不发文件）
- 正确用法：`media="/path/to/file.xlsx"` + `message="说明文字"`
- 错误用法：`filename="xxx.xlsx"` 只会在消息里显示文件名文字
- 操作网站时多用 screenshot（peekaboo）确认页面状态

## 命名规范检查定时任务（2026-06-25 修复）
- **独立 cron 任务** — `in3-naming-check` (ID: 20235245-52bc-4503-b831-8365dc0db296)，每天17:45（周一到周六）
- **独立于查重任务** — 即使查重 cron 失败，命名检查也能独立执行
- **智能复用** — 如果查重任务已下载当天物料文件，直接复用，不重复下载
- **无问题不发消息** — 只有发现问题才通知 Dongfang
- **脚本：** `IN3数据/naming_check.py`（自动找最新物料文件，自动筛选当天新建/修改物料）
- **之前的问题：** 命名检查绑在查重 cron 的 Step 5，查重一旦失败命名检查也不会执行。现在拆分独立后彻底解决

## 查重规则更新（2026-06-26 Dongfang 反馈）
- **型号末尾 F=辅助触头** — 一方有F一方没有 = 非重复（如 WG160/160/3F vs WG160/160/3）
- **型号末尾 P=板前接线** — 一方有P一方没有 = 非重复（如 BM3E-400C/3400 400A P vs BM3E-400C/3400 400A）
- **型号末尾 R=板后接线** — 同理
- **型号末尾 SD=信号接点** — 同理（如 iC65N 带SD接点 vs iC65N）
- **型号末尾 FM=遥信模块** — 同理
- **规则 #46（2026-06-26 升级）** — 品牌命名规则知识库驱动，替代旧#45硬编码
  - 数据来源：11品牌51系列选型手册PDF/官网
  - 后缀代号数：63个（附件34 + 安装8 + 接线13 + 脱扣器12 + 兜底硬编码）
 - 文件：`IN3数据/brand_naming_rules/naming_rules.json` + `naming_rules_summary.md`
  - 待人工确认：188→164（减少24对正确排除），确认重复不变（无误杀）
  - 极数上下文（3P/4P/3D）已排除，不会误触发
- **查重时学习命名规则的方法（Dongfang 2026-06-26 确认）** — 以后遇到型号/品牌元器件疑似重复，可以上网搜索相关资料说明书，学习其命名规则来辅助判断是否重复
- **利驰电小二平台** — leadsoft.com.cn 旗下选型数据库，型号含义可参考其配置参数（如截图确认 F=辅助触头）
- **品牌型号命名规则知识库（2026-06-26建立，同日大规模扩展）** — `IN3数据/brand_naming_rules/naming_rules.json`
  - 覆盖**16个分类、149+个系列**（从初始11品牌51系列大幅扩展）
  - ABB: 6→20系列（新增Tmax T、Formula、OT/OTM、TruONE ATS、AX/AF接触器、TA/TF热继、MS电动机保护、OVR浪涌、CPX100、GSH/GS漏电、SD/S800隔离开关、VD4真空断路器、NX/NF中间继电器、PSTX软起动器、ACS510变频器）
  - 正泰: 6→19系列（新增NM1、NMB、NXM/NXB/NXBLE漏电断路器、NXC/NXR接触器、NJR2热继、LW转换开关、NA1/NP2按钮、NTC1时间继电器、HR5熔断器等）
  - 上海人民电器: 2→21系列（新增RDW5/RDM5/RDB5/RDC5接触器、RMW1框架、RMT双电源、RMS SPD等，发现用"RD"前缀体系）
  - 其他品牌保持原有系列数
  - 关键发现：正泰NM1分断能力C/S/H/R四级（≠常熟CM3的C/L/M/H）；ABB ACS510的-01是壁挂安装方式、-4是380-480V电压码
  - 数据来源：各品牌选型手册PDF + 官方网站
  - 人可读版：`naming_rules_summary.md`
  - **持续扩展中** — 施耐德、德力西、良信等品牌仍有系列待补充PDF

## 命名规范检查规则（Dongfang 2026-06-22 确认）
- **传感器不算大类统称** — 「传感器」本身已是最小品类名称，不应警告。VAGUE_NAMES 中不包含传感器
- **工、器具不需要写制造商** — FC开头物料（辅材/工器具）不检查制造商空缺，不提示
- **CP开头成品柜跳过全部检查** — 命名规范检查对CP开头物料直接跳过，不检查任何规则
- **报告必须包含变更人和变更时间** — Dongfang 2026-07-23 确认：命名规范检查报告必须包含「变更人」（最近修改人）和「变更时间」（最近修改日期），方便追溯是谁做的变更。脚本已更新，Excel 新增「变更人」「变更时间」两列
- **△符号允许在描述中使用** — Dongfang 2026-08-03 确认：△（三角形符号）从非标符号列表中移除，允许出现在物料描述中
- **颜色字作为词汇组成部分不报** — Dongfang 2026-08-03 确认："镀白锌""镀彩锌""红外""黑壳""绿灯指示"等，颜色字是词汇一部分（表面处理工艺/技术方式/颜色修饰功能件）的不算单纯标色，不警告。只有颜色字单独出现才警告
- **每次 Dongfang 的规则反馈必须记录** — 写入 MEMORY.md + 命名规范检查脚本，确保下次不重复犯错
