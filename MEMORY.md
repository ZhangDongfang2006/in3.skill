placeholder-check
## CLI 优先铁律（2026-11-23 Dongfang 指令）
- **IN3 一切查询优先走 in3-cli（SDK/CLI），禁止爬网页**。网页 CDP 只在 CLI 完全不可用时兜底，且用完要报告原因。
- 老账号 18392180970 密码 grant 被拒（haiyue 走 SSO），用「浏览器会话抓 Bearer token → login --paste-token --token-stdin」登录；token 约 8h 过期。
- SDK 用法：in3_client.IN3.from_token(api_host, access_token, tenant_id, tenant_domain, user_id)，四参数都要传（漏 tenant_id 则 URL tenants/ 为空 → 404）。
- 跨公司实测（2026-11-23）：PO 12812（HY02 8306/HY01 4506）✅；采购合同 4834（HY02 2058/HY01 2776）✅；工单 5376/领料 8461/客户 1069/供应商 2393 ✅；**销售订单与销售合同只有 HY01（各480）⚠️ HY02 销售侧在 sd 接口查不到，需确认宁波销售单据在哪个组织/模块**。
- filter 不支持 company_code（声明外 key 报错防静默忽略），分公司统计用 all=True 拉全量本地分桶。
- material-doc/大表 SSL EOF 偶发：缩 size + 重试。

## HY02 销售单据缺失根因（2026-11-23 定案）
- 现象：sd.sales_order/sd.contract 全量只见 HY01；HY02 一张没有。
- 根因：**SDK/CLI 的 sd.contract filter_keys 声明漏了 company_id**（声明外 key 会被拒）；sd.sales_order 声明里有 company_id 可用。
- 后端实际支持：GET sales-orders/page?company_id=<HY02 id> → 1,499 张 ✅；GET contracts 端点 raw 带 company_id → 1,473 张 ✅（绕过 SDK 校验直打 HTTP 即可）。
- 结论：**不是宁波海越没有销售数据，是 in3-cli 1.5.0 的 sd.contract filter 声明不全**。已实证三单样例（SO2611040 浙江中云 等，今日仍有新单）。
- 公司 ID：HY01=562051706024898304，HY02=567646444086142720。
- 修复方向：给供应商反馈补 sd.contract filter_keys（+contract 端点）；临时方案用 http.get_page 直打。
