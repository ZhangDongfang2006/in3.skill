# AGENT-INSTALL.md — 给 AI 看的安装指令

> 这份是给 **Claude Code / Codex** 等 agent 读的。用户把本 zip 丢给你后，请严格按这 8 步执行，每步报告结果。需要用户交互的只有 Step 1（zip 路径定位）、Step 2（确认装到哪里）、Step 7（收 tenant 凭证）三步，其他步骤自动跑。失败就停下问。

---

## Step 1 — 定位 zip 附件

用户通过附件方式上传了 `in3-cli-skill.zip`。先告诉用户它落在哪个路径（agent 一般写到临时目录，例如 `/tmp/...` 或 `/var/folders/...`）。

如果你拿不到附件实际路径，问用户「你把 zip 放在哪了」。**不要瞎猜路径。**

## Step 2 — 跟用户确认 SKILL_HOME（必须问，不要替用户决定）

skill 装哪里有 3 个不同范围，**列下面 3 个候选给用户，用非技术语言**讲清差别让 ta 选：

**A. 用户级（全局，最常用）** — 装一次以后所有项目里都能用
- 路径：`$CLAUDE_CONFIG_DIR/skills/`（如果你用的是第三方 claude 启动器 / profile 工具）；或 `~/.claude/skills/`（如果你用的是官方 Claude Code 直接装）
- ⚠️ **重要**：如果用户用了启动器（如 claude launcher / 多 profile 工具），`CLAUDE_CONFIG_DIR` env var 会指向当前 profile 的根目录，**user-scope 必须用这个 env，不能硬编码 `~/.claude/skills/`**。
- 走 A 的实操：**先跑 `echo "$CLAUDE_CONFIG_DIR"` 拿真实值**，再跟用户对绝对路径——
  - 非空 → 「检测到 `CLAUDE_CONFIG_DIR=X`，会装到 `X/skills/`，对吗？」
  - 空 → 「没检测到启动器 env var，默认 `~/.claude/skills/`，对吗？」

**B. 项目级（只这个项目可见）** — 装在当前项目下，换项目就要重装
- 路径：`<当前目录>/.claude/skills/`
- 适合：只在这个项目里用，不想污染全局；或者团队所有人共享同一份 skill（commit 进项目）

**C. plugin 模式（高级，普通用户跳过）** — 把它捆进某个 plugin 一起分发
- 路径：`$CLAUDE_PLUGIN_ROOT/skills/`（先 `echo "$CLAUDE_PLUGIN_ROOT"` 看 env 有没有设）

**Codex 用户**：流程同 A，但环境变量名是 `CODEX_CONFIG_DIR`，fallback 是 `~/.codex/skills/`。

走完顺序：
1. 把 A/B/C 用上面的大白话念给用户，问「想装到哪一种？」
2. 用户选 A → 先 `echo "$CLAUDE_CONFIG_DIR"`（Codex 则 `echo "$CODEX_CONFIG_DIR"`）拿真实值，再跟用户确认最终绝对路径
3. 用户选 B → 跟用户确认是不是想装到 `<pwd>/.claude/skills/`，并告知"出了这个项目就看不到"
4. 用户选 C → `echo "$CLAUDE_PLUGIN_ROOT"` 拿真实值，再确认
5. 用户最终确认绝对路径后再 `mkdir -p $SKILL_HOME`

## Step 3 — 解压

用户确认 SKILL_HOME 后：

```bash
unzip -o <zip 路径> -d $SKILL_HOME/
ls $SKILL_HOME/in3-cli/SKILL.md     # 验证
rm -rf $SKILL_HOME/__MACOSX 2>/dev/null   # 清 macOS 残留
```

## Step 4 — 读 SKILL.md

读 `$SKILL_HOME/in3-cli/SKILL.md` 头 80 行，一两句话告诉用户这 skill 干嘛的。

## Step 5 — 体检

```bash
python3 $SKILL_HOME/in3-cli/scripts/in3_cli.py doctor
```

按输出分支：

- 报 `legacy global install` → 跑 `migrate`（要交互 y，用 `echo y | python3 ... migrate` 喂）
- 干净但 workspace 不存在 → 跑 `python3 ... init`
- 全 OK → 进 Step 6

## Step 6 — 验证就位

```bash
python3 $SKILL_HOME/in3-cli/scripts/in3_cli.py status
```

确认 8 个模块 `installed: true`、`workspace_exists: true`，告诉用户 workspace 路径。

## Step 7 — 登录租户

跟用户一次性收 5 件事（先确认前 4 项不敏感的，再问密码）：

1. **env**：prod 还是 qa？
2. **tenant_domain**（如 `indx`、`aquaman`）
3. **短用户名**（如 `shenchenjian`，CLI 自动拼 `corp:<user>@<tenant>`）
4. **alias**（默认 = tenant_domain；多租户隔离用，按提示问即可）
5. **password**（明文）

⚠️ **密码会进入 agent 对话上下文** —— 这是为了让用户在 Codex/Claude app 里直接装完，不切窗口的 trade-off。如果用户对此敏感（远程开发/合规要求），让 ta 主动说「走本机终端 fallback」走方案 B。

### 方案 A — 非交互 args（默认；Codex app / 无 TTY 必走这条）

收齐 5 项后，**用 Python subprocess 调用**（不要用 bash 一行命令——密码里特殊字符会被 shell 炸掉）：

```python
import subprocess
r = subprocess.run([
    "python3", "<SKILL_HOME>/in3-cli/scripts/in3_cli.py", "login", "<alias>",
    "--env", "<prod|qa>",
    "--tenant", "<tenant_domain>",
    "--user", "<短用户名>",
    "--password-stdin",
], input="<密码明文>\n", capture_output=True, text=True, check=False)
print(r.stdout)
print(r.stderr)
```

为什么用 `--password-stdin` + stdin 喂而不是 `--password <X>`：
- args 形式让密码进 `ps aux`、可能进 shell history 和 audit log
- stdin pipe 不进任何一个

退出码 0 + 输出含 8 个 `PASS` → 成功。否则把 stdout/stderr 完整贴给用户看错误。

> 如果 `login` 因为「alias 已存在」需要覆盖，非交互模式会自动覆盖（不再 prompt y/N）；想显式控制可加 `--force`。

### 方案 B — 本机终端 fallback（密码 0 进 agent context）

用户主动选 B，或者方案 A 因为环境限制跑不动时（不太会发生），给 ta 一条命令模板：

```bash
python3 <SKILL_HOME>/in3-cli/scripts/in3_cli.py login <alias>
```

让 ta 在**自己电脑的本机终端**跑（不是 agent 内执行），按 4 个 prompt 手动输入。跑完回来跟 AI 说「我 login 完了」，AI 继续 Step 8。

> CLI 版 Claude Code 用户其实有 TTY，方案 A 跑得通；但如果 ta 偏好原 4-prompt 交互体验，方案 B 也行。

## Step 8 — 验收

login 完成后脚本会自动跑 test-all。8 个模块都 PASS 就完成。告诉用户：

> 装完了，可以用自然语言问 IN3 数据了，例如「查本月采购订单总额」。

---

## 加租户 / 卸载（可选交代）

- 加第二个租户：跟 AI 说「再加一个租户 X」即可，多租户原生隔离不会串数据。
- 卸载：`python3 $SKILL_HOME/in3-cli/scripts/in3_cli.py uninstall` 一行干净拆掉 workspace（skill 目录自己删）。

详细安装说明、踩坑、跨模块用法见 `INSTALL.md` 和 `SKILL.md`。
