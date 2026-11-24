# in3-cli 2026-05-19 升级公告

> 3 个 CLI 包升版本，agent 调用稳定性 + 数据准确性整体提升约 10 分（百分制 88.6 → 99.8）。配套 in3-cli skill 文档补 10+ 条踩坑指南。
> **升级方法**：把 `UPGRADE_GUIDE.md` 发给你的 Claude Code / Codex，说"按这个升级"即可。

---

## TL;DR

| 包 | 旧 → 新 | 修复 | 对你的影响 |
|---|---|---|---|
| `@industics/ibrain-mm-cli` | 0.4.0 → **0.4.1** | PO 行项 `open_qty=null` 自动 fallback 算 `purchase_qty - completed_qty`，并标 `_open_qty_source` meta | 算"未交付数量""缺口"不用再自己兜底；agent 写履约就绪度查询少一步推理 |
| `@industics/ibrain-wm-cli` | 0.1.8 → **0.1.9** | `stock` 的 `bin` / `storage-location` / `storage-bin` 三个视图补 `--material-ids` 多值并发 fan-out | N 个物料查库存从 N 次串行 HTTP 降到 1 次 call（前两轮评测最大成本瓶颈消失） |
| `@industics/ibrain-sd-cli` | 0.2.2 → **0.2.5** | `sales-order get` 大输出（>60KB）pipe 截断 bug 修复，对齐 mm-cli 0.3.1 的 flush 写法 | `\| jq` / Python `subprocess.run(capture_output=True)` 不再随机丢数据；debug 时省一轮 "jq parse error: Unfinished JSON term at EOF" |

`@industics/ibrain-pp-cli` 0.2.7 和 `@industics/in-mom-md-cli` 0.1.3 不变，无需升级。

---

## 评测背景

这次升级前后跑了 **5 轮真实业务问题闭环验证**，共 **25 道跨模块查询题**，覆盖 mm / wm / sd / pp / md 五个 CLI 的单模块基线、双模块联动、三+ 模块综合、业务约束特例（孤儿物料、不可对账数据源、紧固件 SO 缺口等）。每题由独立"裁判"按行为锚定 4 维度（正确性 / 鲁棒性 / 体验 / 成本）打分。

### 分数趋势

| 轮 | 加权 (满分 5.0) | 100 分制 | 增量 | 关键动作 |
|---|---:|---:|---:|---|
| R1 | 4.43 | 88.6 | 基线 | 测出 4 个真实 bug |
| R2 | 4.86 | 97.2 | **+8.6** | wm / sd 升版本 + skill 文档勘误 |
| R3 | 4.93 | 98.6 | +1.4 | skill 加 8 条新踩坑 + 孤儿物料模板 |
| R4 | 4.91 | 98.2 | -0.4 | mm 升 0.4.1 修 `open_qty`；R3 触顶后小噪声 |
| **R5** | **4.99** | **99.8** | +1.6 | skill 加 Top-N 伪物料剔除模板 |

R3 起 **0 被动触雷**（连续 3 轮）。

### 严格门槛 PASS

- 加权总分每轮 ≥ 4.0 ✓
- L1 单模块题各项 ≥ 3 ✓
- 被动触雷 ≤ 8 条 ✓（最终 0 条）

---

## 你最关心的几件事

### 1. 升级会破坏什么吗？

**不会。**

- 业务后端代码 **0 改动**（5 个业务仓 `git status` 验证，所有改动都在各仓的 `cli/` 子目录里）
- CLI 包修的是 bug 和加 fallback，**没有 breaking change**
- 已在 prod / indx 租户上跑了 200+ 次只读 API 验证，全程无任何写操作

### 2. 不升级会怎样？

继续踩前面提到的 3 个 bug：

- **mm 0.4.0**：算"未交付数量"会拿到 null，agent 容易给出 NaN 或错误的缺口数字
- **wm 0.1.8**：查多个物料的库存只能在 agent 端 fan-out N 次（前两轮评测的 Q3 用 wm 0.1.8 跑了 42 次串行 HTTP，升 0.1.9 后变成 1 次）
- **sd 0.2.2**：`sales-order get` pipe 大输出有概率截断，agent 调试时会浪费一轮看 stderr

### 3. 升级路径

把 `UPGRADE_GUIDE.md` 整段文档发给你的 Claude Code / Codex，说"按这个升级"。Agent 会：

1. 定位 in3-cli skill 入口
2. 跑 status 快照当前版本
3. `upgrade mm / wm / sd` 三条
4. `sync` 把 in3 profile 写回（**这一步不能跳**——sd 升级会重置 `current_context` 到 qa）
5. 跑 `--version` + `status` + `test-all` 验证

全程大约 30 秒。

### 4. 多人协作 / 多个租户怎么办？

每个人各自的本地环境独立升。如果你登过多个租户（prod / qa / test），升级**不会动**你本地保存的主凭证，只动 npm 全局包；`sync` 会把所有已登模块的 in3 profile 一次性刷新到当前激活的 context。

---

## in3-cli skill 文档同步更新

`SKILL.md` 加了下面这些"前 N 轮反复踩过、值得首次就避开"的指南：

- **zsh shell quoting 防呆**：`--filter material_ids=X --filter material_ids=Y` 多值时变量必须 quote，否则 zsh 分词会让 multi filter 被静默忽略——这条曾让 R1 评测误诊 mm 后端"bug"，curl 反证后写进文档
- **multi filter 是否真生效的验证方法**：1 个值 vs N 个值跑两遍对比 `items.length`
- **8 条 Round 2-3 新发现的雷**：sd `from_ordered_at` 是 datetime / mm `--include-items` payload 可膨胀 ~20x / sd `status='A'` SO products 也可能全 null / mm `bom list` items 全是子组件（parent 是入参） / wm `stock bin` 同物料多货位拆多行（要 client `group_by`） / md 字典类默认 `size=20`（要 `--max 500` 拿全） / wm `stock` 裸拉返空安全阀 / mm `header.total` 单页查询返真值 0
- **"孤儿物料"识别模板**：`list + set diff` 套路，2 次 HTTP 替代 N 次 `md material get` fan-out
- **Top-N 物料分析的"伪物料"剔除 jq 模板**：剔除 `WGJ_00` / `FY_` / 运费 / 杂费 / 批领等会霸榜的虚假物料

版本速查表全部更新到当前在线版本，"按物料反查端点速查表"wm 行更新到 0.1.9 全视图支持。

---

## 下一步建议（团队层面的长线工作）

以下是评测里反复出现的优化方向，不影响本次升级，但值得后续投入：

| 优先级 | 事项 | 价值 |
|---|---|---|
| P0 | 沉淀"全租户聚合 + 一次 list" 范式到 skill 专章 | 每条 cross-module 查询平均省 50+ HTTP call |
| P1 | 伪物料剔除 marker 做成租户级配置 | indx 租户 marker 在 `material_category`，文档默认在 `material_no`——跨租户硬编码会漂移 |
| L | 5 个 skill 精修级文档缺口（marker 位置 / md.currency_no 全 null / wm 安全阀边界 / BOM tree 反查表 / Step 1 升级克制对称描述） | 体验侧打磨，单次补完 |

如果想推进 P0 / P1，回来说一声即可启动新一轮闭环验证。

---

## 联系方式

- 升级命令出错 → 看 `UPGRADE_GUIDE.md` 的 "## 出错怎么办" 一节
- 评测细节 / 单题 trace / judge 评分原文 → 联系本次评测发起人取 workspace 完整产出
- 想给自己模块也做一轮同款评测 → 同上
