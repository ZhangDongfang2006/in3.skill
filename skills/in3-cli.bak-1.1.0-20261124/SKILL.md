---
name: in3-cli
description: IN3（in3.industics.com）产品族多模块 CLI 调度器 + workspace-scoped 多租户 onboarding。当用户查询采购、合同、BOM、供应商、库存、销售、生产、质量、服务、财务、物料主数据，需跨模块联合分析、切换租户，或尚未初始化 workspace、安装 8 个 CLI、登录 tenant 时触发。所有 CLI 位于独立 workspace（默认 ~/in3-workspace），不污染全局；租户配置隔离，调度器原样输出模块返回的价格和金额字段。不适用于 huluwa 的 ina-* 模块及非 IN3 产品。
compatibility: [claude-code, codex]
---

# in3-cli
IN3 产品族（在线 SPA 入口 `in3.industics.com`，API gateway `apiv3.industics.com/service`）多模块 CLI 的统一调度层。

## What this skill does
三件事：

1. **Workspace init**：一个命令在 `~/in3-workspace` 创建独立工程，本地装 8 个 module CLI（`@industics/ibrain-mm-cli`/`ibrain-wm-cli`/`ibrain-pp-cli`/`ibrain-sd-cli`/`ibrain-mom-fn-cli`/`in-mom-md-cli`/`in-mom-qm-cli`/`in-mom-cr-cli`），不污染全局 npm prefix。
2. **多租户 onboarding + 切换**：用户报一次 env/tenant/账号/明文密码（getpass），skill 用 SPA 同款 AES-128-ECB 加密，把同一份加密 profile 写到 workspace 内 `tenants/<alias>/.<binary>/config.json`。再跑 `login <alias-b>` 加第二个租户，互不串数据。`use <alias>` 切当前活跃 tenant。
3. **自然语言查询分发**：用户问"5 月采购金额"这类业务问题，你（Claude）查 `references/modules.md` 的实体地图，**通过 `exec <mod>` 子命令** 调对应模块 CLI 拉数据，必要时 jq 聚合或客户端 join。
4. **跨模块组合分析（SDK code-mode）**：复杂的跨 mm/wm/md/sd 组合分析，**优先写 Python 用 `run` 跑 `in3_client` SDK**（直连 HTTP、坑层下沉、中间数据不进上下文）——见下方专节。登录除密码外还支持 SSO/MFA 的 `login --paste-token` / `login --browser`。

skill 本身（dispatcher）不发请求；`exec` 路径的 HTTP 由模块 CLI 发，`run`/SDK 路径由 `in3_client` 直连后端发。skill 负责 workspace 管理 + 多租户隔离 + 实体到模块的映射知识 + env var 注入 + SDK 分发。

## Core helper
```
python3 ${SKILL_DIR}/scripts/in3_cli.py <subcmd>
```

| 命令 | 用途 |
|---|---|
| `init [--path P] [--force] [--allow-legacy]` | 创建 workspace + npm ci 装 8 个 CLI |
| `doctor` | 体检 workspace + legacy 残留 + Node + registry + 8 binary + tenant 完整性 |
| `migrate` | legacy 全局安装 → workspace 一键迁移 |
| `uninstall` | 二次确认后 `rm -rf workspace` + 删 pointer |
| `where` | print workspace 路径 |
| `status [--refresh-versions]` | JSON 输出 workspace/tenant/8 模块状态(2h 版本缓存) |
| `login [alias]` | 交互式收 env/tenant/账号/密码;不传 alias 时用 tenant_domain;落地后跑 test-all |
| `login --paste-token [alias]` | **SSO/MFA 兜底(零安装)**:粘贴浏览器抓的 Bearer,解 JWT 落 token 模式凭证(`--token-stdin` 非交互) |
| `login --browser [--url U] [alias]` | **自动捕获(需 Python Playwright)**:起浏览器到登录页,登录后从网络流抓 token(含 refresh) |
| `run <script.py> [--timeout N] [-- args]` | **跑 `import in3_client` 的 Python(SDK 执行壳)** — 注入凭证/SDK 到子进程,坑层下沉,中间数据不进上下文 |
| `run --code "<py>"` | 同上,内联代码(短查询用) |
| `audit [--limit N]` | 看最近 run 的审计摘要(退出码/超时/截断/耗时/脚本头) |
| `sync [alias]` | 用主凭证给该 tenant 重新 fanout 8 模块 profile (不重输密码) |
| `logout <alias>` | 删指定 tenant 的 cred + 8 profile (**强制 alias 参数**,避免误删全部) |
| `use <alias>` | 切当前 active tenant (改 current-tenant.json 一行) |
| `tenants` | 列所有 tenant + 标当前 |
| `exec <mod> <args...>` | **调 module CLI 命令的统一入口** — 自动注入 workspace binary + 当前 tenant 的 8 个 env var |
| `install <mod>` | workspace 内装/重装单个模块 |
| `install-all` | 按 lock 重装 workspace 全套 (`npm ci`) |
| `upgrade <mod>` | 升单个模块到 latest(会脱离 lock baseline) |
| `upgrade-all` | 升所有已装模块到 latest |
| `pack-vendor` | (维护者) npm pack 所有模块到 vendor/ |
| `test <mod>` | 跑该模块的 smoke 只读命令 |
| `test-all` | 跑所有模块的 smoke,汇总 PASS/FAIL |
| `help` | 用户向 quickstart |

## 🚨 调 module CLI 的统一约定：用 `exec` 子命令
**所有对 module CLI 的调用** —— 不管是 `ibrain-mm-cli purchase-order list ...` / `ibrain-wm-cli stock bin ...` / 任何模块的 `__schema` / `--version` —— **必须通过 `exec` 走**：

```bash
# ❌ 错: 直接调裸 binary
ibrain-mm-cli purchase-order list --filter status=A   # PATH 里没有,会 command not found

# ✅ 对: 通过 exec 调
python3 ${SKILL_DIR}/scripts/in3_cli.py exec mm purchase-order list --filter status=A
```

为什么必须走 `exec`：
- workspace 的 `node_modules/.bin/<binary>` **不在 shell PATH**，裸调会 not found
- 8 个 `IBRAIN_<MOD>_CONFIG_DIR` env var **必须每次都全设**，否则 CLI 读不到当前 tenant 的 profile（甚至可能读到错 tenant）
- `exec` 一行就把这两件事都搞定

### v1.3.0：价格字段原样输出
调度器不再检查 `price_viewer`（价格查看角色），也不再删除字段名包含 `price`、`amount`、`cost`、`tax` 等内容的字段。`fn` 财务模块、报价、价目和费用等命令与其他命令一样，module CLI 返回什么，调度器就输出什么。

这只移除了本地 Python 调度器的过滤。IN3 服务端如果拒绝某个接口，CLI 仍会原样显示服务端错误，不会伪造数据或成功状态。详见 `docs/price-fields-pass-through.md`。

下面 §"Step 4" 的所有 CLI 示例为了简洁仍写裸 binary 形式（如 `ibrain-mm-cli purchase-order list ...`），但你（agent）实际跑的时候必须**全部替换成 `python3 ${SKILL_DIR}/scripts/in3_cli.py exec <mod> ...`**。Pipe 和 jq 链没问题：

```bash
# 文档里写
ibrain-mm-cli __schema | jq '.commands."purchase-order".list.filter_keys'
# 你实际跑
python3 ${SKILL_DIR}/scripts/in3_cli.py exec mm __schema | jq '.commands."purchase-order".list.filter_keys'
```

## 🚀 跨模块组合分析首选：`in3_client` SDK + `run` 执行壳
**遇到"跨 mm/wm/md/sd 的组合分析"（如本月采购金额 Top10 × 库存 × 独家供应、缺口=需求−在途、孤儿物料对账）时——优先写一段 Python 用 `run` 跑，而不是多步 `exec` + jq fan-out。**

为什么（POC 实测，见 `docs/in3-cli-cemcp/BEFORE-AFTER.md`）：同一主任务，裸 `exec` 路径要把 5 月 534 单 PO + 3900 行明细的 JSON 拉进上下文（**540 万 token / 15.8 MB，塞不进任何上下文窗口**）、且 wm 库存维度因 CLI multi-filter 缺陷一律 400 做不出；SDK 路径**坑层全下沉、中间数据留子进程**，只有最终 10 行表（**565 token**）进上下文，1 次脚本搞定（轮次 11→1）。

```bash
# 写一段 import in3_client 的脚本，只 print 最终结果
python3 ${SKILL_DIR}/scripts/in3_cli.py run analysis.py
# 短查询用内联：
python3 ${SKILL_DIR}/scripts/in3_cli.py run --code "import in3_client; print(len(in3_client.IN3().mm.supplier.list().items))"
```

> **FN 0.1.1 路由例外**：`fapiao` / `payment-receipt` 必须走上面的 `run` + SDK，不能走
> `exec fn` 做业务查询。npm CLI 0.1.1 使用了过期 header，且声明的 `--all/--page/--size` 未真正接入；
> SDK 已按 production 的 `fncc` header、真实端点和分页协议修复。详见 `references/modules.md`。

SDK 形态（`engineering/skills/in3-cli/sdk/in3_client/`，随 skill 分发、零硬依赖；详见 `sdk/poc/` 示例 hello.py/north_star.py）：

```python
import in3_client
in3 = in3_client.IN3()                          # 用当前 active 租户（token 或 password 模式都透明）
# SDK 已覆盖全 8 模块 78 个 entity，统一返回 Page{items, page, total, has_next}。
# ① mm/wm/sd/md 核心 entity —— live-parity 逐位验证最充分，首选：
in3.md.currency.list()        in3.md.material.list(filter=...) / .get(id)
in3.mm.supplier.list() / .get(id)
in3.mm.purchase_order.list(filter={"material_ids":[...], "from_ordered_at":"2026-05-01"}, include_items=True, all=True)
in3.wm.available_stock.by_materials(ids)        # POST 分页 + fan-out（CLI 做不到）
in3.wm.stock.material(material_ids=[...]) / .bin(...) / .storage_location(...) / .storage_bin(...)
in3.sd.sales_order_item.list(filter=...)
# ② pp/qm/cr/fn 也已 SDK 化（直接 in3.<mod>.<entity> 调，无需 exec）：
in3.pp.sales_order.get(so_id)   in3.pp.production_plan.list(...)              # pp 8 entity（sales_order.get 已 live 验证）
in3.fn.company_code.list()      in3.fn.payment_receipt_order.list(filter=...)  # fn 5 entity（金额字段旁挂 156↔CNY companion）
in3.qm.inspection_lot.list(...)                                              # qm 5 entity
in3.cr.service_order.list(...)                                               # cr 6 entity（需租户开通慧客服，否则 401）
# 价值面：
in3.df(items)                 # → pandas DataFrame，groupby/nlargest
in3.join(a, b, c, on="material_id")   # 内存 left/outer，孤儿保留并标 _orphan（不静默丢）
in3.sole_source(material_ids)         # 独家供应三态（1供=风险/≥2/0=孤儿）
```

**无人值守 / 定时跑（无浏览器、无人工登录）**：除 `IN3()`（读 workspace 凭证）外，SDK 支持 AGENT 服务客户端 + `client_credentials` 机器令牌——
`in3_client.IN3.from_client_credentials(api_host="https://apiv3.industics.com/service", tenant_domain="<租户域名>", client_id=..., client_secret=...)`。
机器令牌无人值守、不需浏览器/无 refresh 续期脆弱点，适合定时巡检。实际能读哪些数据由 IN3 服务端决定。坑点：T-CODE 用租户域名（如 `indx`）不是数字 id；client_id/secret 走环境变量、**绝不入库**。

坑层已下沉（agent 不必再手踩）：分页归一（`total<len` 置 None，¥111K 防御）/ PO chunk≤80 fail-loud / open_qty 兜底 / 多值 filter `_matched_filter_values` / wm POST-body 分页 / 4 视图 fan-out skip-on-error / 币种 156↔CNY 归一 / 孤儿保留。**SDK 已覆盖全 8 模块 78 个 entity**（v1.x 全覆盖）。成熟度分层（按可靠性）：mm/wm/sd/md 核心 entity 经 live-parity 逐位验证（最可靠）；fn 的 company_code / posting_period / fapiao / payment_receipt 已 live 验证（其中双轨接口须走 SDK，见 `references/modules.md` 已知坑 0）；pp/qm 多数 entity 单测绿、部分 verb 的 live 端点尚未逐位钉死（结果建议抽验）；cr 6 entity 需租户开通慧客服权限，多数租户 401。

`run` 自带运维护栏：超时（默认 300s→退出码 124）、输出截断（64KB）、审计日志（`<ws>/audit/`，`audit` 子命令查）。中间业务数据留在子进程、不进你的上下文。

> 何时仍用 `exec`：单模块单点查询（一行 CLI 更省事）、要对 SDK 做 parity 比对、或调用 SDK 中 live 未武装的冷门 entity/verb 时想用 CLI 二次印证。

### 内置能力：主数据质量巡检（mdm-sentinel）
`sdk/poc/mdm-sentinel/` 是基于本 SDK 的**多规则主数据巡检框架**（确定性脚本算 → AI 判读 shortlist）。当用户问"主数据有没有问题 / 价格记录异常 / 帮我巡检物料主数据 / 找出可疑 SKU"时可用：

- **rule#1 单价异常**（PCS 包装单位错配 / 现价跨供应商离散）：从物料描述抠包装规格 + 每供应商当前有效价（含有效期/最近新建过滤）+ 采购数量整除佐证 → 给 Sourcing 的核验单，**每条点名要改哪个供应商哪条记录 + 建议纠正 PCS 单价**。
- **R2** 价格记录 vs 实际 PO 成交价偏离 / **R5** 完整性（无现价 / 有采购无价格记录）/ **R7** 独家供应（按采购金额收口）。

```bash
python3 ${SKILL_DIR}/sdk/poc/mdm-sentinel/mdm_inspect.py out.html   # 多规则 TAB 报告
python3 ${SKILL_DIR}/sdk/poc/mdm-sentinel/mdm_sentinel.py r.html    # 仅 rule#1 + shortlist JSON
```

定时无人值守跑法（客户端定时任务 + `execute_code`）见其 `PROMPT.md`；设计/信号校准/决策见 `CONTEXT.md`、`ADR-0001`。默认走当前 workspace 登录用户；定时场景配 `IN3_AGENT_CLIENT_ID/SECRET` 环境变量走机器令牌。

### v2：MCP server（给纯 MCP host 用，免 skill）
同一套 SDK 执行核还能起成 **MCP server**（stdio JSON-RPC，单一 `execute_code` 工具），
让 Claude Desktop 等**任意 MCP host** 不经本 skill 直接跑 `import in3_client` 的跨模块只读分析：

```bash
python3 ${SKILL_DIR}/scripts/in3_cli.py mcp      # 起 stdio MCP server（前台）
```

- `execute_code` 入参 `code` / `timeout` / **`tenant`**（多租户 session-scoped 路由：每请求显式指定目标租户，省略回退当前 active tenant，未知租户返错误结果不崩）。
- 正确性/省 token 收益与 `run` 同源（同一 `in3_run.execute` 执行核），增量只是**可移植性**。纯读、本地凭证。
- MCP host 注册（Claude Desktop 配置）+ command 该用哪个带 SDK 依赖的 python + 自驱验证，全在 **`docs/in3-cli-cemcp/MCP-SERVER.md`**。

## When the user triggers this skill
按这个顺序判断状态，分别走不同分支。

### Step 0 — workspace 是否就位？
```bash
python3 ${SKILL_DIR}/scripts/in3_cli.py status
```

如果 `workspace_exists: false`：

→ 跑 `python3 .../in3_cli.py doctor` 看是否检测到 legacy 全局安装（用户之前用 0.x 版本）。
- doctor 报「detected legacy global install」→ 引导用户跑 `migrate`，一键迁移旧 config + 卸全局 + 建 workspace
- doctor 干净 → 跑 `init` 直接建 workspace

init 会问的就一个：是否走默认路径 `~/in3-workspace`。除非用户有特别要求，默认就行。

### Step 1 — status 输出怎么读
```json
{
  "workspace_path": "/Users/x/in3-workspace",
  "workspace_exists": true,
  "current_tenant": "<alias>",
  "tenants": ["<alias>"],
  "current_tenant_meta": { "api_host": "...", "env_label": "prod", "tenant_domain": "...", "username": "...", "last_login_at": "..." },
  "vendor_present": false,
  "modules": {
    "mm": {
      "binary": "ibrain-mm-cli",
      "installed": true,
      "installed_version": "0.4.7",
      "latest_version": "0.4.7",
      "update_available": false,
      "profile_for_current_tenant": "present",
      "current_context": "<alias>",
      "vendor_tarball_version": null
    }
  },
  "legacy_global_install": { ... }   // 如果检测到
}
```

分支：

- **`workspace_exists: false`** → 见 Step 0
- **`current_tenant: null`** 但 workspace 已 init → 引导用户跑 `login`
- **某模块 `profile_for_current_tenant: "absent"`** → 跑 `sync` (复用主凭证下发 profile，**不要重新 login**)
- **某模块 `installed: false`** 且用户问题需要它 → `install <mod>` 单装
- **某模块 `profile_for_current_tenant: "present_but_not_active"`** → CLI 里 current_context 被切走了，跑 `sync` 切回。dispatch 前必须修
- **`update_available: true`** → 提示用户「`mm-cli <旧> → <新>` 有更新,要升一下吗？」让用户决定。**不要自动升** —— 升级中途可能改变行为
- **`legacy_global_install` 字段存在** → 引导跑 `migrate`，否则 PATH 优先解析全局 binary 跟 workspace 冲突
- **`workspace + current_tenant + 8 模块 profile=present`** → 直接走 Step 4 dispatch

`latest_version` 走 2h 本地缓存（`~/.config/in3-cli/version_cache.json`）。强制刷：`status --refresh-versions`。

### Step 2 — 登录（首次或加新租户）
三种方式。**默认首选 ① 浏览器登录**——它把"弹页面 → 输账号密码 → 自动抓 token"做成一条命令，密码在浏览器里输、不经终端、不进你的上下文，**所以你（agent）可以直接用 Bash 跑，不需要让用户加 `!` 前缀**。

#### ① 浏览器自动捕获（默认首选）
```bash
python3 ${SKILL_DIR}/scripts/in3_cli.py login --browser <alias>
# 非默认登录页可带：--url https://in3.industics.com
```

- **你直接用 Bash 跑（不要加 `!`）**：脚本起有头 Chromium 弹到登录页，用户登录后脚本监听 `/uaas/oauth/token` 响应自动抓 access_token + refresh，落 token 模式凭证。
- 跑之前告诉用户：
  > 浏览器马上弹出 in3 登录页，请用**账号密码**登录（**别用飞书扫码——扫码的 token 端点不同，抓不到**）。登完我自动拿 token 继续。
- ⚠ **硬约束（已实测）**：prod 登录页 = `sso.industics.com`，同时支持飞书扫码 + 账号密码；**本模式只对账号密码登录有效**，飞书扫码会 timeout（脚本会提示改 ③）。
- ⚠ **token 模式不写 8 个模块 CLI 的 profile**，只够 SDK `run` 用（复杂分析/报表本来就推荐走 SDK，见下方专节）。**若任务要 `exec` 单模块 CLI → token 模式会失败，改走 ②**。

#### ② 账号密码直输（getpass，写齐 8 模块 profile）
```bash
python3 ${SKILL_DIR}/scripts/in3_cli.py login <alias>
```

**这条必须让用户用 `!` 前缀和终端交互**（getpass 走 TTY，agent 的 Bash 非 TTY 会 hang）。先告诉用户：
> 即将跑 login。我会在终端问环境（prod/qa/custom）、tenant_domain、短用户名、密码。密码 getpass 不回显，只在本机加密落盘，明文不存。

跑完 script 自动接 `test-all`，各模块应 PASS。用这条的场景：**要 `exec` 跑模块 CLI**，或浏览器/Playwright 不可用。

#### ③ 粘贴 token（SSO/MFA / 飞书扫码兜底，零安装）
```bash
python3 ${SKILL_DIR}/scripts/in3_cli.py login --paste-token <alias>
```

用户自己浏览器登录（含飞书扫码/MFA）后，从 devtools 抓 Bearer 粘贴。适合 ① 抓不到（扫码）又没装 Playwright 的场景。

**怎么选**：默认 ①（账号密码浏览器登录，体验最顺，配 SDK `run`）；任务要 `exec` 模块 CLI 走 ②；飞书扫码/MFA 用户走 ③。

### Step 2.5 — 切换租户
如果用户在跟某个 tenant 工作时说"看下另一个租户的..."、"对比 X 和 Y 两个租户的..."这种话，你需要切 active tenant：

```bash
python3 ${SKILL_DIR}/scripts/in3_cli.py tenants     # 看有哪些
python3 ${SKILL_DIR}/scripts/in3_cli.py use <alias> # 切
```

如果用户要的 tenant 不在 `tenants` 输出里 → 引导先 `login <alias>` 加。

切完后所有后续 `exec` 调用都自动走新 tenant 的凭证。**不需要重输密码** —— login 一次终身用，除非密码改了。

### Step 3 — 缺模块就装（少见，init 已装齐 8 个）
```bash
python3 ${SKILL_DIR}/scripts/in3_cli.py install mm        # 装单个
python3 ${SKILL_DIR}/scripts/in3_cli.py install-all       # 重新 npm ci 全套
```

正常 `init` 之后 8 个都齐了。`install` 主要用于：升级失败后重装、个别模块从 latest 回退到 lock baseline。

### Step 4 — 自然语言查询分发
查 `references/modules.md` 的实体表，确定走哪个模块。例如：

| 用户问 | 选 | 关键命令（实际跑时加 `exec` 前缀） |
|---|---|---|
| 4 月下达的采购金额 | mm | `purchase-order list --filter from_ordered_at=2026-04-01 --filter to_ordered_at=2026-04-30 --all`，jq sum `local_total_tax_price` |
| 某供应商签了多少合同 | mm | `contract list --filter supplier_id=<id> --all` |
| 物料 BOM 结构 | mm | `bom get <material_id>` |
| 某仓库当前余量 | wm | `stock bin --material-id <id> --all`，累加 `total_quantity` |
| 销售订单/合同/出货 | sd | `sales-order list` / `contract list` / `delivery-receipt list` |
| 工单 / 生产计划 | pp | `production-plan list` |
| 物料字典 / 类目 / 币种 / 工厂 | md | `material list` / `material-category list` / `currency list` / `plant list` |
| 检验批 / 检验计划 | qm | `inspection-lot list` |
| 服务记录 / 工单 | cr | `work-log-category list` |
| 公司代码 / 财务科目 | fn | `company-code list` |

> 📌 **再强调一遍**：上面命令实际跑时全部要替换成 `python3 ${SKILL_DIR}/scripts/in3_cli.py exec <mod> <command>`。

#### 优先用服务端 filter，别盲目 `--all` 拉全表
mm-cli 0.2.0 起每个 entity 的 `__schema` 暴露 `filter_keys`——后端真实接受的过滤字段、类型、是否支持多值都在那里。先看 filter_keys 决定打法：

```bash
python3 ${SKILL_DIR}/scripts/in3_cli.py exec mm __schema | jq '.commands."purchase-order".list.filter_keys'
```

**判断流程**

1. 用户的过滤维度（日期/状态/供应商/物料 等）有没有对应的 `filter_keys` 条目？
   - 有 → `--filter k=v` 服务端过滤，传完整 `--all --max <N>` 把命中条目拿全
   - 没有 → 才走 `--all` 拉全表 + `jq select(...)` 客户端过滤
2. 日期类 filter 在 mm-cli 里命名约定是 `from_<field>` / `to_<field>`（date 类型，例 `from_ordered_at`、`from_created_date`）
3. `--filter` 可重复传，多个 key 是 AND；同 key 多值（`--filter status=A --filter status=F`）后端按 OR 处理（前提是 `multi: true`）
4. 服务端 filter 不一定比客户端快——backend 偶尔 filter path 没走索引。命中率 < 10% 用 filter，> 50% 跟 `--all` 差不多
5. **`total` 字段是后端 Spring Page.totalElements,多数 list 端点不可靠**（mm 0.3.1 已在 `__schema.pagination_notes` + 每个 list verb 的 `response_notes` 钉死）；判结果数永远 `(items|length)` 自数
6. **mm 同 key 多值** (`--filter material_ids=A --filter material_ids=B`) 在 ibrain-mm-cli ≥ 0.3.1 正确工作（0.3.0 CLI 端 last-write-wins,已 fix）；require `ibrain-mm-cli --version` ≥ 0.3.1。**0.4.0 起加 `--include-items` 时每个命中 header 还会带 `_matched_filter_values.material_ids: string[]`**——做"per-material 反查"免 fan-out
7. 服务端 filter 失效判断方法：用最小集合（1 个）和当前集合分别跑，命中 PO 数量差异极小或完全不变，说明 filter 没生效

**复杂参数兜底**：不确定 flag 时直接看 `__schema`：

```bash
python3 ${SKILL_DIR}/scripts/in3_cli.py exec mm __schema | jq '.commands."<entity>".list'
```

#### 大输出处理
mm-cli ≥ 0.3.1 / sd-cli ≥ 0.2.5 已修 pipe-flush bug，可直接 `| jq`。wm/md/pp/qm/cr/fn 这批升级后**没专门 verify 同款 fix 是否同步**——保险起见这些的大输出走文件中转：

```bash
# wm/md/pp/qm/cr/fn 大输出, 走文件
python3 ${SKILL_DIR}/scripts/in3_cli.py exec wm stock bin --all --plant <id> > /tmp/stock.json
jq '...' /tmp/stock.json
```

#### shell quoting 防呆（zsh 重要）
`--filter material_ids=X --filter material_ids=Y` 多值时，**每个值必须独立写一行 `--filter material_ids=<literal_id>`，并把变量 quote**：

```bash
# ✅ 对：每个 mid 独立 --filter，变量 quote
ICLI="python3 ${SKILL_DIR}/scripts/in3_cli.py exec mm"
for mid in "${MIDS[@]}"; do
  args+=(--filter "material_ids=$mid")
done
$ICLI purchase-order list "${args[@]}" --max 100

# ❌ 错：拼成一个字符串塞给一个 --filter
$ICLI purchase-order list --filter "material_ids=$ARGS"   # zsh 不分词
```

更保险的写法是 Python `subprocess.run(["python3", ".../in3_cli.py", "exec", "mm", ...])` —— execvp，shell 完全不参与分词。

**怎么判断 multi filter 是否真生效**：用 1 个值跑一次（记 `items.length=N1`），用 N 个值再跑一次（记 `items.length=NN`），如果 `NN < total_without_filter` 且 `NN >= N1` filter 生效；如果 `NN == total_without_filter` 那就是 filter 被静默忽略了（很可能是 shell 没 quote 把多值打散）。

### Step 5 — 跨模块组装
mm/wm/md/sd/pp 都活着后，典型问法："过去 30 天 PO 中某物料类目的总金额 + 这些物料当前库存"。打法：

1. **md** `material-category list` → 找类目 code；`material list --filter material_category=<code> --all` → 物料 id 集合 **S**
2. **mm** `purchase-order list --filter from_ordered_at=... --filter to_ordered_at=... --filter material_ids=<id> ...(多次) --all` → 命中 PO；**注意 header `local_total_tax_price` 是整单合计，不是该类目的贡献**，必须 `purchase-order get <po_id>` 拿行项,按 `items[].material.material_category` 客户端筛后 sum `local_total_tax_price`
3. **wm** 没有 `material_category` filter——但 `stock` 自 ibrain-wm-cli ≥ 0.1.9 起 **4 个视图全部** 接 `--material-ids` 多值（`material` / `bin` / `storage-location` / `storage-bin`），可一次传完物料集合 S 拿全部库存

CLI 本身不做 join，是 skill 层（你）的活。

#### "按物料反查" 端点速查表（跨模块组装的高频起点）
| 反查目标 | 走哪个端点 | 关键 filter | 备注 |
|---|---|---|---|
| 含此物料的**销售订单**（sd） | `sales-order-item list --material <id>` | typed flag | 全租户行项视图。**别 fan-out `sales-order get`**——几千张 SO 拉到天荒地老 |
| 含此物料的**采购订单**（mm） | `purchase-order list --filter material_ids=<id1> ... --include-items` | `material_ids`（multi, mm-cli ≥ 0.3.1） | 一次 call 可传任意多个 id，后端 OR 命中。加 `--include-items` 还会自动注入 `_matched_filter_values.material_ids`（mm-cli ≥ 0.4.0）——agent client-side 按 mid 分组无需 fan-out |
| 含此物料的**库存**（wm） | `stock bin --material-id <id> --all` 单料；`stock bin --material-ids <id1> --material-ids <id2> ... --all` 多料 | typed flag，multi 触发**客户端并发 fan-out** | wm-cli ≥ 0.1.9 起 4 视图全支持 |
| 含此物料的**排产**（pp） | `production-plan list --filter materialIds=<id>` | `materialIds`（**camelCase**！） | pp 的 filter_keys 全是 camelCase，**不是** snake_case |
| 含此物料的**主数据**（md） | `material get <id>` / `material list --filter material_no=<no>` | typed/filter | 物料类目、单位、计划交期、MRP 类型 |
| 含此物料的**销售合同**（sd） | `contract-item list`（同理） | 待验证 | 模式应跟 sales-order-item 一致 |

#### 按物料/类目聚合金额硬规范
**只要题面是"某物料 / 某类目 / 某供应商 + 某金额"，就一定要 fan-out + items 二次聚合，不能用 header**。这条没有例外。

```text
错: header 累加
  exec mm purchase-order list --filter ...
  → jq '[.items[].local_total_tax_price] | add'   ❌ 整单合计累加

对: fan-out + items 筛 + items sum
  step 1: exec mm purchase-order list --filter ... --include-items   # 拿 PO + 行项
  step 2: jq '[.items[] | .items[]                                    # 展开行项
              | select(.material.material_category == "WGJ_1")        # 类目筛
              | .local_total_tax_price] | add'
```

**为什么 header 不能信**：mm/sd 的 list 接口 header `local_total_tax_price` 是该单**全部行项**的合计。用 `material_ids` filter 命中的 PO 里，仍含**非该物料的其他行**。直接 sum header 会把无关行的金额算进去。

**1 行 jq 模板**（按物料类目聚合金额，含伪物料剔除）：
```bash
python3 ${SKILL_DIR}/scripts/in3_cli.py exec mm purchase-order list \
  --filter from_ordered_at=... --filter to_ordered_at=... --include-items --all \
  | jq '[.items[] | .items[]
         | select(.material.material_category | test("^WGJ_(?!00)|^WXJ_"))
         | select(.material.material_no | test("WGJ_00|FY_|运费|杂费|包装费|垫付|领料单|批领") | not)
         | .local_total_tax_price] | add'
```

#### Top-N 物料分析：剔除"伪物料"再排名
按"采购金额 / 出库量 / 销售额"排 Top N 物料前，**先剔除两类伪物料**：

- **批领/费用类**（`material_no` 前缀 `WGJ_00`、`FY_`、含"运费/杂费/包装费/垫付"等）——会计科目挂物料
- **`material_no` 含"领料单/批领/批次领料"** 或 `material_category` 是 `BJ_*` 板材按米按公斤的

剔除方法（jq 示例）：

```bash
jq '.items | map(select(
  (.material_no // "" | test("^WGJ_00|^FY_|运费|杂费|包装费|垫付|批领") | not)
  and (.material_category != null)
))' /tmp/po_items.json
```

剔完再 `group_by(.material_id) | sort_by(-.total_amount) | .[0:5]` 拿 Top 5。

#### "孤儿物料"识别：list + set diff 套路（替代 N 次 fan-out get）
```bash
# 一次拿 sd 全租户行项里的 material_id（去重）
python3 ${SKILL_DIR}/scripts/in3_cli.py exec sd sales-order-item list --all --max 5000 --json > /tmp/sd_items.json
jq -r '.items[].material_id | select(. != null)' /tmp/sd_items.json | sort -u > /tmp/sd_mids.txt

# 一次拿 md 全字典 material_id
python3 ${SKILL_DIR}/scripts/in3_cli.py exec md material list --all --max 20000 --json > /tmp/md_all.json
jq -r '.items[].id' /tmp/md_all.json | sort -u > /tmp/md_mids.txt

# 集合差: sd 用过的 - md 现存的 = 候选孤儿
comm -23 /tmp/sd_mids.txt /tmp/md_mids.txt > /tmp/orphans.txt
```

> ⚠ **md `material list` 默认隐藏 `valid_to_date < today` 的过期物料**——上面 `md_mids.txt` 只含"当前有效"物料。差集结果是**候选孤儿**，必须逐个 `exec md material get <id>` 确认：
> - get 返完整对象但 `valid_to_date < today` → **过期但未删，业务通常仍可用**（不算真孤儿）
> - get 返全 null / 404 → **真删除/不存在**

#### PO header 字段 vs PO 行项字段（别混用）
mm `purchase-order` 在 list 和 get 里数量字段命名**不一样**，行项里**没有** `total_quantity`：

| 层级 | 数量字段 | 含义 |
|---|---|---|
| **PO header** | `total_quantity` | 整单总数量 |
| | `total_completed_quantity` | 整单已完成 |
| | `local_total_tax_price` | 整单含税合计 |
| **PO 行项**（`.items[]`） | `purchase_qty` | 该行采购数量 |
| | `open_qty` | 该行未交 |
| | `completed_qty` | 该行已完成 |
| | `shipped_qty` | 该行已发 |
| | `local_total_tax_price` | 该行含税金额 |

⚠️ 行项里**不要用** `total_quantity`——会得到 null，jq sum 出来全 0。

> ⚠ 跨模块 join **之前**先用 `exec md material get <id>` 验证物料还在——sd 等模块的 `material_id` 偶尔是孤儿。

#### "订单履约就绪度" 5-CLI 套路（实战示例）
回答"客户订了 X 物料，能交吗"这类问题：

```
exec sd sales-order get <so-id>           → 客户 + products[] (取 material_id + qty)
    ↓
exec md material get <material-id>        → 验证物料存在 + 拿类目/单位/计划交期
    ↓
exec wm stock bin --material-id <id>      → 在仓余量
    ↓
exec mm purchase-order list --filter material_ids=<id> --filter from_ordered_at=... → 在途采购
    ↓
exec pp production-plan list --filter materialIds=<id>  → 排产/MRP 计划
    ↓
缺口 = max(0, SO.qty - wm 余量 - mm 在途 - pp 排产)
```

#### 跨模块踩过的坑
1. **header total ≠ 类目金额**：mm `purchase-order list` 返回的 `local_total_tax_price` 是整单（含所有行）。真实归集必须 `get <id>` 拉行项，客户端二次筛
2. **filter key 命名风格不齐**：mm/wm/md/sd 用 snake_case（`material_ids`/`material_category`/`supplier_id`），**唯独 pp 用 camelCase**（`materialIds`/`plantId`/`productionPlanStatus`）
3. **wm 多个库存视图，空了别下结论**：`available-stock list/summary` 可能某些租户返空，但 `stock bin / material` 同步有数据；遇空换视图。wm 0.1.8+ `__schema.commands.stock.view_notes` 已文档化 4 个子视图语义
4. **`total` 字段持续返 0**（Spring Page.totalElements 不可靠），永远 `(items|length)` 自数
5. **取大类时先用 list 看 code 命名**：`material-category list` 一次返回所有类目，code 命名规律性强（`WGJ_*`=外购、`WXJ_*`=外协、`TY_*`=通用、`FG_*`=成品、`BJ_*`=板材、`XN_*`=虚拟）
6. **大批量补货类目**（紧固件/钣金外购）通常不直接绑 SO 也不走排产。fan-out `sales-order-item list --material` 和 `production-plan list --filter materialIds` 返 0 行**不是 bug 是业务**
7. **判断"独家供应"用历史 PO 反推**：`exec mm purchase-order list --filter material_ids=<id> --filter from_ordered_at=<近 180d> --all`，看 `supplier_id` 集合大小=1 视为独家。md 的 supplier 关联字段不可靠

#### 当前 CLI 能力速查（2026-06-04 verified；具体版本以 `status` 输出为准——workspace 可能已 upgrade 到更新版）
| 模块 | 版本 | 多值 filter | `__schema` | `--version` | `--json` |
|---|---|---|---|---|---|
| mm | 0.5.0 | ✅ `material_ids` (multi) + `--include-items` 注入 `_matched_filter_values` | ✅ + `item_fields` + `response_notes` + `pagination_notes` | ✅ | ✅ |
| wm | 0.1.16 | ✅ `--material-ids` (multi) + `--concurrency` 并发 fan-out（4 视图全支持） | ✅ + `view_notes` | ✅ | ✅（noop） |
| md | 0.1.8 | `material_category` / `procurement_type` / `mrp_type` (multi) | ✅ + `response_field_hints` | ✅ | ✅ |
| pp | 0.2.13 | ✅ `materialIds` (multi，**camelCase**) | ✅ | ✅(JSON) | ✅ |
| qm | 0.1.1 | (新接入,见 `__schema`) | ✅ | ✅ | ✅ |
| sd | 0.2.8 | ✅ `status`/`so_type`/`type`/`shipped_status` (multi)；bin pipe-flush 已修 | ✅ | ✅(JSON) | ✅ |
| cr | 0.1.0 | (新接入,见 `__schema`) | ✅ | ✅ | ✅ |
| fn | 0.1.1 | (新接入,见 `__schema`) | ✅ | ✅ | ✅ |

**仍存在的不一致**：

- pp filter key 是 camelCase，其他 7 个 snake_case
- sd 时间类 filter 是 datetime ISO（`YYYY-MM-DDTHH:mm:ss`），mm 是 date（`YYYY-MM-DD`）——同名 filter `from_ordered_at` 两个语义

## 关于密码
- 明文走 `getpass`，不进你的上下文，不落盘
- 加密用 SPA 同款 AES-128-ECB（实现在 `scripts/aes_encrypt.mjs`），密文落到 workspace 内 tenant 子目录
- 用户改密码 → 重跑 `login <alias>`，该 tenant 的所有 module profile 都会被覆写（其他 tenant 不受影响）
- 用户问"我密码怎么了" → 告诉他 skill 不存明文，重跑 login 即可

## 加新模块
完整步骤见 `references/module-onboarding.md`。核心：
1. 在 `scripts/in3_cli.py` 的 `MODULES` dict 加一项
2. 在 `MODULE_ENV_VARS` 加对应 env var 名（看新 CLI 的 `profile-store.ts` 实现）
3. 在 `templates/package.json` 加 dependency + 重新生成 `templates/package-lock.json`
4. 在 `references/modules.md` 加一节实体地图
5. 同事重跑 `init --force` 或 `install <new-mod>` 装上

## 不该做的事
- **不要直接调裸 module binary**（`ibrain-mm-cli ...`/`ibrain-wm-cli ...`）—— PATH 里没有，且不会自动注入 tenant env。**所有调用走 `exec`**
- 不要建议用户改 `~/.npmrc` 加 `_auth` —— registry 匿名可读，不需要
- 不要建议用户改全局环境变量 `IBRAIN_*_CONFIG_DIR` —— skill 在 `exec` 时自动注入，全局设了反而干扰
- 不要 `npm i -g @industics/*` —— 跟 workspace 隔离冲突；用户碰到这种 advice 提醒他跑 `doctor` 检查
- 不要自己直接 POST `oauth/token` 或写 token 缓存——每个模块 CLI 已经做完
- 不要 echo master cred 文件内容给用户——里头加密密文没必要露
- 不要在没 `status` 的情况下就跳到 `login` —— workspace 可能没 init，应该先 `init`
- 不要替用户输入密码 —— 必须经 getpass 进终端，由用户亲手敲
- 不要 pipe wm/md/pp/qm/cr/fn 大输出给 jq（pipe-flush fix 未 verify 同步）—— 走文件中转
- 不要用 logout 时省略 alias —— skill 设计上强制要求 alias，避免误删全部租户
- 不要建议 `uninstall` 当作"卸某个 tenant"用 —— 那是删整个 workspace；删单 tenant 用 `logout <alias>`
