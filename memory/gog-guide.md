# gog (Google Workspace CLI) 使用教程

## 环境配置

### 代理（必须）
gog 访问 Google API 需要代理，所有命令前加环境变量：
```bash
export https_proxy=http://127.0.0.1:7897
export http_proxy=http://127.0.0.1:7897
```

### 账号
```bash
# 所有命令都需要指定账号
--account zhangdongfang990@gmail.com

# 或设环境变量一劳永逸
export GOG_ACCOUNT=zhangdongfang990@gmail.com
```

## 常用命令

### Gmail 邮件

```bash
# 搜索未读邮件
gog gmail search "is:unread" --account zhangdongfang990@gmail.com --max 10

# 搜索最近7天邮件
gog gmail search "newer_than:7d" --max 20

# 搜索特定发件人
gog gmail search "from:example@example.com" --max 10

# 发送邮件（纯文本）
gog gmail send --to recipient@example.com --subject "标题" --body "内容"

# 发送邮件（多行，用文件）
gog gmail send --to recipient@example.com --subject "标题" --body-file ./message.txt

# 发送邮件（HTML）
gog gmail send --to recipient@example.com --subject "标题" --body-html "<p>内容</p>"

# 回复邮件
gog gmail send --to sender@example.com --subject "Re: 原标题" --body "回复内容" --reply-to-message-id <msgId>

# 标记邮件已读（按 thread）
gog gmail thread modify <threadId> --account zhangdongfang990@gmail.com --remove UNREAD --no-input

# 查看邮件详情
gog gmail thread get <threadId> --account zhangdongfang990@gmail.com
```

### Calendar 日历

```bash
# 列出日历事件
gog calendar list --account zhangdongfang990@gmail.com

# 查看指定时间范围事件
gog calendar events primary --from 2026-06-18 --to 2026-06-25

# 创建事件
gog calendar create primary --summary "会议" --from 2026-06-20T10:00:00 --to 2026-06-20T11:00:00
```

### Drive 文件

```bash
# 搜索文件
gog drive search "关键词" --max 10
```

### Contacts 联系人

```bash
# 列出联系人
gog contacts list --max 20
```

### Sheets 表格

```bash
# 读取数据
gog sheets get <sheetId> "Tab!A1:D10" --json

# 写入数据
gog sheets update <sheetId> "Tab!A1:B2" --values-json '[["A","B"],["1","2"]]'
```

### Docs 文档

```bash
# 导出文档
gog docs export <docId> --format txt --out /tmp/doc.txt

# 直接读取
gog docs cat <docId>
```

## 注意事项

1. **代理必须加**：不加代理会 timeout
2. **token 已存在 keychain**：Dongfang 已授权，账号是 `zhangdongfang990@gmail.com`
3. **Keychain 弹窗**：首次使用可能会弹窗要求输入 Mac 密码，点 Always Allow
4. **批量操作**：用 shell 循环处理，注意 API 速率限制
5. **JSON 模式**：加 `--json` 适合脚本处理
