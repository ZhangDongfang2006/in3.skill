# IN3 每日采购价格异常检查任务指令

## Step 1：导出宁波采购订单明细
1. 打开IN3浏览器，打开 https://in3.industrics.com/
2. 确认登录状态（如未登录则登录：企业haiyue，账号18392180970，密码Start12345@）
3. 确认当前是宁波工厂，进入采购管理→采购订单管理
4. 确保在明细视图（不是单据视图），直接点「批量导出」→「导出全部字段」
5. 不需要筛选日期，直接导出全量open PO

## Step 2：导出湖北采购订单明细
1. 切换到湖北工厂（孝昌工厂）
2. 同样进入采购订单管理→明细视图→批量导出→导出全部字段
3. 如果湖北IN3无法访问（SSL错误等），用最新已有湖北文件代替，注明日期

## Step 3：下载文件
1. 进入下载中心（https://in3.industics.com/tc/list），等导出完成（通常3-4分钟）
2. 用 evaluate 获取下载链接，curl下载两个xlsx到 IN3数据/
3. 命名：采购订单明细-宁波-YYYYMMDD.xlsx 和 采购订单明细-湖北-YYYYMMDD.xlsx
4. 必须用 openpyxl.load_workbook() 不带 read_only=True（IN3导出xlsx有dimension bug）
5. 验证数据：确认行数>10，列数>20

## Step 4：运行分析脚本
```bash
cd /Users/zhangdongfang/.openclaw/workspace-in3bot && python3 IN3数据/price_anomaly_daily.py
```
- 增强版 v2：自动获取长江现货铜价，分三类分析
- 铜排/电线 → 按当日铜价计算基准价（+10%/15%加工费）
- 标准元器件/其他 → 按历史均价对比，偏离度从高到低
- 螺丝/标准件/走线槽 → 自动跳过
- 全部列出不筛选，Excel 含 3 个 Sheet
- 新物料中的元器件（排除钢板/电热管/挡板等）→ 用 tavily_search 网上搜价对比

## Step 5：发送结果
## Step 5：发送结果
- 将生成的Excel cp到 /Users/zhangdongfang/.openclaw/media/
- 用 message 发给 Dongfang（target: 8782649356, channel: telegram, media=文件路径）
- 同时用 sessions_send 发给飞书群（agentId=company, sessionKey=agent:company:feishu:group:oc_498ec91554f3c3272cc6ae02ecf27557），让 Bot 10 发到飞书群
- 发送失败：用 message 通知 Dongfang

## 注意事项
- 网址 https://in3.industics.com/（industics没有r）
- IN3前端组件特殊，优先用evaluate+DOM查询操作
- 导出按钮只点一次
- 禁止重启 Gateway
- 如果浏览器操作失败/超时，直接重试
- 不要用 sleep 等待，用 browser snapshot 轮询检查状态
