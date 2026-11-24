# language: zh-CN
功能: POC 端到端验收（北极星）— 采购集中度 × 库存 × 独家供应
  作为 决定 v1 该不该 ship 的干系人
  我想 同一任务用 CLI 现状路径与 SDK/run 路径各跑一遍并量四指标
  以便 用实测数据而非断言裁决 M4 go/no-go

  覆盖 Build-PRD 用户故事 7,32 + Decision Gate（issue #9）— RTM #7, #32
  注：这是整个 v1 的北极星验收；issue #1–#7 的所有切片都朝它收敛。

  背景:
    假定 2026-05 的采购订单、可用库存、供应商数据可查（跨 mm+wm+md）
    并且同一 POC 任务集分别走 CLI 现状路径与 SDK/run 路径

  场景: RTM #7 — 主任务一次脚本成型（轮次↓）
    当 用 SDK/run 跑「本月采购金额 Top10 物料 × 各自 wm 可用库存 × 标独家供应」
    那么 完成所需 LLM 推理轮次落在 1–3 轮
    并且中间数据不进 LLM 上下文、只 print 最终结果

  场景: RTM #32 — 指标① parity 逐位一致（硬门禁）
    当 比对 SDK 路径与 CLI 路径对主任务的业务数字
    那么 Top10 采购金额、可用库存数量、独家供应标记、币种逐位一致
    并且任一位不一致即整体验收 FAIL

  场景: RTM #32 — 指标② token 降幅达阈值
    当 量同一任务端到端进 LLM 的 token
    那么 SDK 路径相对 CLI 路径降幅达到阈值（暂定 ≥70%，以设计 PRD §5.2 为准）

  场景: RTM #32 — 指标④ doctor BARS 不退（非翻 PASS）
    当 用 in3-cli-doctor 对 SDK 版跑 BARS
    那么 关键分项 #3/#14/#15 不低于当前基线且加权总分不退
    并且报告把"不退"与"翻 PASS"明确区分（翻 PASS 是 bonus、非门禁）

  场景: RTM #7 — partial 失败 fail-loud（防 ¥111K 静默丢单）
    假定 主任务中某个 fan-out 子查询失败
    当 SDK 路径处理该失败
    那么 它 fail-loud（抛错或显式标记）
    并且绝不静默返回空集导致 Top10 金额/库存少算

  场景: RTM #7 — 孤儿物料保留（防漏算）
    假定 某 material_id 在 md.material 无对应记录
    当 主任务做跨模块 join
    那么 该行被保留并标 _orphan
    并且不被静默丢弃

  场景: RTM #32 — M4 go/no-go 由人裁决
    假定 四指标实测值已记入 BEFORE-AFTER.md
    当 团队/干系人评审
    那么 按「①必过 + ②③达阈值 + ④不退」裁决是否 ship
    并且决策由人显式确认、不由 agent 自判
