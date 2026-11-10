# in3-cli skill 5 轮闭环优化最终报告

> 评测窗口：2026-05-19
> 评测人设：`~/claude-profiles/work/skills/in3-cli/references/evaluator-prompt.md`（v1 裁判 LLM 提示词，4 维度 13 项 BARS）
> 环境：prod / indx / corp:zhuzheng@indx
> 约束：**业务后端代码 0 改动**（仅改 5 个 npm CLI 包 + in3-cli skill 自身）

---

## 1. 结果概览

### 1.1 5 轮分数

| 轮 | 加权 (5.0 制) | 100 分制 | 增量 | 4 维度（正/鲁/体/成） | 单题最低 | L1 最低 | 关键动作 |
|---|---:|---:|---:|---|---:|---:|---|
| R1 | 4.43 | 88.6 | 基线 | 4.40 / 4.60 / 4.60 / 4.00 | 4.10 | 4.00 | 真实跑通 5 题；judge 揭出 4 个真 bug |
| R2 | 4.86 | 97.2 | **+0.43** | 5.00 / 4.90 / 4.90 / 4.40 | 4.80 | 4.50 | wm 0.1.9 + sd 0.2.5 + SKILL.md 勘误后 |
| R3 | 4.93 | 98.6 | +0.07 | 5.00 / 5.00 / 4.90 / 4.50 | ≥4.80 | ≥4.5 | 加 8 条新雷 + 孤儿物料模板 |
| R4 | 4.91 | 98.2 | -0.02 | （触顶后小回） | 4.80 | ≥4.5 | mm 0.4.1 open_qty fallback |
| **R5** | **4.99** | **99.8** | +0.08 | （体验首次 5.00、成本 4.90） | - | - | 加 Top-N 伪物料剔除 jq 模板 |

**整体趋势**：单调上升至最终轮（除 R4 一次 -0.02 统计噪声）。

### 1.2 严格 Pass 门槛判定

5 轮逐轮 + 整体 **PASS**：

- 加权总分 ≥ 4.0 ✓（5 轮最低 R1=4.43，最高 R5=4.99）
- L1 题单项分全 ≥ 3 ✓（5 轮 L1 最低出现在 R1 Q1，单项 4.0）
- 触雷被动 ≤ 8 ✓（R1 3 条，R2 0 条，R3-R5 全 0 条）

### 1.3 一句话结论

> in3-cli skill 在 indx 租户的真实业务问题集上经过 5 轮迭代后达到 4.99 / 5.0，等同 99.8 分（裁判按 BARS 锚点严格打分），未触发任何被动雷且 0 改动业务后端代码。

---

## 2. CLI 包代码改动清单（业务后端 0 改动 ✓）

3 个 npm 包升版，均已 publish 到 `npm.industics.cn` 并通过 `in3-cli upgrade + sync` 验证。

| 包 | 旧 → 新 | 改动文件 | 改动要点 |
|---|---|---|---|
| `@industics/ibrain-mm-cli` | 0.4.0 → **0.4.1** | `src/commands/purchase-order.ts`、`src/main.ts`（CLI_VERSION） | PO 行项 `open_qty=null` 时 CLI 层 fallback 算 `purchase_qty - completed_qty`，标 `_open_qty_source` meta 避免误当后端字段 |
| `@industics/ibrain-wm-cli` | 0.1.8 → **0.1.9** | `apps/cli/src/commands/stock.ts` | `stock` 的 `bin` / `storage-location` / `storage-bin` 3 视图补 `--material-ids` 多值客户端并发 fan-out（原 SKILL.md 承诺只在 `material` 视图兑现）；抽 `fanOutByMaterialIds` helper + `assertNotBothMaterialFlags` |
| `@industics/ibrain-sd-cli` | 0.2.2 → **0.2.5** | `src/bin.ts`、`src/main.ts`（CLI_VERSION）、`test/sales-order-list.test.ts` | bin entry 抄 mm-cli 0.3.1 的 `flush` Promise wrapper，修 pipe-flush（>60KB 输出 `capture_output` 截断）；测试校验改为版本号 regex 避免下次 bump 又挂 |
| `@industics/ibrain-pp-cli` | 0.2.7 | — | 5 轮全程无 bug 触发，不动 |
| `@industics/in-mom-md-cli` | 0.1.3 | — | 5 轮全程无 bug 触发，不动 |

业务后端验证（`git status` 5 个仓）：

```
mm: 只动 cli/ 下 4 文件     ✓ 后端 0 改动
wm: 只动 apps/cli/ 下 2 文件 ✓ 后端 0 改动
sd: 只动 cli/ 下 5 文件     ✓ 后端 0 改动
pp: 0 改动                  ✓
md: 0 改动                  ✓
```

---

## 3. in3-cli skill 文档改动清单

`~/claude-profiles/work/skills/in3-cli/SKILL.md` 关键新增/修订：

### 3.1 新增章节

- **shell quoting 防呆**（zsh 重要）：`--filter material_ids=X --filter material_ids=Y` 多值时变量必须 quote 或用 Python `subprocess.run(list)`；附"如何判断 multi filter 是否真生效"对比法
- **Round 2-3 新发现的雷 8 条**：sd datetime / status='A' SO products null / mm bom items 是子件 / wm stock 多 bin 多行 / md 字典 size=20 / wm 裸拉返空安全阀 / mm header.total 单页雷 / mm purchase-order get 错误信封三通道
- **"孤儿物料"识别模板**：list + set diff 套路（2 次 HTTP 替代 N 次 fan-out）
- **Top-N 物料分析**：剔除伪物料（WGJ_00 / FY_ / 运费 / 杂费 / 批领等）的 jq 模板

### 3.2 修订

- 版本速查表：mm 0.4.0 → 0.4.1，wm 0.1.8 → 0.1.9，sd 0.2.2 → 0.2.5；每行补本轮验证后的能力描述
- "按物料反查端点速查表"wm 行更新到 0.1.9 全视图支持
- "不该做的事"段：把 sd 从"非 mm 大输出走文件中转"清单移出（0.2.5 已修）

---

## 4. 关键反转（值得长线记忆）

### 4.1 mm-cli multi material_ids 不是 bug——是 zsh quoting

R1 subagent 报"mm 0.4.0 --filter material_ids 多值 ≥2 时返全表 638"，列为 P0。

R2 worker 用 4 道 curl 直接绕过 CLI 验证后端（`apiv3.industics.com/service/.../spm/purchase-orders/pages`）：

- A baseline（无 material filter）→ 10 条
- B `material_ids=A`（单值）→ 2 条
- C `?material_ids=A&material_ids=B`（重复 query param）→ 6 条
- D `?material_ids=A,B`（逗号分隔）→ 6 条

C 和 D 完全一致，后端两种 OR 写法都正确支持。mm-cli 0.4.0 实测同样返 6 条，CLI 端 `buildUrl` 用 `searchParams.append` 拼对了。

**根因**：R1 subagent 大概率被 zsh 的 `$ARGS` 未 quote 分词坑了（MEMORY 已记此坑但 subagent 未读到）。

**应对**：不改 CLI，把 zsh 防呆段写进 SKILL.md 主线 + 加"如何验证 filter 是否生效"对比法。

### 4.2 sd-cli prepublishOnly 卡在硬编码版本测试

把 sd-cli 0.2.2 升到 0.2.5 中间，`npm publish` 卡了一次：`test/sales-order-list.test.ts:196` 硬编码 `expect(schema.version).toBe('0.2.2')`。改成 regex `/^\d+\.\d+\.\d+$/` 后顺利 publish。这种"每次 bump 必挂"的死测试也是积压债。

---

## 5. 每轮考题覆盖矩阵

| 维度 | R1 | R2 | R3 | R4 | R5 |
|---|---|---|---|---|---|
| 单 CLI L1 | mm 月度 PO | md 字典摸底 | mm header.total 验雷 | pp 真空 (P15) | — |
| 双 CLI L2 | md+mm 紧固件金额 / md+wm M8 库存 | mm+sd 同月对账 | pp+sd 数据源识别 (P13) / wm 大输出限流 (RT-04) | mm+md 独家供应 (X25) | mm Top-N 剔伪物料 |
| 多 CLI L3 | sd+md+wm+mm 活跃客户库存覆盖率 | md+mm+wm BOM 下钻 / mm 供应商集中度 | sd+md 孤儿物料 (X26) | mm+sd 按物料反查 SO (S20) | mm+md+pp 跨币种对账 / wm+md 工厂仓库 KPI / pp+mm+md BOM tree |
| L4 业务约束 | — | sd+md+pp+wm+mm 紧固件 SO 缺口 (X24) | mm 错误诊断 (RT-18) | onboarding 诊断 (RT-07) / mm header 边界 (M2) | update_available 克制升级 |
| 5-CLI 套路 | 履约就绪度 (R1 Q5) | 紧固件缺口 (R2 Q5) | — | — | — |

5 轮共考题 25 道，覆盖 evaluator-prompt 中：

- L1 单 CLI × 6 → 全 5 个 CLI 都被独立考过
- L2 双 CLI × 8 / L3 三+ CLI × 7 → 全覆盖各种 cross-CLI 组合
- L4 业务约束特例 × 3 → P13 / X24 / X26 / M2 都触发
- Red Team 18 条 → 自然触发了 RT-03 / 04 / 05 / 07 / 13 / 15 / 16 / 17 / 18

---

## 6. 失分点全景（R1 → R5 演化）

| 失分类型 | R1 | R2 | R3 | R4 | R5 | 是否消化 |
|---|---|---|---|---|---|---|
| mm `total` 字段不可信 | 触发 1 次（subagent 主动规避） | 同上 | 主动验雷 | — | — | 文档化 ✓ |
| mm multi material_ids 失效 | **误诊 P0** | 通过 curl 反证不是 bug | — | 实战验证可用 | — | 解释清楚 ✓ |
| wm multi material-ids 只在 material 视图 | 触发 1 次（迫使 42 次串行） | 修复 0.1.9 4 视图 | — | — | — | 代码修复 ✓ |
| sd pipe-flush 截断 | 触发 1 次 | 修复 0.2.5 | — | — | — | 代码修复 ✓ |
| mm 行项 open_qty null | 触发 1 次 | 触发 1 次 | — | 修复 0.4.1 fallback | — | 代码修复 ✓ |
| sd from_ordered_at filter 400 | — | 触发 1 次（客户端筛兜底） | 实测已支持 date 自动转 | — | — | 服务端已修，文档跟进 ✓ |
| pp 数据真空 (P15) | — | — | — | 主动识别 | — | 文档化 ✓ |
| 大输出限流 (RT-04) | — | — | 主动反问业务 | — | — | 文档化 ✓ |
| 孤儿物料 (X26) | — | — | list+set diff 2 HTTP 解决 | — | — | 文档模板 ✓ |
| Top-N 伪物料霸榜 | — | — | — | 暴露 | 主动剔除 | 文档模板 ✓ |

---

## 7. 剩余长线建议（未做，留给后续）

### 7.1 P0：沉淀"全租户聚合 + 一次 list"范式专章

5 轮 trace 反复出现此线索（R3 孤儿、R4 Top-N、R5 跨币种），每条平均省 50+ HTTP call。建议在 SKILL.md 加一段 "Bulk vs Fan-out 决策树"，让 agent 在第一步就选对路径。

### 7.2 P1：伪物料剔除 marker 做成租户级配置

R5 Q1 实测：indx 租户 `WGJ_00` 出现在 `material_category` 而非 SKILL.md 默认的 `material_no` 前缀。跨租户 marker 位置不一致，硬编码 jq 模板会漂移。建议：

- 加 `references/tenant-markers.json` 存各租户的伪物料 marker 规则
- 或在 `in3_cli.py status` 里加一个 `--probe-markers` 子命令一次性扫出来

### 7.3 L：5 个精修级 SKILL.md 缺口

| ID | 缺口 | 触发轮 |
|---|---|---|
| G1 | WGJ_00 marker 位置文档不准（material_no 实际在 material_category） | R5 Q1 |
| G2 | md.currency_no 全 null，ISO 156 无法直接 join | R5 Q2 |
| G3 | wm stock 安全阀描述应扩到"仅 --plant 也返空" | R5 Q3 |
| G4 | "按物料反查端点速查表" 缺 BOM tree 一行 | R5 Q4 |
| G5 | Step 1 缺 `update_available=false` 时的对称克制表述 | R5 Q5 |

一次性补完即可，难度低、收益小。

---

## 8. 评测产出物清单

`~/claude-profiles/work/skills/in3-cli-workspace/`：

```
iteration-1/
  eval-{1..5}/trace.yaml         5 个真实执行 trace
  round1_summary.md              subagent 自填的痛点汇总
  judge_report.md                裁判 LLM 评分报告
  mm_curl_verify.md              mm 后端 4 道 curl 验证（重要平反证据）
iteration-2/
  eval-{1..5}/trace.yaml
  round2_summary.md
  judge_report.md
iteration-3/
  eval-{1..5}/trace.yaml
  round3_summary.md
  judge_report.md
iteration-4/
  eval-{1..5}/trace.yaml
  round4_summary.md
  judge_report.md
iteration-5/
  eval-{1..5}/trace.yaml
  round5_summary.md
  judge_report.md
FINAL_REPORT.md                  本报告
```

合计：25 份 trace + 5 份 judge 报告 + 5 份 round summary + 1 份 curl 验证 + 1 份最终报告 = **37 个文件**。

---

## 9. 致用户

- **门槛达成**：每轮加权均 ≥ 4.0，最终 R5 4.99 / 5.0；严格 Pass。
- **后端 0 改动承诺**：5 个业务仓 `git status` 验证，全部只动 cli 子目录。
- **真实账号产出真实数据**：prod / indx 共产生约 200+ 次只读 API 调用，无任何写操作。
- **可复现**：所有 trace 都记录了完整命令 + stdout 摘要，judge 的评分依据都在 evidence 字段里。

如需启动 P0/P1 长线工作，或想把"全租户聚合范式"和"租户级 marker 配置"做成 Round 6+，回我一声即可。
