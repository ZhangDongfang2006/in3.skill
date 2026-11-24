# 主数据巡检 · 定时运行提示词（喂给客户端定时任务的 agent）

把本段作为客户端定时任务（Claude Desktop / Codex 等）的提示词。agent 据此跑确定性脚本拿
shortlist，再做"判读层"（ADR-0001 的"判"侧）策展成 Sourcing 可用核验单。

## 前置（一次性）
- 凭证：环境变量 `IN3_AGENT_CLIENT_ID` / `IN3_AGENT_CLIENT_SECRET`（AGENT client_credentials；
  机器令牌无人值守，绕用户价格权限闸，见 [[in3-cli-client-credentials-auth]]）。
- 脚本目录：`engineering/skills/in3-cli/sdk/poc/mdm-sentinel/`。

## 每次运行做三件事

1. **算（确定性，可经 in3-mcp `execute_code` 跑）**：
   `python3 mdm_sentinel.py report.html`
   → 拉 info-record（价格+描述）→ PCS 门槛 + 信号 C（包装规格抽取）+ P（跨供应商价差）
   → 规则化分级 → `report_shortlist.json`（几十条，不把原始数据进上下文）。
   （信号 Q=PO 采购数量当前被 AGENT 权限挡住，自动降级 C+P；开通 PO 读权限后自动启用。）

2. **判（你来做的判读层）**：读 `report_shortlist.json`，按优先级策展：
   - **P0 确诊·包装单位错配**：`cause` 含"包装单位错配"（价差≈包装规格）。**最高置信**，
     `note` 已给建议纠正 PCS 单价（=最高价÷包装规格）。逐条复核纠正价是否合理。
   - **P1 强疑似·包装类**：有包装规格 + 极端价差但价差≠包装规格。核高价记录是否按包/盒/卷录入。
   - **P3 价格离散·非包装**：无包装规格、纯价差≥10×。**属另一类口径问题，不在包装单位整改范围**，
     只抽查极端值（≥1000×），别让它淹没 P0/P1。
   你可直接跑 `python3 judge_report.py report_shortlist.json sourcing.html` 出分组骨架，
   再补：① 精炼执行简报（一句话讲清"几条确诊、建议立即改价"）；② **误报研判**——
   P0 里若"价差≈包装规格"疑为巧合（如该料价差本就因规格差异），标注存疑降级。

3. **报**：产出 `sourcing.html`（只读核验单）。如需推送，附一句摘要给 Sourcing/朱政。

## 判读纪律
- 不复算、不臆造数字——所有价差/建议纠正价以脚本输出为准，你只做分类、研判、措辞。
- 高度疑似只认包装佐证的（纯价格离散降中度），避免确诊高危被机械料价差淹没。
- v1 无状态：每期全量重报，已核验误报会重复出现（已知局限，轻状态后置，见 CONTEXT.md）。
- 锚点自检：扎带 **EL00556 必须落 P0 确诊**（田野旧模型给它 28/观察会漏掉，本设计就是修这个）。
