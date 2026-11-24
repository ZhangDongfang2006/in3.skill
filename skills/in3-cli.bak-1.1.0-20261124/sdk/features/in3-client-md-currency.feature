# language: zh-CN
功能: md.currency 端到端查询与 CLI parity（第一颗 tracer bullet）
  作为 跑 IN3 查询的 agent
  我想 import in3_client 直接查币种字典并拿到归一结果
  以便 验证整条脊柱（config→auth→http→envelope→pagination）打通且与 CLI 逐位一致

  覆盖 Build-PRD 用户故事 1,8,31（issue #1）— RTM #1, #8, #31

  背景:
    假定 一个已登录租户的 workspace（credentials.json 就位）
    并且md currency 端点的录制 fixture 已就位

  场景: RTM #8 — import 直跑（A surface，不经 run 壳）
    当 一段 Python 在 import in3_client 后调用 in3.md.currency.list()
    那么 它无需经 run 壳即可返回一个 Page
    并且该 Page 的 items 为归一后的币种记录

  场景: RTM #1 — 脊柱端到端打通
    当 in3.md.currency.list() 执行
    那么 它依次走 config 读凭证、auth 换 token、GET /mdm/currencies/page、envelope 归一、pagination
    并且返回统一的 Page{items, page, total, has_next}

  场景: RTM #31 — 与现有 CLI 路径逐位一致（parity 硬门禁）
    假定 同一 currency 查询分别走 SDK 路径与现有 CLI 路径
    当 比对两条路径的产出
    那么 业务数字（含币种码字段）逐位一致
    并且任一位不一致即判 parity FAIL（一票否决）

  场景: RTM #1 — 本片 md.currency 不做 156↔CNY 表示归一
    当 in3.md.currency.list() 返回币种记录
    那么 币种码原样穿过
    并且156↔CNY 表示归一留待 issue #7 的 normalize_currency
