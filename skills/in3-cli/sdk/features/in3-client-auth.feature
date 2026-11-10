# language: zh-CN
功能: in3_client 认证（password-grant 兜底路）
  作为 跑 IN3 查询的 agent
  我想 SDK 自己读 workspace 凭证换 token 并组装鉴权头
  以便 我不必手工处理 OAuth / AES / 401 重试

  覆盖 Build-PRD 用户故事 21,22,23（issue #1 脊柱）— RTM #21, #22, #23
  注：浏览器 OAuth 是 issue #8（门禁 M0.5）；本 feature 只覆盖 password-grant 兜底路。

  背景:
    假定 一个已登录租户的 credentials.json 存有 api_host、tenant_domain、username、user_id 和一段 AES 加密口令串
    并且UAAS token 端点 /uaas/oauth/token 已被 mock

  场景: RTM #21 — password-grant 直发 AES 串、不解密
    当 SDK 取 token
    那么 它向 /uaas/oauth/token 发 grant_type=password 请求
    并且请求的 password 字段等于 credentials.json 里那段 AES 串（逐字一致、未解密）
    并且SDK 代码中不存在任何 AES 解密逻辑

  场景: RTM #22 — 每个数据请求组装三个鉴权头
    假定 已拿到 access_token、tenant_domain 与 user_id
    当 SDK 发起任意数据请求
    那么 请求头 Authorization 等于 "Bearer <access_token>"
    并且请求头 T-CODE 等于 tenant_domain
    并且请求头 X-Operator-ID 等于 user_id

  场景: RTM #23 — 401 清 token 重试一次
    假定 第一次数据请求返回 401
    当 SDK 处理该响应
    那么 它清除当前 token、重新换 token 并仅重试一次
    并且若重试仍 401 则抛认证错误（不静默吞）

  场景: RTM #23 — 200 但非 JSON 视为认证失败
    假定 网关对数据请求返回 HTTP 200 且 content-type 不是 JSON（HTML 重定向页）
    当 SDK 处理该响应
    那么 它判定为认证失败并抛错
    并且绝不把 HTML 当作空结果或 0 行返回

  场景: RTM #21 — credentials.json 缺失 fail-loud
    假定 credentials.json 缺失或关键字段缺失
    当 SDK 构造 Session
    那么 它抛出明确错误
    并且不返回空 Session、不静默继续
