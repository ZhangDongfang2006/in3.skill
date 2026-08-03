# TOOLS.md - Local Notes

## 📡 Agent 通讯录

用 `sessions_send` 联系同事：

| Agent | Bot | sessionKey | 擅长 |
|-------|-----|------------|------|
| Main 👑 | Bot 1 | `agent:main:main` | 主控协调、日常助手、新闻推送 |
| ProjectBot 📋 | Bot 5 | `agent:projectbot:main` | 项目管理、工作日志、Notion、Git |
| NotebookLM 📚 | Bot 7 | `agent:notebooklm:main` | Gemini Notebook、文档分析、总结 |
| GeoBot 🌍 | Bot 8 | `agent:geo:main` | 地理信息、数据分析 |
| **我** 🏭 | Bot 9 | `agent:in3bot:main` | IN3系统、物料、采购、BOM |

### 协作规则
- 收到其他 bot 的消息 → 像同事问问题一样直接回复
- 需要其他 bot 配合 → 直接用 `sessions_send` 联系对方，不必通过 Bot 1
- 不属于自己领域的任务 → 转给对应 bot
- `REPLY_SKIP` = 结束对话
- bot 之间消息禁止回复 NO_REPLY

### 转交指引
- 项目/Notion/Git → ProjectBot (Bot 5)
- 文档/论文/总结 → NotebookLM (Bot 7)
- 地理/地图 → GeoBot (Bot 8)
- 跨部门协调 → Main (Bot 1)

---

## What Goes Here

Things like:

- Camera names and locations
- SSH hosts and aliases
- Preferred voices for TTS
- Speaker/room names
- Device nicknames
- Anything environment-specific

## Examples

```markdown
### Cameras

- living-room → Main area, 180° wide angle
- front-door → Entrance, motion-triggered

### SSH

- home-server → 192.168.1.100, user: admin

### TTS

- Preferred voice: "Nova" (warm, slightly British)
- Default speaker: Kitchen HomePod
```

## Why Separate?

Skills are shared. Your setup is yours. Keeping them apart means you can update skills without losing your notes, and share skills without leaking your infrastructure.

---

Add whatever helps you do your job. This is your cheat sheet.

## Related

- [Agent workspace](/concepts/agent-workspace)
