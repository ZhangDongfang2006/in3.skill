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
- 脚本自动筛选当天新增采购 vs 历史价格，偏离≥40%标记异常
- 如果无异常，输出「无价格异常」

## Step 5：发送结果
- 有异常：将生成的Excel cp到 /Users/zhangdongfang/.openclaw/media/，用 sessions_send 发给 agentId=company，sessionKey=agent:company:feishu:group:oc_498ec91554f3c3272cc6ae02ecf27557，让它发到飞书群
- 无异常：同样发消息到飞书群告知今天无价格异常（不需要发文件）
- 发送失败：用 message 发给 Dongfang（target: 8782649356, channel: telegram）告知失败原因

## 注意事项
- 网址 https://in3.industics.com/（industics没有r）
- IN3前端组件特殊，优先用evaluate+DOM查询操作
- 导出按钮只点一次
- 禁止重启 Gateway
- 如果浏览器操作失败/超时，直接重试
- 不要用 sleep 等待，用 browser snapshot 轮询检查状态
