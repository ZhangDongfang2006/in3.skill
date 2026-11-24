# Price Privilege — Issue Breakdown

> 来源 PRD: `prd-price-privilege.md`
> Label: `retired`（已退役）
> 依赖图: #1 ──→ #3 ──→ #4 ──→ #5 ←── #2
>
> 2026-08-28：IN3-CLI v1.3.0 已移除本地价格过滤。本文件只保留为历史任务拆分，不再是当前实现要求。

---

## Issue 1: 注册 identity CLI 到 in3-cli 调度器

### What to build

将 `@industics/ibrain-identity-cli`（v0.1.0，已发布到 npm.industics.cn）注册到 in3-cli 调度器，使其成为第 9 个模块。包括：

- `MODULE_ENV_VARS` 新增 `"identity": "IBRAIN_IDENTITY_CONFIG_DIR"`
- `MODULES` 新增 identity 模块注册项（npm_package: `@industics/ibrain-identity-cli`, binary: `ibrain-identity-cli`, base_suffix: `/mom/identity`, smoke_cmd/smoke_desc 根据 cli-capability.json 选最轻量的 entity）
- `templates/package.json` 新增 `"@industics/ibrain-identity-cli": "0.1.0"` 依赖
- 重新生成 `templates/package-lock.json`
- `references/modules.md` 补充 identity 模块的实体清单（9 个 entity：roles, tags, configs, users, orgs, apps, tenants, privileges, menus）

注册后 `in3-cli login` 流程应自动包含 identity CLI 的 profile 创建，`in3-cli status` 应显示 identity 模块状态。

### Acceptance criteria

- [ ] `in3_cli.py` 的 `MODULE_ENV_VARS` 包含 identity 条目
- [ ] `in3_cli.py` 的 `MODULES` 包含 identity 注册项，字段完整（npm_package, binary, base_suffix, smoke_cmd, smoke_desc, supports_plaintext_password, min_version_auto_use_context）
- [ ] `templates/package.json` 包含 `@industics/ibrain-identity-cli` 依赖
- [ ] `templates/package-lock.json` 已重新生成且包含 identity CLI
- [ ] `references/modules.md` 包含 identity 模块文档
- [ ] 现有 8 个模块的功能不受影响

### Blocked by

None - can start immediately

---

## Issue 2: PriceFieldScrubber — 递归关键词字段删除

### What to build

新建 `scripts/price_scrubber.py`，实现纯函数 `scrub_price_fields(data) -> data`：

- 递归遍历整棵 JSON 树（dict 每层 key + list 内每个元素）
- 对每个 dict 的 key 做大小写不敏感匹配，包含以下任一关键词则删除整个 key-value 对：`price`, `amount`, `cost`, `fee`, `charge`, `discount`, `margin`, `tax`
- 白名单机制：key 完全匹配白名单（初始: `person_in_charge`）则跳过删除
- 白名单定义为模块级常量 `PRICE_FIELD_WHITELIST`，方便扩展
- 输入为 dict 或 list，输出为同类型的过滤后副本（不修改原对象）

配套完整单元测试。

### Acceptance criteria

- [ ] `scrub_price_fields({})` 返回 `{}`
- [ ] `scrub_price_fields([])` 返回 `[]`
- [ ] 单层 dict 中包含 `local_total_tax_price` 的 key 被删除
- [ ] 二层、三层嵌套中的价格字段被删除
- [ ] `items[]` 数组内对象的价格字段被删除
- [ ] 8 个关键词各至少一个测试用例命中
- [ ] `person_in_charge` 不被删除（白名单生效）
- [ ] 大小写不敏感：`Unit_Price`, `TOTAL_AMOUNT` 等均命中
- [ ] 无价格字段的 JSON 原样通过（非价格 key 不丢失）
- [ ] 不修改原始输入对象（返回新副本）

### Blocked by

None - can start immediately

---

## Issue 3: PricePrivilegeChecker — 角色查询 + 缓存 + TTL + 降级

### What to build

新建 `scripts/price_privilege.py`，实现 `has_price_privilege(workspace_path, tenant_alias) -> bool`：

**查询链路：**
1. 从 tenant 的 credentials 中读取 username
2. 调用 `ibrain-identity-cli users get <username> --by-username` 拿到 user_id
3. 调用 `ibrain-identity-cli roles list --user-id <user_id>` 拿到角色列表
4. 检查角色列表中是否包含 `price_viewer`

**缓存机制：**
- 缓存文件位置：`<tenant_config>/.price-privilege-cache.json`
- 缓存结构：`{"has_privilege": bool, "cached_at": "ISO8601", "username": str, "roles": [str]}`
- TTL：24 小时。`cached_at` + 24h > now → 直接返回缓存
- 过期后自动重新查询 identity CLI 并更新缓存

**降级逻辑：**
- identity CLI 调用失败 + 有旧缓存 → 返回旧缓存结果 + stderr 警告
- identity CLI 调用失败 + 无旧缓存 → 返回 `false`（deny）

配套完整单元测试（用 subprocess mock 模拟 identity CLI 调用）。

### Acceptance criteria

- [ ] 缓存命中且 TTL 内 → 直接返回缓存结果，不调 identity CLI
- [ ] 缓存过期 → 重新调 identity CLI 并更新缓存文件
- [ ] 无缓存首次查询 → 调 identity CLI 并写入缓存
- [ ] identity CLI 失败 + 有旧缓存 → 返回旧缓存结果 + stderr 有警告
- [ ] identity CLI 失败 + 无缓存 → 返回 `false`
- [ ] 角色列表包含 `price_viewer` → 返回 `true`
- [ ] 角色列表不包含 `price_viewer` → 返回 `false`
- [ ] 缓存文件写入格式正确（JSON，含 has_privilege / cached_at / username / roles）

### Blocked by

- Issue 1（identity CLI 必须先注册到调度器）

---

## Issue 4: 调度器 — 模块/entity 级别禁用 + PRIVILEGE_DENIED

### What to build

修改 `in3_cli.py`，在执行模块 CLI **之前**插入权限检查：

**整模块禁用：**
- 目标模块是 `fn` 且 `has_price_privilege() == False` → 不调 CLI，直接返回 PRIVILEGE_DENIED

**整 entity 禁用：**
- mm 的 `info-record`、`quotation`
- sd 的 `sd-info-record`、`quotation`
- cr 的 `fee`
- 以上 entity 在 `has_price_privilege() == False` 时 → 不调 CLI，直接返回 PRIVILEGE_DENIED

**PRIVILEGE_DENIED 响应格式：**
```json
{"error": {"type": "PRIVILEGE_DENIED", "message": "您无权查看价格相关数据，请联系管理员获取 price_viewer 角色"}}
```

禁用配置定义为调度器中的集中常量（如 `PRICE_BLOCKED_MODULES` 和 `PRICE_BLOCKED_ENTITIES`），方便维护。

cr 的 `fee-category`（费用类别字典）不禁用。

配套集成测试。

### Acceptance criteria

- [ ] 无价格权限 + 请求 fn 任意 entity → PRIVILEGE_DENIED JSON
- [ ] 无价格权限 + 请求 mm info-record → PRIVILEGE_DENIED JSON
- [ ] 无价格权限 + 请求 mm quotation → PRIVILEGE_DENIED JSON
- [ ] 无价格权限 + 请求 sd sd-info-record → PRIVILEGE_DENIED JSON
- [ ] 无价格权限 + 请求 sd quotation → PRIVILEGE_DENIED JSON
- [ ] 无价格权限 + 请求 cr fee → PRIVILEGE_DENIED JSON
- [ ] 无价格权限 + 请求 cr fee-category → 正常返回（不禁用）
- [ ] 无价格权限 + 请求 mm purchase-order → 正常调 CLI（不在本 issue 做字段过滤）
- [ ] 有价格权限 + 请求以上所有 → 正常调 CLI
- [ ] PRIVILEGE_DENIED 的 JSON 格式与 error envelope 规范一致

### Blocked by

- Issue 3（需要 PricePrivilegeChecker）

---

## Issue 5: 调度器 — 字段级 scrub 集成到 CLI 输出出口

### What to build

修改 `in3_cli.py`，在执行模块 CLI 拿到 JSON **之后**、返回给 LLM **之前**，插入字段级过滤：

- 如果 `has_price_privilege() == False`，对 CLI 返回的 JSON 调用 `scrub_price_fields()` 后再输出
- 过滤逻辑在统一的"执行模块 CLI 并收集结果"的出口函数中，一处代码覆盖所有模块
- 已被 Issue 4 整模块/entity 禁用的请求不会走到这里（已提前返回 PRIVILEGE_DENIED）

这是最终集成 slice，完成后整个 price privilege 功能端到端可用。

配套集成测试。

### Acceptance criteria

- [ ] 无价格权限 + mm purchase-order list → 返回数据但 `local_total_tax_price` 等价格字段被删除
- [ ] 无价格权限 + mm purchase-order get → header 和 items 中的价格字段均被删除
- [ ] 无价格权限 + sd sales-order get → `total_amount`、`local_total_amount`、`local_total_tax_amount`、`products[].local_total_tax_price` 均被删除
- [ ] 无价格权限 + wm/pp/qm/md 请求 → 非价格字段完整保留
- [ ] 有价格权限 + 任意模块 → 返回完整数据，不过滤
- [ ] 过滤逻辑只在一处出口函数中（不分散到各模块）
- [ ] `person_in_charge` 等白名单字段未被误删
