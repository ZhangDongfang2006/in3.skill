# in3-cli skill 安装指南

> 内部分享文档 — 请勿外传
> 适用于 **Claude Code** 和 **Codex (oh-my-codex)** 两种 agent

把 `in3-cli.zip` 装到你的 agent 里，从此可以用自然语言查 IN3 业务数据（采购订单、销售订单、库存、生产计划、物料主数据），不用各模块 CLI 单独学。

**1.0 起的设计要点**：

- 所有 CLI 装到独立的 **workspace 工程**（默认 `~/in3-workspace`），不污染全局 npm prefix / 不动你的 `~/.npmrc` / 不写 `~/.ibrain-*`
- 多租户原生隔离：A 租户和 B 租户的凭证 / profile 物理分目录存，切换不会串数据
- 删 workspace = 干净卸载（一行命令）

---

## 0. 前置要求

| 要求 | 验证 |
|---|---|
| Claude Code 或 Codex 已装 | `claude --version` / `codex --version` |
| Node.js ≥ 20 | `node --version` |

**仅此而已**。不需要配 `~/.npmrc`，不需要 `npm login`——workspace 自带一份只指向 `@industics:registry=http://npm.industics.cn/` 的 `.npmrc`，且该 registry 匿名可读。

---

## 1. 解压 skill

**Claude Code 用户**：

```bash
unzip in3-cli.zip -d ~/.claude/skills/
```

**Codex 用户**（oh-my-codex 框架）：

```bash
unzip in3-cli.zip -d ~/.codex/skills/
```

两个 agent 都装？两个目录都解压一份即可。解完后应该有：

```
~/.{claude,codex}/skills/in3-cli/
├── SKILL.md
├── INSTALL.md
├── scripts/
│   ├── in3_cli.py
│   └── aes_encrypt.mjs
├── templates/                       # workspace 初始化用 (.npmrc / .nvmrc / package.json / package-lock.json)
└── references/
```

> macOS 解压可能多出 `__MACOSX/` 隐藏目录，可以删 `rm -rf ~/.{claude,codex}/skills/__MACOSX/`，不影响功能但占地方。

---

## 2. 初始化 workspace + 装 8 个模块 CLI

**Claude Code**：

> /in3-cli 帮我初始化 workspace

**Codex**：

> 用 in3-cli skill 初始化 workspace

或者直接命令行（agent 无关）：

```bash
python3 ~/.claude/skills/in3-cli/scripts/in3_cli.py init
# 或者 Codex 路径：
python3 ~/.codex/skills/in3-cli/scripts/in3_cli.py init
```

这一步会：

1. 在 `~/in3-workspace` 创建独立工程（含 `.npmrc` / `.nvmrc` / `package.json` / `package-lock.json` / `config/tenants/`）
2. 用 `npm ci` 按 lock **精确安装** 8 个模块 CLI 到 `~/in3-workspace/node_modules/`（不是全局）
3. 写一个 pointer 到 `~/.config/in3-cli/workspace.json` 让脚本日后能找到 workspace

会装这 8 个：

- `@industics/ibrain-mm-cli`（采购 MM：PO/PR/合同/BOM/供应商）
- `@industics/ibrain-wm-cli`（仓储 WM：库存/收发/盘点）
- `@industics/in-mom-md-cli`（物料主数据 MD：物料/类目/单位/币种/工厂）
- `@industics/ibrain-pp-cli`（生产计划 PP：工单/MRP/排产）
- `@industics/in-mom-qm-cli`（质量管理 QM：检验批/检验计划）
- `@industics/ibrain-sd-cli`（销售 SD：SO/合同/出货）
- `@industics/in-mom-cr-cli`（客户关系 CR：服务记录/工单）
- `@industics/ibrain-mom-fn-cli`（财务 FN：公司代码/科目）

预计 30s–2min（取决于网络）。

**自定义 workspace 路径**：`init --path /your/custom/path`
**强制重建**：`init --force`（会先 rm -rf 已有 workspace）

> 💡 如果你之前装过老版本（`npm i -g @industics/*`），init 会拒绝直接跑并提示先 `migrate`——见 §6。

---

## 3. 登录（首次配租户）

**Claude Code**：

> /in3-cli 帮我登录

**Codex**：

> 用 in3-cli skill 帮我登录 in3

或者命令行：

```bash
python3 ~/.<claude|codex>/skills/in3-cli/scripts/in3_cli.py login
```

会在**你的终端**（不是 agent 对话框）交互式问 4 个值——**全部由你的实际账号决定，本文档不预填任何值**：

| 提示 | 填什么 |
|---|---|
| 环境（prod/qa/custom） | （按你的实际环境选，多数选 prod） |
| tenant_domain | （向 @shenchenjian 索取） |
| 短用户名 | （向 @shenchenjian 索取） |
| 密码 | （向 @shenchenjian 索取） |

> ⚠️ **密码用 `getpass` 收，输入时不回显**。你看不到 `*` 也看不到字符，敲完按回车即可。密码不会进 agent 的对话上下文，也不会明文落盘——skill 用 AES-128-ECB（跟 in3.industics.com 网页同款算法）本地加密后写到 `~/in3-workspace/config/tenants/<tenant>/credentials.json` 和 8 个模块各自的 `~/in3-workspace/config/tenants/<tenant>/.ibrain-<mod>/config.json`，权限 `0600`。

login 会自动用你输入的 `tenant_domain` 作为 **alias**（多租户标识）。跑完会自动接着跑 `test-all` 联通性测试，8 个模块都 `PASS` 就成。

服务器：`https://in3.industics.com/`（API gateway `https://apiv3.industics.com/service`）

---

## 4. 多租户使用

每跑一次 `login` 都会创建一个新 tenant 子目录。你可以在多个租户间切换，**互不串数据**。

### 4.1 加第二个租户

```bash
python3 .../in3_cli.py login              # 第二次跑 login,交互输另一个 tenant_domain
# 或者明示 alias:
python3 .../in3_cli.py login <alias>      # 创建指定 alias 的租户配置
```

### 4.2 查看所有租户

```bash
python3 .../in3_cli.py tenants
```

输出形如：

```
  alias                env     tenant_domain        last_login           user
* <tenant-a>           prod    <tenant-a>           2026-05-19T10:11:00  <user>@<tenant-a>
  <tenant-b>           qa      <tenant-b>           2026-05-12T08:00:00  <user>@<tenant-b>
```

`*` 标当前活跃 tenant。

### 4.3 切换租户

```bash
python3 .../in3_cli.py use <alias>
```

或在 agent 里：

> /in3-cli 切到 \<alias\>

切完后，所有后续查询（包括自然语言问业务问题）都走目标租户的凭证、查目标租户的数据。**之前租户的查询不会污染目标租户的 profile，反之亦然**——隔离是文件系统级的，靠 8 个 `IBRAIN_<MOD>_CONFIG_DIR` 环境变量动态注入实现。

---

## 5. 开始查数据

直接用自然语言问你的 agent。例子：

- "4 月所有采购订单的总金额是多少？"
- "近 7 天新签的销售订单有几张？分别是什么客户？"
- "物料 R-CJ00078 当前库存还有多少？"
- "供应商 V0270 过去半年供了哪些物料？"
- "某张 SO 能不能按期交货？缺口多少？"

skill 会自动判断该走哪个模块的 CLI、拉数据、必要时跨模块组装（比如"履约就绪度"需要 sd → md → wm → mm → pp 5 模块联查）。

**Claude Code 用 slash command**：

> /in3-cli 4 月采购订单总金额

**Codex 通常直接说就行**；如果没自动用，明示一下：

> use the in3-cli skill: 4 月采购订单总金额

---

## 6. 日常运维

### 看当前状态

```bash
python3 ~/.<claude|codex>/skills/in3-cli/scripts/in3_cli.py status
```

输出告诉你：workspace 路径 / 当前 tenant / 所有 tenant 清单 / 8 模块的安装版本 + profile 状态 / vendor 是否存在 / 是否有 legacy 全局残留。

### 体检（建议每月跑一次）

```bash
python3 .../in3_cli.py doctor
```

逐项检查：workspace 完整性 / lock vs node_modules drift / legacy 全局残留 / Node 版本 / registry 连通性 / 8 模块 `--version` / 每个 tenant 的 cred + profile 完整性。

### 找 workspace 在哪

```bash
python3 .../in3_cli.py where
# 输出: /Users/x/in3-workspace
# 可配合 shell: cd $(python3 .../in3_cli.py where)
```

### 从旧版（全局 npm 安装）迁移

如果你之前用过 0.x 版本（`npm i -g @industics/*` + `~/.ibrain-*/config.json`），跑：

```bash
python3 .../in3_cli.py migrate
```

会自动：
1. 创建 workspace（如未创建）
2. 从旧主 cred 读 `tenant_domain` 作为 alias
3. 拷贝旧 `~/.ibrain-<mod>/config.json` 进 workspace 内对应 tenant 目录
4. `npm rm -g` 卸掉所有全局 `@industics/*`
5. 把旧 `~/.ibrain-*` 改名 `.bak`（不删，留后悔药）

跑前会显示完整 plan 并要求 y/N 确认。

### 升级 CLI

```bash
python3 .../in3_cli.py upgrade-all
```

⚠️ 这会脱离 `package-lock.json` baseline，让你装上 npm registry 当前的 latest。如想恢复到 lock 的精确版本，跑 `install-all`（走 `npm ci` 严格还原）。

### 删某个 tenant（不删整个 workspace）

```bash
python3 .../in3_cli.py logout <alias>
```

会删该 tenant 的 cred + 8 个模块 profile。**必须传 alias**——避免误删所有租户。

### 彻底卸载

```bash
python3 .../in3_cli.py uninstall
```

二次确认后：
- 删 `~/in3-workspace/`（含全部 8 个 CLI + 所有 tenant 凭证）
- 删 `~/.config/in3-cli/workspace.json` pointer
- **不删** `~/.ibrain-*.bak`（migrate 留下的后悔药）

完事。再次使用只需重跑 `init` + `login`。

---

## 7. 常见问题排查

| 症状 | 原因 / 修法 |
|---|---|
| `no workspace found; run init first` | 你还没跑 `init`，跑一下 |
| `detected legacy global install` | 你有 0.x 版本残留（`npm i -g @industics/*`），跑 `migrate` 一键迁移 |
| `tenant 'X' not found. Available: [...]` | alias 写错了，看 `tenants` 命令的输出 |
| `npm install` 报 `ENOTFOUND npm.industics.cn` | 你不在公司内网；连 VPN 后重试 |
| 升级后 `doctor` 报 lock drift | 你跑了 `upgrade`，已脱离 lock baseline。想恢复跑 `install-all` |
| 查询结果像是另一个租户的 | 可能 `current-tenant` 没切对；跑 `tenants` 看 `*`，再 `use <alias>` |
| login 后 test-all 有 FAIL | 跑 `doctor` 看是哪个模块、什么错；通常是密码错或 tenant_domain 错——重跑 `login` |
| **Codex 不主动触发 skill** | 检查 `~/.codex/skills/in3-cli/SKILL.md` frontmatter；或每次明示"用 in3-cli skill" |
| 想看 skill 完整说明 | 读 `~/.<claude\|codex>/skills/in3-cli/SKILL.md`，或在 agent 里 `/in3-cli help` |

---

## 8. 安全注意

- 加密密文虽然不是明文，但**仍是凭据材料**。`~/in3-workspace/config/tenants/<alias>/credentials.json` 和各模块 `.ibrain-<mod>/config.json` 默认权限 `0600`，**不要拷贝到不可信环境、不要 commit 到 git**
- 不要把 `~/in3-workspace/config/` 整个目录贴到聊天群里求助——里面有所有租户的加密密文
- 共享账号信息**不写在本文档**，向 @shenchenjian 私聊索取
- 改密后重跑 `login <alias>` 即可，旧加密密文会被覆盖；其他租户不受影响
- 多机使用：可以把 `~/in3-workspace/config/` 通过 dotfiles 工具同步，但不要把 `node_modules/` 同步（用 `init` 各自重建）

---

## 9. 适用 / 不适用

- ✅ 适用：IN3 产品族（`in3.industics.com`）的 MM/WM/MD/PP/QM/SD/CR/FN 8 类业务数据查询
- ❌ 不适用：huluwa 体系 ina-* 模块（用 `ina-cli` skill）、DOM/Confluence/MO8 等其他系统（各有专属 skill）

---

## 10. （维护者）刷 baseline + 打离线 vendor

> ⚠️ **这一节只给 skill 维护者看**。同事永远不需要跑这些命令。

### 10.1 刷 package-lock.json baseline

当你想把同事拉到新版 CLI 时：

1. 改 `templates/package.json` 的精确版本（如 `"@industics/ibrain-mm-cli": "0.5.0"`）
2. 删 `templates/package-lock.json`
3. 在临时 dir 跑 `HOME=/tmp/x npm install` 重新生成 lock
4. cp 新 lock 回 `templates/`
5. 重新打 skill zip 分发

### 10.2 打离线 vendor 包（可选）

适用场景：客户现场断网 demo、registry 维护期同事 onboarding 冗余、CI 跑预编译镜像。

```bash
python3 ~/.claude/skills/in3-cli/scripts/in3_cli.py pack-vendor
```

会在 skill 根目录创建 `vendor/` + 8 个 tarball + `MANIFEST.json`（含 sha256）。`init` 检测到 `vendor/` 存在时会优先用本地 tgz，跳过 `npm ci`。sha256 失配会立即中止安装。

平时不用 vendor 就不创建它，`vendor/` 不存在时 `init` 自动走 `npm ci`。

---

## 反馈

skill 行为有 bug 或想加新模块：联系 @shenchenjian，或者直接改 `~/.<claude|codex>/skills/in3-cli/SKILL.md` + `scripts/in3_cli.py`，然后告诉我做 upstream merge。
