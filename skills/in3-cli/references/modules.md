# IN3 模块注册表与实体地图

skill 触发时，Claude 用这份表决定"用户的问题该走哪个模块的哪个命令"。

## 当前已接入

### `mm` — ibrain-mm-cli (Material Management)

- npm 包: `@industics/ibrain-mm-cli`
- 二进制: `ibrain-mm-cli`
- 配置路径: `<workspace>/tenants/<alias>/.ibrain-mm/config.json`（1.0 workspace-scoped；profile 名 = tenant alias，通过 `in3-cli use <alias>` 切）
- API base: `<api_host>/mom/mm`（例 `https://apiv3.industics.com/service/mom/mm`）
- Smoke: `ibrain-mm-cli currency list` — 列出本租户启用的币种
- 鉴权: SPA password grant，AES 密文密码

#### 实体清单

| 实体 | CLI 子命令 | 必填 flag | 业务对应 |
|---|---|---|---|
| 采购订单 (PO) | `purchase-order list` / `get <id>` | 可选 `--plant` | 5 月采购金额、某供应商订单、PO 状态 |
| 采购需求 (PR) | `purchase-requirement list` / `get <id>` | 可选 `--plant --status --ordered-by` | 待审批 PR、某人发起的 PR |
| 合同 (Contract) | `contract list` / `get <id>` | 可选 `--supplier --plant` | 在执行合同、某供应商合同 |
| 信息记录 (InfoRecord) | `info-record list` / `get <id>` | 可选 `--material --plant --supplier` | 供应商×物料×工厂的报价 |
| 货源清单 (SourceList) | `source-list list` / `get <id>` | 可选 `--material --plant --supplier` | 某物料允许的供应商 |
| BOM | `bom list` / `get <material-id>` | `list` 必传 `--material` | 物料 BOM 层级、组件清单 |
| 工程变更 (ECN) | `ecn list` | 可选 `--status` | 变更单清单 |
| 询价 (RFQ) | `rfq list` / `get <id>` | 可选 `--plant --status` | 询价单、各询价状态 |
| 报价 (Quotation) | `quotation list` / `get <id>` | 可选 `--rfq --supplier` | 某询价的供应商报价 |
| 供应商 (Supplier) | `supplier list` / `get <id>` | 可选 `--name --erp-code --status` | 供应商信息、CA、附件 |
| 币种 (Currency) | `currency list` / `get <currency-no>` | 无 | 启用币种 + 汇率 |

#### 通用 flag

- `--all --max <n>`：翻页拿全部（默认 max 1000）
- `--page --size`：手工分页（默认 size 20，max 200）
- `--filter k=v`：服务端过滤（可重复），key 列表见 `__schema` 每个 list 命令的 `filter_keys`
- `-v` / `-vv`：调试 HTTP（凭证脱敏）
- `--format json|table|csv`：终端格式

#### 服务端 filter（mm-cli 0.2.0+）

每个 entity 后端真实接受的过滤字段都在 `__schema` 里：

```bash
ibrain-mm-cli __schema | jq '.commands."<entity>".list.filter_keys'
```

##### 常用 filter（mm 现役实体）

| 实体 | 高频 filter_keys | 备注 |
|---|---|---|
| purchase-order | `from_ordered_at` / `to_ordered_at`（date）、`status`（multi）、`supplier_id`（multi）、`po_no`、`pr_no`、`material_ids`（multi）、`only_overdue` / `only_open` / `no_contract`（bool） | 日期类还有 `from_created_date/to_created_date`、`from_modified_date/to_modified_date` |
| purchase-requirement | `from_created_date` / `to_created_date`、`status`（multi）、`ordered_by`、`pr_no`、`approval_statuses`（multi） | |
| contract | `from_created_date` / `to_created_date`、`status`（multi）、`supplier_id`（multi）、`category` (ONLINE \| OFFLINE)、`contract_no`、`po_no` | |
| bom | `from_created_date` / `to_created_date`、`from_modified_date` / `to_modified_date`、`material_id`、`bom_name`、`bom_rev` | |
| ecn | `from_time` / `to_time`（datetime）、`material_ids`（multi）、`so_no` | 注意 ecn 是 `*_time` 不是 `*_date` |
| rfq | `rfq_date_from` / `rfq_date_to`（date）、`rfq_valid_to_date_from` / `_to`、`statuses`（multi）、`rfq_no` | 命名跟 PO 反着，是 `_from` / `_to` 后缀 |
| quotation | `quotation_date_from` / `quotation_date_to`、`rfq_id`、`supplier_ids`（multi）、`statuses` | |
| info-record | `supplier_id`、`material_id`、`only_latest`（bool） | |
| supplier | `name`、`erp_code`、`status`（multi）、`supplier_type` | 无日期 filter |

##### 命名约定

- **PO/PR/Contract/BOM**：日期类是 `from_<field>` / `to_<field>`（前缀 from/to）
- **RFQ/Quotation**：日期类是 `<field>_from` / `<field>_to`（后缀 from/to）
- **ECN**：用 `from_time` / `to_time`（datetime 类型）
- 不确定时一律看 `__schema.filter_keys`，别猜

##### 例：5 月下达 + 状态非完成的 PO

```bash
ibrain-mm-cli purchase-order list \
  --filter "from_ordered_at=2026-05-01" \
  --filter "to_ordered_at=2026-05-31" \
  --filter "status=W" --filter "status=I" \
  --all --max 5000
```

##### 已知坑

- **`total` 字段返回 0**（v0.2.0 未修），别用它判断结果数，用 `(items|length)`
- 服务端 filter 偶尔比客户端慢——命中率高时 `--all` 拉全表 + jq 反而快
- `--filter` 的 key 不在 `filter_keys` 里时后端**静默忽略**（不报错，返回全量），结果数应该跟基准一致就说明 key 没生效
- **PO `status` 是单字母生命周期码**，后端无 `status_name` 字段（须按码表翻译；ibrain-mm-cli ≥ 0.6.2 已把码表注入 `__schema` 的 status filter/response note）。来源后端 `PurchaseOrderStatusEnum`：`P`=待处理 `E`=待审批 `S`=待发送 `W`=待供应商确认 `I`=待发货 `R`=已发货 `T`=部分到货 `F`=全部到货 `A`=已废弃。⚠️ **`F`=全部到货（收货完成），不是"已完成下达"**；`status` 支持多值 filter（`--filter status=W --filter status=I`）。

#### 命令树兜底

```bash
ibrain-mm-cli __schema | jq '.commands'
```

返回完整 JSON Schema，agent 拿来选 flag + filter_keys。

#### 错误信封

非零退出时 stdout 仍是合法 JSON：

```json
{"error":{"type":"AUTH_FAILED|NOT_FOUND|VALIDATION|NETWORK|SERVER","message":"...","http_status":401}}
```

退出码：0 成功 / 2 鉴权失败 / 3 未找到 / 4 参数错 / 5 网络。

---

### `wm` — ibrain-wm-cli (Warehouse Management)

- npm 包: `@industics/ibrain-wm-cli`（v0.1.16 已发 npm.industics.cn · 2026-05-20 verified · 19 entity 全 200 · stock 4 视图全 `--material-ids` multi）
- 二进制: `ibrain-wm-cli`
- 配置路径: `<workspace>/tenants/<alias>/.ibrain-wm/config.json`（1.0 workspace-scoped；profile 名 = tenant alias，通过 `in3-cli use <alias>` 切）
- API base: `<api_host>/mom/wm`（例 `https://apiv3.industics.com/service/mom/wm`）
- Smoke: `ibrain-wm-cli rd-category list` — 列出本租户的收发类别字典
- 鉴权: SPA password grant，AES-128-ECB（key `HGY12345HGY12345`），`--password 明文`
- 真后端验证: prod (`apiv3.industics.com` · 租户 indx) 19/19 entity 全 200

#### 实体清单（19 个）

| 业务域 | CLI 子命令 | 子动作 | 业务对应 |
|---|---|---|---|
| 销售发运单 | `sales-order-shipment` | list / get / lines | 25 filter; lines=行项 |
| 物料凭证 | `material-doc` | list / get / items | items=明细行项 |
| 调拨单 | `trans-order` | list / get / items | items 走独立 `/tos-items/page` (23 filter, 跨单查行项) |
| 出入库申请 | `warehouse-request` | list / get / items <id> | items 按 `<request-id>` 查行项 |
| 盘点任务 | `inventory-check-task` | list / get / items <id> | items 按盘点 id 查; --include-diff-only 仅看差异 |
| 领料申请 | `requisition` | list / get | 20 filter |
| 检验单 | `check-order` | list / get / details / pending | details=明细视图; pending=待检清单 |
| 装配/拆解单 | `assembly-order` | list / get / disassembly-list / disassembly-get | 装+拆合一; POST body `--filter k=v` |
| 工单 | `mo` | list / info / kitting-items | 没有 get-by-id; info 按 mo_no 查; kitting-items 按 mo_no 查投料 |
| 销售发运单 lookup | `delivery-order` | summary | 仅按 ref 查 summary; **业务 list 走 sales-order-shipment** |
| 库存 | `stock` | material / bin / storage-location / storage-bin | 4 个 sub 视图，14 共享 filter |
| 可用库存 | `available-stock` | list / summary / types / config / estimated-incoming | POST body `--filter k=v`; estimated-incoming 需 --material-id |
| 物料单元 | `unit` | list / get | 6 filter + --fuzzy 模糊 sn |
| 移动类型 | `move-type` | list | 含借贷反转标志 |
| 收发类别 | `rd-category` | list | 字典型，无 filter（smoke 首选） |
| 库存地点 | `storage-location` | list | 用 --storage-location-no 精确查（无单条 get） |
| 货位 | `storage-bin` | list | 17 filter (8 string + 9 boolean) |
| 仓库 | `warehouse` | list / get | warehouse-no 别名 |
| WM 业务配置 | `wm-config` | document-configs / lot-strategies (3 个) / delivery-order-config / etc. | 6 个字典型 sub |

#### 通用 flag

- `--page --size`：分页（默认 size 20）
- `--verbose` / `--vv`：调试 HTTP（凭证脱敏）
- 输出: 默认 stdout JSON（`{items, page, total, has_next}` for Page · 数组 for array endpoint）
- 单据系都含 items / lines / details 明细 verb（按上表）

#### 分页契约 (v0.1.6+ · 见 #034 二修)

Page<T> 输出:
- `items: T[]` — 始终为数组，可空
- `page: number` — 当前 0-indexed 页号
- `total: number | null` — **可能为 null** (后端 Spring Slice 不给 total, e.g. `material-doc`/`trans-order`)；agent **不要**用它判分页
- `has_next: boolean` — **可靠分页信号**，优先取后端 `last` 字段，没给则启发 (items.length < size → false)

agent 用法:
```bash
ibrain-wm-cli material-doc list --size 20 --page 0 | jq -r '.has_next'   # true → 接着拉下一页
ibrain-wm-cli material-doc list --size 20 --page 0 | jq -r '.items | length'  # 想要计数, 走 items 长度
```

`--all` / `--max` 已内置基于 `has_next` 的拉满逻辑，不必自己分页。

#### 错误信封 + 退出码

- 0 成功 / 2 参数错 / 3 鉴权失败 / 4 服务端 5xx / 5 NOT_FOUND / 6 FORBIDDEN / 7 CLIENT_ERROR
- 错误信封: `{"error":{"code":"NOT_FOUND|CLIENT_ERROR|SERVER_ERROR","message":"...","http_status":404}}` to stderr

#### 已知坑

- **`material` 不在 wm 后端**（在 MDM 服务），wm-cli 没有 `material` 命令
- **`delivery-order` 公开仅 summary lookup**，要查销售发运单清单走 `sales-order-shipment`
- **`mo` 没 get-by-id**，用 `mo info --mo-no XXX` 查指定工单
- 部分实体的"items 明细"endpoint 是顶级独立路径（如 trans-order 的 `/tos-items` 而非 `/tos/{id}/items`），不会跟着单据 id 走

---

### `md` — in-mom-md-cli (Master Data)

- npm 包: `@industics/in-mom-md-cli`
- 二进制: `in-mom-md-cli`
- 配置路径: `<workspace>/tenants/<alias>/.in-mom-md/config.json`（1.0 workspace-scoped；profile 名 = tenant alias，通过 `in3-cli use <alias>` 切）
- API base: `<api_host>/mom/md`
- Smoke: `in-mom-md-cli currency list`
- 鉴权: SPA password grant, AES 密文

主数据字典层，是 mm/wm/pp/sd 共同的查表基础——业务里出现的 material/plant/currency/material-category 等都从这里查。

#### 实体清单

| 实体 | CLI 子命令 | 用途 |
|---|---|---|
| 物料 | `material list` / `get <id>` | 物料主数据（48 个 field_a..field_av 扩展字段，丰富的 filter） |
| 物料类目 | `material-category list` | 全量返回，**无 filter**；code 命名规律（WGJ_/WXJ_/TY_/FG_/BJ_/XN_ 等），用户问"原材料/紧固件/外购件"先 list 出来映射到 code |
| 物料计量单位 | `measure-unit list` | 单位字典 |
| 工厂 | `plant list` / `get <id>` | plant_id ↔ plant_no ↔ plant_name 映射 |
| 公司代码 | `company-code list` | 财务实体 |
| 销售组织 | `sales-organization list` | SD 用 |
| 产品层级 | `product-level list` | 物料分类层级 |
| 币种 | `currency list` | 启用币种 |
| 汇率 | `exchange-rate list` | 币种间汇率 |
| 客户/账户 | `account list` / `get <id>` | 客户主数据 |
| 客户联系人 | `account-contact list` | account 子表 |

#### 常用 filter

- `material list`: `material_query`（模糊）、`material_no`、`material_name`、`material_category`（取 **code**，multi）、`material_group`、`brand`、还有 48 个扩展字段过滤
- 其余字典型实体大多无 filter，直接 `list` 拿全量

#### 已知坑

- `material-category list` 是非分页全量返回，items 数量约几十到上百
- `material list` 走分页，配 `--all --max 5000`
- filter `material_category` 取 **code 字符串**（如 `WGJ_1`），不是 category id

---

### `pp` — ibrain-pp-cli (Production Planning)

- npm 包: `@industics/ibrain-pp-cli`（已上线 npm.industics.cn）
- 二进制: `ibrain-pp-cli`
- 配置路径: `<workspace>/tenants/<alias>/.ibrain-pp/config.json`（1.0 workspace-scoped；profile 名 = tenant alias，通过 `in3-cli use <alias>` 切）
- API base: `<api_host>/mom/pp`
- Smoke: `ibrain-pp-cli production-plan list --size 1`
- 鉴权: SPA password grant, AES 密文

生产计划/MRP/工单计划侧。注意：**车间执行级的工单**（mo, 完工/投料/检验）在 wm，**计划级的工单/MRP/物料需求**在 pp。

#### 实体清单

| 实体 | CLI 子命令 | 用途 |
|---|---|---|
| 生产计划 | `production-plan list` / `get <id>` | 计划单（pp 的主实体） |
| 生产计划记录 | `production-plan-record list` | 计划执行记录/变更日志 |
| 需求供应 | `demand-supply list` | MRP 需求/供应平衡视图 |
| MRP 历史 | `mrp-history list` | MRP 运行历史 |
| MRP 规则 | `mrp-rule list` | 物料/工厂级的 MRP 策略 |
| BOM 树 | `bom-tree get <material-id>` | 多层展开 BOM（区别于 mm 的 `bom get`，pp 这个是展开后的多层视图） |
| 配套模板 | `kitting-template list` | 投料配套模板 |
| 销售订单（pp 视图） | `sales-order list` | pp 服务自己的 so 视图，跟 sd 的 sales-order 不是同一份数据，是 pp 维度的 so 引用 |

#### 已知坑

**1. `pp.sales-order` 是物料反向视图，不是 SO 头表（R7 修正）**

`pp sales-order list` 返回 `Page<MaterialStatisticsVO>`——按物料维度聚合的统计行（material_id / material_no / 占用 / 可用 等），**不返回 SO header**（无 so_id / so_no / customer 字段）。`sd sales-order list` 才是 SO 主数据（header + status + amount + products[]）。

- 想找"哪些客户/合同有 SO" → 走 **sd.sales-order**
- 想找"某物料被哪些 SO 占用 / 物料级销售统计" → 走 **pp.sales-order** 或 **sd.sales-order-item list --material**

**跨模块联查时不要混**——R7 实测：用 `pp sales-order list` 查"客户 X 的 SO 数"必然 0 行，因为返回结构里压根没 customer/account 维度。

**2. pp 的"工单"≠ wm 的 `mo`**

同一物理实体不同抽象层：pp 看的是**计划下达侧**（产线计划），wm 看的是**车间执行侧**（`mo info` / `kitting-items`）。

**3. filter_keys 全是 camelCase，是 IN3 全家桶里的异类**（pp 0.2.5 实测）

| 模块 | filter_key 风格 | 示例 |
|---|---|---|
| mm / wm / md / sd | **snake_case** | `from_ordered_at`、`material_ids`、`account_id` |
| **pp** | **camelCase** | `materialIds`、`accountId`、`plantId`、`productionPlanStatus` |

跨模块组装时容易踩：习惯了 `--filter material_ids=xxx` 的写法到 pp 必须改写 `--filter materialIds=xxx`，且 pp 后端**静默忽略**不在 filter_keys 里的 key（同 mm 行为），不会报错只会返全量。

**4. pp 自带第三种日期 filter 命名约定**

IN3 全家桶里日期 filter 已经有两种约定，pp 又给了第三种：

| 风格 | 用在 | 示例 |
|---|---|---|
| `from_<field>` / `to_<field>` | mm 多数实体、sd | `from_ordered_at` / `to_ordered_at` |
| `<field>_from` / `<field>_to` | mm 的 rfq / quotation | `rfq_date_from` / `rfq_date_to` |
| **`<event>StartDate` / `<event>EndDate`** | **pp 全部** | `createdStartDate` / `createdEndDate`、`planProdStartDate` / `planProdEndDate`、`actualStockStartDate` / `actualStockEndDate` |

pp 的 `production-plan.list` 一口气暴露 50 个 filter_keys，覆盖创建/最后修改/计划生产/实际生产/计划入库/实际入库 6 组时间窗——选哪一组取决于业务问题问的是"哪个时间点"。

**5. CLI 通 ≠ 数据有（租户差异大，不要默认空）**

`pp` 在某些租户曾经所有 list 端点返回 `items: []`——但**这条论断已过时**。doctor R1-R3 实测 indx prod 在 2026-05 已有 `production-plan ≥ 577 条 / mrp-history ≥ 466 条`，pp 不再真空。先用 `production-plan list --max 5` 拿一条看真实结构，再决定后续路由；遇到 0 条**先核对 plantId 是否收敛到该租户实际工厂**，不是默认 CLI 坏。

**6. 后端 filter 静默忽略（P16，0.2.9+ CLI 端 fail-loud）**

`production-plan list` 后端把 query body 里**所有** filter 字段（`plantId / materialIds / sn / createdStartDate / createdEndDate / productionPlanStatus`）**全部静默忽略**——传与不传返回完全一致全量。ibrain-pp-cli 0.2.9+ 在 stderr 输出 `[P16] WARN` 提醒；后端修好前**永远不要相信 production-plan list 的结果集是 filtered 的**，必须拉全后 jq client-side `.items[] | select(.material_id == ...)` 过滤。

> ⚠️ 因为 filter 被忽略，做单物料/单工厂查询时 `--max` 给小会**静默漏数**（doctor 实测 `--max 300` 只命中 2 条、`--max 3000` 拉全 651 条才命中 4 条）。必须 `--all` 或把 `--max` 给到覆盖全表，再客户端筛。

**7. 数量字段叫 `total_quantity` / `completed_quantity`，不是 `plan_qty` / `quantity`**

doctor 2026-06 实测：`production-plan` 的计划数量在 `total_quantity`（与 wm 库存数量同名），已完成在 `completed_quantity`，另有 `shipped_qty` / `scrap_quantity` / `rework_quantity`。直觉的 `plan_qty` / `quantity` / `planned_qty` **不存在**（取到 null 不是没数据，是字段名错）。先 `production-plan list --max 5` 看真实 keys 再取数。

---

### `sd` — ibrain-sd-cli (Sales & Distribution)

- npm 包: `@industics/ibrain-sd-cli`（已上线 npm.industics.cn）
- 二进制: `ibrain-sd-cli`
- 配置路径: `<workspace>/tenants/<alias>/.ibrain-sd/config.json`（1.0 workspace-scoped；profile 名 = tenant alias，通过 `in3-cli use <alias>` 切）
- API base: `<api_host>/mom/sd`
- Smoke: `ibrain-sd-cli sales-order list --size 1`
- 鉴权: SPA password grant, AES 密文

销售/分销侧（**对客户**），跟 mm（**对供应商**）的采购侧对称。

#### 实体清单

| 实体 | CLI 子命令 | 用途 |
|---|---|---|
| 销售订单 | `sales-order list` / `get <id>` | SO 主实体；`get` 的行项数组挂在 `.products[]`（不是 `.items[]`） |
| 销售订单行项 | `sales-order-item list` | **跨单行项查询**——按 `--material <id>` 反查命中 SO 的**正确入口**（别 fan-out `sales-order get`）。⚠️ **没有 so_id filter**：传 `--so-id` 被静默忽略、返全租户行项（见坑 6） |
| 行项类目 | `so-item-category list` | SO 行项分类字典 |
| 销售合同 | `contract list` / `get <id>` | **客户合同**（注意：跟 mm 的 contract 同名但是供应侧 vs 销售侧） |
| 销售合同行项 | `contract-item list` | 销售合同行项 |
| 合同类目 | `contract-category list` | 销售合同分类字典 |
| 报价单 | `quotation list` / `get <id>` | 对客户报价（跟 mm 的 quotation 是供应商报价，方向相反） |
| 出货单/送货单 | `delivery-receipt list` / `get <id>` | 出货主单据 |
| 出货行项 | `delivery-receipt-item list` | 出货行项 |
| 出货类型 | `delivery-receipt-type list` | 出货单类型字典 |
| 出货分组号 | `delivery-group-no list` | 出货批次/分组号 |
| 销售部门 | `sales-dept list` | 销售部门字典 |
| 销售信息记录 | `sd-info-record list` | 客户×物料×销售组织的报价/条件 |

#### 已知坑

**1. 命名对称陷阱**（mm/sd 同名反向）

mm 跟 sd 有几个**同名但方向相反**的实体，跨模块联查时要分清来源：

| 实体名 | mm（采购侧） | sd（销售侧） |
|---|---|---|
| `contract` | 采购合同（甲方=本租户，乙方=供应商） | 销售合同（甲方=本租户，乙方=客户） |
| `quotation` | 供应商给本租户的报价 | 本租户给客户的报价 |
| `info-record` ↔ `sd-info-record` | 供应商×物料×工厂 | 客户×物料×销售组织 |

**2. `from_ordered_at` / `to_ordered_at` 日期 filter 服务端已生效**（sd-cli ≥ 0.2.8；0.1.0 曾后端 400，已修）

```bash
ibrain-sd-cli sales-order list --filter from_ordered_at=2026-05-01 --filter to_ordered_at=2026-05-31 --all
```

doctor 2026-06 实测：5 月窗口返 **27 条 vs 全量 178 条**，服务端真过滤、与客户端 `select(.ordered_at)` 逐条一致。**旧提示「后端 400，需 `--all` + 客户端筛」已过时**——直接用 date filter 即可，不必再拉全表防御。`sales-order-item list` 同样支持 `from_ordered_at` / `to_ordered_at`。（若遇 400，仍用 `jq -e '.error // empty'` 检测错误信封。）

**3. 行项数组：取 `.products[]` 最稳（sd≥0.2.8 起 `.items[]` 也双挂同一组行项）**

`sales-order get <id>` 的响应里，行项历来挂在 `.products[]`。doctor 2026-06 实测 sd 0.2.8：get 视图 **`.items[]` 与 `.products[]` 双挂同一组行项**（各 7 行一致），旧版「按 `.items` 取拿 null 误判空订单」**已不成立**——但取 `.products[]` 仍是最稳写法（跨版本兼容）。

```json
{
  "batch_no": "SDJN.01_SC250014_S",
  "so_id": "e6c6b248...",        ← get 视图带 so_id（list 视图会裁成 null，见坑 4/5）
  "total_amount": 676991.15,     ← get 视图只填 total_amount（未税本币）
  "local_total_amount": null,    ← get 视图 local_* 为 null（含税总额改读 list 视图 header，见坑 4）
  "local_total_tax_amount": null,
  "items":    [ /* 7 行，与 products 同 */ ],
  "products": [ { "material_no": "...", "quantity": 3, "local_total_tax_price": 0 } ]  // 行项金额多数为 0，见坑 4
}
```

**4. SO header 金额：list 视图三字段全填，get 视图只填 `total_amount`（sd≥0.2.8；旧文档「永远 0」已过时）**

doctor 2026-06 实测**两视图填充规则相反**：
- **`sales-order list`**：header `total_amount` / `local_total_amount`（未税本币）/ `local_total_tax_amount`（含税）**三字段全填非 0**（如 391150.44 / 391150.44 / 442000）。
- **`sales-order get <id>`**：**只填 `total_amount`（未税本币）**，`local_total_amount` / `local_total_tax_amount` **为 `null`**——只走 get 想拿含税总额会拿到 null 误判「无金额」。

**含税总额权威口径 = `sales-order list` 视图 header 的 `local_total_tax_amount`**（doctor 实测与 sum(products[].local_total_tax_price) 逐分对齐）。「header 金额永远 0、必须 sum 行项」的旧结论已过时。

仍要注意：
- **list 投影裁主键**：`sales-order list` 的 header 把 `so_id` / `so_no` / `customer_name` 裁成 `null`（要这些字段走 `get <id>`，或用带 `so_id` 的 `sales-order-item list` 行项）。
- **行项金额字段大面积为 0**：`products[].local_total_tax_price` 与 `sales-order-item` 行项金额**多数行返 0**（实测某 SO 7 行仅 2 行非 0；全租户 729 行绝大多数 0）。**按物料/类目拆 SD 销售额时只 sum 行项会系统性少报**——SO 级总额以 list 视图 header `local_total_tax_amount` 为权威；要做物料级拆分须先确认该物料行项的金额字段非 0，否则口径不可靠。

**5. SO 没有 `so_no`，用 `batch_no` 作为人类可读单号**

mm 的 PO 有 `po_no=PO20260418010`，sd 的 SO 的 `so_no` 字段恒为 `null`，业务单号在 `batch_no` 字段（如 `SDJN.01_SC250014_S`）。

**6. 按物料反查 SO 走 `sales-order-item --material`；但该端点没有 `so_id` filter（P0 静默坑）**

`sales-order list` 的 filter_keys 里**没有** material 维度，但 sd 提供独立端点 `sales-order-item list`（后端 `/sales-orders/items/page`），把 SO 行项**平铺成全租户行项视图**，支持 `--material <id>`（=material_id）按物料反查：

```bash
# ✅ 按物料反查：一次 HTTP，命中含该物料的所有行项
ibrain-sd-cli sales-order-item list --material <material-id> --all --max 1000

# ❌ 错误：fan-out 数千张 SO 的 get 看 products[]（慢且容易超时）
```

**⚠️ P0：`sales-order-item list` 的 `__schema` 没有 `so_id` filter_key。** 传 `--so-id <id>` / `--filter so_id=<id>` 会被**后端静默忽略**，返回**全租户行项**——doctor 2026-06 实测：filter `so_id` 后仍 **729 行 / 164 个不同 so_id**（与不加完全一致）。**agent 若信此 filter 直接 sum/列举，会把别单物料算进目标 SO，严重错答。**（ibrain-sd-cli **≥ 0.2.9 已在 stderr 输出 `[SD-SOI-1]` WARN** 提醒——本次 doctor 审计修复；旧版无 WARN、纯静默。）按指定 SO 取行项只有两条可靠路径：
- `sales-order get <so_id>` 读 `.products[]`（单单精确）；或
- `sales-order-item list --all --max N` 后客户端 `jq 'select(.so_id=="<id>")'`（批量时）。

跨模块组装"按物料反查"时的统一原则：

| 反查目标 | 走哪个端点 |
|---|---|
| 含此物料的销售订单 | sd `sales-order-item list --material <id>` |
| 含此物料的采购订单 | mm `purchase-order list --filter material_ids=<id>`（命中后还要 `get` 拿行项做类目归集） |
| 含此物料的合同 | mm/sd `contract-item list` 走类似套路（待验证） |
| 含此物料的库存 | wm `stock bin --material-id <id>` |
| 含此物料的排产 | pp `production-plan list --filter materialIds=<id>`（camelCase） |

**7. SO 行项的 material_id 可能是孤儿**（指向 md 里不存在的 id）

实测某些 sd SO 的 `products[].material_id` 在 `in-mom-md-cli material get <id>` 时返回**全 null**——说明 sd 的 sales-order item 表没强制外键到 md，可能是历史脏数据或测试数据。跨模块 join 之前最好先 `md material get` 验证一遍 material 还在，否则会把"物料已删/不存在"误判成"该物料无 SO/PO"。

—

### `cr` — in-mom-cr-cli (Customer Relations / 现场服务 + 商机)

- npm 包: `@industics/in-mom-cr-cli`（已上线 npm.industics.cn）
- 二进制: `in-mom-cr-cli`
- 配置路径: `<workspace>/tenants/<alias>/.in-mom-cr/config.json`（1.0 workspace-scoped；profile 名 = tenant alias，通过 `in3-cli use <alias>` 切）
- API base: `<api_host>/mom/cr`
- Smoke: `in-mom-cr-cli work-log-category list`（字典，最轻量）
- 鉴权: SPA password grant + AES 密文（与 mm/wm/sd/md 完全一致）
- 版本基线: 0.1.0（doctor R4 首次评测通过，加权 4.79，0 触雷）

业务承载两块：**FLSC**（现场服务，类似派单/工单/费用/服务人员）+ **SSME**（商机/客户管理，对应 CRM 销售前段）。v1 只读 6 个 entity，写操作 + evaluation/wage/account 见 ADR-0002 的 v2 候选。

#### 实体清单

| 实体 | CLI 子命令 | 用途 |
|---|---|---|
| 服务单 | `service-order list` / `get <id>` | FLSC 核心。**list 是 POST + JSON body**（不是 GET），typed flag 走 `--project-name` / `--account-name` / `--so-name` / `--service-order-sn` / `--from-date` / `--to-date` / `--status` |
| 费用 | `fee list` | 服务费用流水。同样 POST + body。无 `get-by-id` |
| 服务人员 | `service-person list` (全量) / `query --q <text>` (模糊搜) | **list 与 query 是两个独立 verb**——list 无入参拿全量，query 必须带 `--q`。两个 endpoint 都返 raw List（被 CLI 包成 Page shape） |
| 费用类别字典 | `fee-category list` | raw List（despite path `/page`）。字典型 |
| 工作记录类别字典 | `work-log-category list` | raw List。常见 3 条：`ONLY_SER`（仅服务，默认）/ `ONLY_JOUR`（仅路途）/ `JOUR_SER_JOUR`（路途-服务-路途） |
| 商机 | `opp list` / `get <id>` | SSME。**list 是 GET + query**（跟 service-order 不同），typed flag 走 `--opp-no` / `--opp-name` / `--account` / `--sales-mgr` |

filter 风格：**全 snake_case**（uniform，与 wm/sd/pp/md 对齐；pp 是唯一 camelCase 异类）。15+ multi-value key 见 `cli-capability.json`。

#### 已知坑

**1. tenant indx 业务面真空，不是 bug**（C1 caveat / R4 验证）

`indx` 租户 cr 模块开通但**未投入运营**：

| entity | indx 实测 |
|---|---|
| `work-log-category list` | 3 条（reference data，backend seed） |
| `service-person list` / `query` | 0 |
| `fee-category list` | 0 |
| `service-order list`（全时段） | 0 |
| `fee list` | 0 |
| `opp list` | 0 |

只要 base URL / auth 正确，cr endpoint 都返 `200` + `{"items":[]}` 而不是 5xx。agent 拿到 cr empty 时**不应该当 CLI bug 也不应当 filter bug**——优质回答是"该租户 cr 模块字典已部署但业务零启用，需要 onboard 服务人员/费用类别字典 + 录入第一张服务单"。其它模块（mm/wm/md）数据**正常**，可交叉印证。

**2. raw List 三件套不返 `has_next` 字段**

`service-person list` / `fee-category list` / `work-log-category list` 三个 entity 后端返 raw `List<T>`，CLI 包成简化 Page shape：

```json
{"items":[...], "page":0, "total":3}
```

注意：**没有 `has_next` 字段**（service-order/fee/opp 那些走 Spring Page 的 entity 才有 `has_next: boolean`）。agent 不要对这 3 个字典 entity 期待翻页：看到 `total === items.length` 就是全量，不调 `--page 1`。

**3. service-order/fee 是 POST + JSON body，不是 GET**

`service-order list` 和 `fee list` 都走 `POST /page` + `@RequestBody`：

```bash
# service-order
in-mom-cr-cli service-order list --account-name ACME --from-date 2026-05-01 --to-date 2026-05-31
# 等价于 POST /v2/api/tenants/<tid>/flsc/service-orders/page?page=0&size=20
# body: {"account_name":"ACME","start_date":"2026-05-01","end_date":"2026-05-31"}
```

multi-value filter 用 `--filter status=A --filter status=B` 在 body 里会被序列化成 `"status":["A","B"]`（不是逗号串）。

**4. opp list 反过来是 GET + query string**

跟 service-order/fee 不同，`opp list` 是标准 GET：

```bash
in-mom-cr-cli opp list --filter stage_code=NEGOTIATING --filter status=OPEN
# → GET .../ssme/opps/page?stage_code=NEGOTIATING&status=OPEN
```

multi-value 在 URL 里序列化成 `?stage_code=A&stage_code=B`（Spring `@RequestParam List<X>` 接受这套）。

**5. cr backend Jackson 全局 SNAKE_CASE**（与 wm/sd/pp/md 一致，pp 例外）

读源码（`in-mom-cr-service/.../WebConfiguration.java` 设置 `PropertyNamingStrategy.SNAKE_CASE`）+ 真后端 `-vv` 双重验证。所有 filter_keys / response field 都是 snake_case：`project_name_and_contract_no` / `account_name` / `service_order_sn` / `start_date` / `end_date` / `service_areas` / `service_groups` / `total_elements` / `page_number` / `has_content`。

之前 v0.1.0 的早期 ADR 假设过"POST DTO camel + GET param snake 混合"，被 `-vv` smoke 证伪——经验：**判断 backend 命名风格永远先跑一次 `-vv` list 看 response 字段，别只 grep `application.yml`**（很多 IN3 项目用 `WebConfiguration.java` 代码注入 ObjectMapper，grep 配置文件会漏）。

**6. v1 不支持的 entity**（v2 候选，agent 别尝试调）

- `account` / `account-contact`：只在 `/v2/api/private/.../accounts` 暴露，需 client_credentials（password grant 调不到，ADR-0001）
- `evaluation` / `evaluation-tmpl`：后端无 list endpoint（只 invitation create / single-tmpl get）
- `wage` / `overtime`：只有单条 config detail，无 list
- 写操作（create / update / dispatch / abandon）：v1 严格只读

按客户名反查服务单走 `service-order list --account-name <text>`（typed flag）或 `--filter account_name=<text>`，不要尝试 `account get`。

---

### `qm` — ibrain-qm-cli (Quality Management)

- npm 包: `@industics/ibrain-qm-cli`（已上线 npm.industics.cn）
- 二进制: `ibrain-qm-cli`
- 配置路径: `<workspace>/tenants/<alias>/.ibrain-qm/config.json`（1.0 workspace-scoped；profile 名 = tenant alias，通过 `in3-cli use <alias>` 切）
- API base: `<api_host>/mom/qm`
- Smoke: `ibrain-qm-cli inspection-lot list --size 1`（也可走更轻量的 `rule-group list`）
- 鉴权: SPA password grant + AES 密文（与 mm/wm/sd/md/cr 完全一致）
- 版本基线: 0.1.1

检验/品质侧。覆盖 IQC（来料）/ IPQC（过程）/ OQC（出货）/ MQC（量产）四类检验全流程。

#### 实体清单

| 实体 | CLI 子命令 | 用途 |
|---|---|---|
| 检验批 | `inspection-lot list` / `get <id>` / `list-partials` / `check-and-next` | qm 的**主入口**。一批待检物料/工单产出 = 一个 lot。23 filter，含 `check_type_codes`（multi: iqc/ipqc/oqc/mqc）/ `material_id` / `supplier_id` / `origin_type` (po/mo/so) / `start_delivery_date` / `end_delivery_date` |
| 检验单 | `inspection-order list` / `get <id>` / `list-by-lot` / `list-basic-info` / `list-unqualified-items` / `get-belong-info` / `get-reject-order-id` | 检验批的执行子单（一个 lot 可拆多个 inspection-order）。29 filter，最常用 `inspection_lot_id` / `qualified` (bool) / `report_generate` / `external_ref_no` |
| 检查表 | `check-sheet list` / `get <id>` / `get-by-no` / `list-items` / `search-by-lot` | 检验项目模板（哪些指标 + 公差）。`get-by-no` 按 check_sheet_no 查；`search-by-lot` 按 inspection_lot 反查模板 |
| 检验规则组 | `rule-group list` / `get <id>` / `get-all` / `list-options` | 物料/检验类型级的规则配置；字典型，最轻量 smoke 入口 |
| 拒收单 (NCR) | `reject-order list` / `get <id>` / `list-by-lot` / `list-nonqualified-types` | 不合格品流转单。28 filter，含 `material_id` / `supplier_id` / `nonqualified_type_codes`（multi）/ `defect_codes`（multi）/ `origin_no` |

#### 常用 filter（多 multi-value）

```bash
ibrain-qm-cli __schema | jq '.commands."inspection-lot".list.filter_keys'
```

跨模块联查的高频组合：
- **按物料反查检验状态**：`inspection-lot list --filter material_id=<mid> --filter start_delivery_date=2026-05-01`
- **按供应商反查 NCR**：`reject-order list --filter supplier_id=<sid> --filter approval_statuses=APPROVED`
- **按 PO 反查检验情况**：`reject-order list --filter po_id=<po_id>` / `inspection-order list --filter origin_type=PO --filter origin_no=<po_no>`

#### 已知坑

**1. filter_keys 全 snake_case**（与 mm/wm/sd/md/cr 对齐，pp 是 camelCase 异类）

跨模块组装时不要把 mm 的 `material_ids` 习惯改写到 qm；qm 用单数 `material_id`（不 multi），单值即可。`statuses` / `approval_statuses` / `check_type_codes` / `nonqualified_type_codes` / `defect_codes` 是 multi。

**2. inspection-lot 与 inspection-order 是 1:N 关系**

一个 lot 可拆多个 order（不同 check_sheet / 不同检验员）。"查检验通过率"要走 `inspection-order list --filter qualified=true`，**不是 inspection-lot**。lot 状态是流程状态（待检/检中/已检/已闭环），不是结论。

**3. lot 与 order 都有 `origin_type` + `origin_no`，对接 mm/wm/sd/pp**

- `origin_type=PO` + `origin_no=<po_no>` → IQC 来料检验源于哪张采购订单
- `origin_type=MO` → IPQC/MQC 关联到哪张工单
- `origin_type=SO` → OQC 出货检验关联销售订单

跨模块"全链路追溯"模板：`mm purchase-order get <po> → qm inspection-lot list --filter origin_type=PO --filter origin_no=<po_no> → qm reject-order list-by-lot <lot_id>`

**4. config 子命令对 agent 无用**

`config` verb 组（`add-profile` / `current-context` / `encrypt-password` / `list-profiles` / `use-context`）是 CLI 内部 onboarding 接口，1.0 后**统一走 `in3-cli login / use / sync`** 管理，agent 不要直调。

---

### `fn` — ibrain-mom-fn-cli (Financial)

- npm 包: `@industics/ibrain-mom-fn-cli`（已上线 npm.industics.cn）
- 二进制: `ibrain-mom-fn-cli`
- 配置路径: `<workspace>/tenants/<alias>/.ibrain-mom-fn/config.json`（1.0 workspace-scoped；profile 名 = tenant alias，通过 `in3-cli use <alias>` 切）
- API base: `<api_host>/mom/fn`
- Smoke: `ibrain-mom-fn-cli company-code list`（字典型，最轻量）
- 鉴权: SPA password grant + AES 密文
- 版本基线: 0.1.1

财务侧只读视图。v1 覆盖**会计期间 + 公司代码 + 发票 + 收付款单**四类核心实体，**不涉及 GL 凭证 / 应收应付明细 / 资产**（v2 候选）。

#### 实体清单

| 实体 | CLI 子命令 | 用途 |
|---|---|---|
| 公司代码 | `company-code list` / `get <id>` | 财务记账实体（一个法人 = 一个 company code）。本租户授权可见的所有公司代码 |
| 会计期间 | `posting-period list` | 当前 fiscal year 的期间划分（月度/季度/自定义）。判"5 月单据是否在开账期"用这个 |
| 发票 | `fapiao list` / `get <id>` | 销项+进项发票流水。21 filter，含 `business_partner_ids`（multi 客户/供应商）/ `fapiao_nums`（multi 票号）/ `from_fapiao_date` / `status_list`（multi 草稿/已开/作废/红字）/ `so_ids` / `contract_ids` / `po_ids` |
| 收付款单 | `payment-receipt list` / `get <id>` | 资金流水。18 filter，含 `document_category_code`（收款/付款/退款）/ `from_posting_date` / `status` / `verification_status`（核销状态）/ `contract_ids` / `so_ids` / `po_contract_ids` / `po_ids` |
| 收付款单据 | `payment-receipt-order list` / `get <id>` | 收付款关联的业务单据（SO 收款单、PO 付款单等）。轻量，4 filter：`account_id` / `ordered_by` / `so_id` / `status` |

#### 跨模块联查高频套路

fn 的 list 端点几乎都暴露了 `so_ids` / `po_ids` / `contract_ids` 这类反向引用 filter，**是跨模块"业务单据 → 财务结算"追溯的标准入口**：

```bash
# 某 SO 收过多少钱（含核销状态；会计期间 id 先由 posting-period list 获取）
ibrain-mom-fn-cli payment-receipt list --module ar --company-code <company_code_id> \
  --filter from_posting_period_id=<from_period_id> --filter to_posting_period_id=<to_period_id> \
  --filter so_ids=<so_id> --filter document_category_code=RECEIPT --all

# 某 PO 开过多少进项票
ibrain-mom-fn-cli fapiao list --module ap --company-code <company_code_id> \
  --filter po_ids=<po_id> --filter classify=INPUT --all

# 某客户/供应商当月开票总额（business_partner_ids 包含客户和供应商两类）
ibrain-mom-fn-cli fapiao list --module ar --company-code <company_code_id> \
  --filter business_partner_ids=<bp_id> --filter from_fapiao_date=2026-05-01 \
  --filter to_fapiao_date=2026-05-31 --all
```

#### 已知坑

**0. npm 0.1.1 的 FN 双轨接口不要用于全量分析**

production 使用的公司代码请求头是 `fncc`，不是旧设计中的 `companyCode`；真实端点也不是旧的
`/apar/company-codes/*`。本 skill 自带 SDK 已按 production 在 2026-09-29 校正并完成 live 全量验证。
另外，npm 0.1.1 虽在 schema 中声明 `--all` / `--page` / `--size`，但发票和收付款命令没有把这些
flags 交给分页器，只会返回第一页。发布修正版 npm CLI 前，FN 发票/收付款的全量分析必须走
`python3 .../in3_cli.py run` + `IN3().fn.*.list(all=True)`；不要把裸 CLI 第一页当作全量。

**1. 日期 filter 是 date（YYYY-MM-DD），不是 datetime**

跟 mm 对齐，**不是** sd 的 datetime（`YYYY-MM-DDTHH:mm:ss`）。`from_fapiao_date` / `from_posting_date` / `from_document_date` / `from_certificate_date` 全部 date 类型。

**2. `business_partner_ids` 同时含客户和供应商**

fapiao 的 `business_partner_id` 不区分客户/供应商——销项票对客户、进项票对供应商。判别用 `classify`（INPUT/OUTPUT）+ `fapiao_type_code`。

**3. status_list / verification_status_list 是 multi**

票据状态 / 核销状态都 multi。注意 fn 用的是 `_list` 后缀的命名（`status_list` / `verification_status_list`），而其他模块多是 `statuses`。

**4. `posting-period list` 只接 `valuation_region_id` 一个 filter**

会计期间通常按估值区域分（按工厂或公司代码归集），单一 filter 设计就够。返回行项里含 `valuation_region_posting_periods[]` 数组，里面有每个估值区域的开账/关账状态——agent 想知道"5 月期间是否开账"要往这个嵌套数组里 jq。

**5. `payment-receipt-order` ≠ `payment-receipt`**

| 实体 | 是什么 |
|---|---|
| `payment-receipt` | 资金流水主表（一笔实际收/付款）|
| `payment-receipt-order` | 收付款关联到的业务单据明细（一笔收款可能核销 N 张 SO）|

按"某 SO 收款了吗"反查走 `payment-receipt-order list --filter so_id=<so_id>` **更轻**（4 filter），全量金额追溯才走 `payment-receipt`。

---

### `identity` — ibrain-identity-cli (Identity / Auth / Authorization)

- npm 包: `@industics/ibrain-identity-cli`（已上线 npm.industics.cn）
- 二进制: `ibrain-identity-cli`
- 配置路径: `<workspace>/tenants/<alias>/.ibrain-identity/config.json`（1.0 workspace-scoped）
- API base: `<api_host>/mom/bo`
- Smoke: `ibrain-identity-cli roles list --user-id <self>`（查当前登录用户自己的角色；调度器自动从 token 缓存注入 `--user-id`）
- 鉴权: SPA password grant + AES 密文
- 版本基线: 0.1.0

身份认证与权限管理只读视图。用于查询用户、角色、权限、组织、应用、标签、菜单、租户、配置项。调度器的 smoke（最小连通检查）只查询当前用户自己的角色，用于确认 identity 模块可以正常访问。

#### 实体清单

| 实体 | CLI 子命令 | typed_flags | 用途 |
|---|---|---|---|
| 用户 | `users list` / `get <id>` | `--by-username` `--include-profile` `--include-admin` | 用户信息。`--by-username` 按登录名查 |
| 角色 | `roles list` / `get <id>` | `--user-id` `--include-menus` `--include-users` | 角色列表。`--user-id` 查指定用户的角色 |
| 权限 | `privileges list` | `--user-id` `--is-mixed` | 功能权限点 |
| 组织 | `orgs list` / `get <id>` | `--all` `--include-profile` | 组织架构 |
| 应用 | `apps list` / `get <id>` | — | 已注册应用 |
| 标签 | `tags list` / `get <id>` | `--user-id` | 用户标签 |
| 菜单 | `menus list` / `get <id>` | `--user-id` | 菜单权限 |
| 租户 | `tenants list` / `get <id>` | `--by-domain` | 租户信息 |
| 配置项 | `configs list` / `get <id>` | `--app-id` `--only-public` `--all` | 应用配置。支持 `key_name` filter |

#### 已知坑

**1. `users get` 的 `--by-username` 是按登录名查，不是按姓名**

传 `zhangsan`（登录名）而不是 `张三`（显示名）。

**2. `roles list --user-id` 返回的是该用户已分配的角色，不是全部角色**

不带 `--user-id` 时返回租户全部角色定义。

**3. 裸 `roles list`（列全租户角色）需要后台管理员权限，普通账号会被后端以 404 拒绝**

`roles list`（不带 `--user-id`）= 列全租户所有角色定义，需后台管理员（如 `IN3_SYS_ROLE_BO`）权限；普通账号调用后端返回 `{"error":{"type":"NOT_FOUND","message":"roles list failed","http_status":404}}`（设计上本该 403）。因此 `in3-cli` 的 identity smoke 自动注入 `--user-id <self>`（查自己角色，每个登录用户都有权），而不是裸 `roles list`。

---

## 跨模块 material 字段路径速查（R4 P1 沉淀）

跨模块组装时（"按物料反查全链"），各 CLI 的 material 字段命名 + 路径**不一致**，jq path 容易写错。一张表一次对清：

| 模块 / entity | list 视图行项里 material 路径 | get 视图（带 items/products） material 路径 | 备注 |
|---|---|---|---|
| **mm** `purchase-order` | `items[].material.material_no` | `items[].material.material_no` | mm 行项 material 是**嵌套对象**（material.id / material.material_no / material.material_category）|
| **mm** `purchase-requirement` | `items[].material_no`（顶层）| `items[].material_no` | 跟 PO 不一致（PR 是顶层） |
| **sd** `sales-order` | n/a（list 不返行项）| `products[].material_no` + `products[].material_id` | 行项取 **`products[]` 最稳**；sd≥0.2.8 起 `items[]` 也双挂同组行项（S18）|
| **sd** `sales-order-item` | `material_no`（顶层） | n/a | 按物料反查 SO 的**正确入口**（S20）|
| **wm** `stock` (material view) | `material_no` / `material_id`（顶层） | n/a | 按物料聚合的库存视图 |
| **wm** `stock` (bin view) | `material_no` / `material_id`（顶层） | n/a | 按货位+物料的库存明细 |
| **wm** `material-doc` | `items[].material_id`（行项数组）| `items[].material_id` | 物料凭证（收发记录）|
| **pp** `production-plan` | n/a（行项见 record） | `items[].material_no`（顶层于行项内）| pp 字段普遍 camelCase（P11），但 material 字段无差 |
| **pp** `production-plan-record` | `material_no`（顶层）| n/a | 按物料反查排产用这个 |
| **md** `material` | `material_no` / `id`（顶层） | 同 | 物料主数据本体 |
| **cr** `service-order` | 没有 material 维度 | items 暂未深挖 | cr 业务核心是"服务/客户"，不是物料供应链 |

jq 写法对照（按"按 mid 查所有视图"统一）：

```bash
# mm PO 行项物料
ibrain-mm-cli purchase-order get $PO_ID | jq '.items[] | {mid: .material.id, mno: .material.material_no}'

# sd SO 行项物料（注意是 products 不是 items）
ibrain-sd-cli sales-order get $SO_ID | jq '.products[] | {mid: .material_id, mno: .material_no}'

# 按物料反查 sd 行项（不要 fan-out get）
ibrain-sd-cli sales-order-item list --material $MID --all --max 1000 | jq '.items[] | {so_id, material_no}'

# wm 库存（顶层）—— 数量字段是 total_quantity（主）/ positive_total_quantity（扣负数后），不是 available_quantity（since 2026-05-19, R6 修正）
ibrain-wm-cli stock bin --material-id $MID | jq '.items[] | {bin: .storage_bin, mno: .material_no, total: .total_quantity, positive: .positive_total_quantity}'

# pp 排产行项
ibrain-pp-cli production-plan-record list --filter materialId=$MID | jq '.items[] | {plan_id, material_no, quantity}'
```

**核对原则**：跨模块写联查脚本前先在每个 CLI 单跑一行 `... list --size 1 | jq '.items[0] | keys'` 拿真实字段集，比记忆中"应该叫什么"靠谱。这张表是 R4 doctor 评测沉淀，会随 CLI 版本演进失维，**真有疑问以 `__schema` 为准**（每个 entity 的 `item_fields` 段标了行项实际字段路径）。

—

## 实体到模块的快速 dispatch

| 用户问 | 走 | 备注 |
|---|---|---|
| 采购订单/PR/采购合同/RFQ/供应商/BOM/ECN/采购侧报价 | **mm** | ✅ |
| 仓库/货位/库存/盘点/物料凭证/调拨/检验/装配/领料/收发类别 | **wm** | ✅ |
| 物料/物料类目/工厂/计量单位/币种/汇率/客户/销售组织/产品层级 | **md** | ✅ |
| 销售订单/销售合同/客户报价/出货单/销售信息记录/销售部门 | **sd** | ✅ |
| 生产计划/MRP/需求供应/BOM 展开树/MRP 规则/配套模板 | **pp** | ✅ |
| 现场服务单/派单/服务费用/服务记录/服务人员/工作记录类别 / 商机 / 客户接洽 | **cr** | ✅（v0.1.0 仅只读，account/evaluation/wage 待 v2） |
| 检验批 / 检验单 / 检查表 / 规则组 / 拒收单 / NCR / 来料/过程/出货品检 | **qm** | ✅ |
| 公司代码 / 会计期间 / 发票 / 收付款 / 财务结算追溯 | **fn** | ✅（v0.1.1 仅只读，GL 凭证/明细 待 v2） |
| 用户/角色/权限/组织/应用/标签/菜单/租户/配置 | **identity** | ✅（v0.1.0 只读身份数据查询） |
| GL 凭证 / 应收应付明细 / 资产 / HR / 工资 等 | — | 暂无 CLI，走 SPA / 直 API |
