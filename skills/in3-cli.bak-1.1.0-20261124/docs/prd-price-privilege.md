# PRD: IN3-CLI 价格权限控制 (Price Privilege)

**状态**: retired（已退役）
**日期**: 2026-05-25
**作者**: shenchenjian

> 退役说明（2026-08-28）：IN3-CLI v1.3.0 已移除本地 `price_viewer` 检查和价格字段过滤。本文仅保留为历史设计记录，不再代表当前行为；现行说明见 `price-fields-pass-through.md`。

---

## Problem Statement

IN3-CLI 调度器当前对所有已登录用户返回完整的业务数据，包括采购金额、销售金额、供应商报价、发票、收付款等敏感价格信息。企业需要按角色控制哪些用户可以看到价格数据——没有 `price_viewer` 角色的用户不应看到任何价格相关字段、实体或模块。

## Solution

在 in3-cli Python 调度器层集成 `ibrain-identity-cli`，通过查询当前用户在 IN3 identity 系统中的角色来判定价格查看权限。无 `price_viewer` 角色的用户：

1. 整个 fn（财务）模块不可用
2. 特定价格本质的 entity（mm info-record/quotation、sd sd-info-record/quotation、cr fee）不可用
3. 其余模块返回的 JSON 中，所有包含价格关键词的字段被递归删除

## User Stories

1. As a 仓管人员, I want to query inventory and shipment data without seeing any price information, so that I can do my job without accessing sensitive financial data.
2. As a 采购经理 with `price_viewer` role, I want to see full purchase order data including prices, so that I can analyze procurement spend.
3. As a 系统管理员, I want to assign the `price_viewer` role to specific users in identity, so that I can control who sees price data.
4. As a 无价格权限用户, I want to receive a clear error message when I try to access price-related entities (info-record, quotation, fee, fn module), so that I know to contact my admin for access rather than thinking the system is broken.
5. As a 有价格权限用户, I want prices to show up immediately without extra steps after logging in, so that the permission check is transparent to me.
6. As a 用户 whose role was just changed, I want the permission cache to refresh within 24 hours automatically, so that I don't need manual intervention.
7. As a 用户 whose identity service is temporarily down, I want to keep my previously cached permission, so that a transient outage doesn't block my work.
8. As a 首次登录用户 on a tenant that hasn't configured identity, I want a clear message that price data is unavailable, so that I understand the tenant needs identity setup.
9. As a 开发者 maintaining in3-cli, I want price filtering logic centralized in one place in the dispatcher, so that adding new modules doesn't require remembering to add filtering code in multiple places.
10. As a 开发者, I want a whitelist mechanism for false-positive field names (like `person_in_charge` matching `charge`), so that non-price fields aren't accidentally hidden.
11. As a 无价格权限用户 querying purchase orders, I want to see order status, quantities, dates, and materials — just not prices, so that I can still track order progress.
12. As a 用户 querying cr service-orders, I want to see service order details but not fee data, so that I can track service work without seeing costs.
13. As a 有价格权限用户 querying mm info-record, I want full access to supplier-material-plant pricing data, so that I can compare supplier quotes.

## Implementation Decisions

### 模块架构

三个逻辑模块，全部在 `in3_cli.py` 所在的 `scripts/` 目录下：

**1. PricePrivilegeChecker（`price_privilege.py`）**

- 职责：判定当前用户是否拥有 `price_viewer` 角色
- 接口：`has_price_privilege(workspace_path, tenant_alias) -> bool`
- 内部流程：
  - 读取 tenant profile 中的 credentials 获取 username
  - 检查本地缓存文件（`<tenant_config>/.price-privilege-cache.json`），如果 TTL（24h）内直接返回缓存结果
  - TTL 过期时调用 identity CLI：`ibrain-identity-cli users get <username> --by-username` → 拿 user_id → `ibrain-identity-cli roles list --user-id <user_id>` → 检查是否包含 `price_viewer`
  - 缓存结构：`{"has_privilege": bool, "cached_at": ISO8601, "username": str, "roles": [str]}`
- 降级逻辑：
  - identity CLI 调用失败 + 有旧缓存 → 续用旧缓存，stderr 警告
  - identity CLI 调用失败 + 无旧缓存 → 返回 `false`（deny）

**2. PriceFieldScrubber（`price_scrubber.py`）**

- 职责：从 JSON 数据中递归删除价格相关字段
- 接口：`scrub_price_fields(data: dict | list) -> dict | list`
- 关键词列表（匹配 key 名，大小写不敏感）：`price`, `amount`, `cost`, `fee`, `charge`, `discount`, `margin`, `tax`
- 白名单（key 名完全匹配，跳过删除）：初始包含 `person_in_charge`，可扩展
- 递归遍历整棵 JSON 树（dict 的每一层 key + list 内的每个元素）
- 纯函数，无副作用

**3. 调度器集成（改 `in3_cli.py`）**

- 在执行模块 CLI 之前：
  - 如果 `has_price_privilege() == False`：
    - 目标模块是 `fn` → 返回 `PRIVILEGE_DENIED` 错误 JSON
    - 目标 entity 是 mm `info-record`/`quotation`、sd `sd-info-record`/`quotation`、cr `fee` → 返回 `PRIVILEGE_DENIED` 错误 JSON
- 在执行模块 CLI 拿到 JSON 之后：
  - 如果 `has_price_privilege() == False` → 调用 `scrub_price_fields()` 过滤输出
- PRIVILEGE_DENIED 错误格式：`{"error": {"type": "PRIVILEGE_DENIED", "message": "您无权查看价格相关数据，请联系管理员获取 price_viewer 角色"}}`

### Identity CLI 注册

- 在 `MODULE_ENV_VARS` 新增 `"identity": "IBRAIN_IDENTITY_CONFIG_DIR"`
- 在 `MODULES` 新增 identity 模块注册项（npm_package, binary, base_suffix, smoke_cmd 等）
- 在 `templates/package.json` 新增 `"@industics/ibrain-identity-cli": "0.1.0"` 依赖
- 重新生成 `templates/package-lock.json`

### 关键约束

- 全局生效：所有租户都走价格权限检查，未配 identity 的租户默认看不到价格
- TTL 24 小时：缓存写入时间戳，过期后自动刷新
- 字段过滤仅在调度器出口统一执行一次，不分散到各模块

## Testing Decisions

好的测试只验证外部行为（输入→输出），不验证内部实现细节。

### PriceFieldScrubber 单元测试

- 单层 dict：包含 `local_total_tax_price` 的 key 被删除
- 嵌套 dict：二层、三层嵌套中的价格字段被删除
- 数组内对象：`items[]` 内的价格字段被删除
- 8 个关键词各至少一个用例：`price`, `amount`, `cost`, `fee`, `charge`, `discount`, `margin`, `tax`
- 白名单：`person_in_charge` 不被删除
- 大小写不敏感：`Unit_Price`, `TOTAL_AMOUNT` 等均命中
- 无价格字段的 JSON 原样通过
- 空 dict / 空 list / None 边界情况

### PricePrivilegeChecker 单元测试

- 缓存命中且 TTL 内：直接返回缓存结果，不调 identity CLI
- 缓存过期：重新调 identity CLI 并更新缓存
- 无缓存首次查询：调 identity CLI 并写入缓存
- identity CLI 失败 + 有旧缓存：返回旧缓存结果 + stderr 警告
- identity CLI 失败 + 无缓存：返回 false
- 角色列表包含 `price_viewer`：返回 true
- 角色列表不包含 `price_viewer`：返回 false
- 用 mock/subprocess patch 模拟 identity CLI 调用

### 调度器集成测试

- 无价格权限 + 请求 fn 模块 → PRIVILEGE_DENIED
- 无价格权限 + 请求 mm info-record → PRIVILEGE_DENIED
- 无价格权限 + 请求 mm purchase-order → 返回数据但价格字段已删除
- 有价格权限 + 请求 mm purchase-order → 返回完整数据
- 无价格权限 + 请求 wm/pp/qm/md → 返回数据且非价格字段完整保留

## Out of Scope

- 后端 API 层的权限控制（本 PRD 只在 CLI 调度器层做客户端过滤）
- 字段级的细粒度权限（如"能看采购价但不能看销售价"）——本版只有一个 `price_viewer` 开关
- identity CLI 本身的功能扩展（entity 新增、filter 增强等）
- 其他非价格类的权限控制（如按部门限制可见数据范围）
- `price_viewer` 角色在 IN3 identity 系统中的创建和分配（由租户管理员在 SPA 上操作）
- WM 模块的隐性价格字段排查（当前 WM schema 中未发现显式价格字段，但后端返回可能包含——由关键词匹配兜底）

## Further Notes

- **Breaking change 意识**：上线后所有未配 identity 的现有租户将默认看不到价格。需要在发布说明中明确告知，并提供 identity 配置指引。
- **白名单维护**：关键词匹配的误杀字段需要在实际使用中逐步发现并加入白名单。建议上线初期收集 stderr/日志中被过滤的字段名，人工 review 后补充白名单。
- **identity CLI 安装前置**：workspace 的 `npm ci` 会自动安装 `@industics/ibrain-identity-cli`，但各租户的 identity CLI login（`ibrain-identity-cli config add-profile`）需要在 `in3-cli login` 流程中一并完成。
- **cr `fee-category` 保留**：虽然 `fee` entity 被禁用，但 `fee-category`（费用类别字典）不含金额数据，保留不过滤。
