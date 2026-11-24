"""#3 三 entity（+ md.currency）的实时 parity 硬门禁（@slow，默认不跑）。

对真后端 + 真 CLI 子进程逐位比对业务数字。`pytest -m slow` 触发。
- exact：SDK 与 CLI 记录全字段逐位一致（md.currency / md.material / mm.supplier）。
- subset：sd 非破坏性归一——SDK 在原字段外多旁挂 alpha companion（local_currency 等），
  故比对 CLI 字段 ⊆ SDK 字段且值一致（不比 SDK 多出的 companion）。

范围严格限 v1.x 这批 entity，不扩全量（防 scope creep）。只比业务字段不比 total。

================================================================================
索引比对的三段降级（v1.x parity-arming 脚手）
================================================================================
v1.x 扩张引入大量 **无 top-level id** 的 list-only / 主数据 / 跨单查询实体（货位 / 号段 /
移动类型 / 码表 / tree 主数据 …）。早期 harness 硬编码 it["id"] 建索引——这些实体上要么
KeyError、要么全 None 退化成无效比对。现按每行声明的索引意图三段降级：

  1) **id 优先**：两侧记录都带 "id" → 按 id 建索引，id 集 + 逐条比对（**保持原行为不变**）。
  2) **声明 key**：行 opts 给 `key`（如 "move_type_no" / ("contract_no","item_no")）且两侧记录
     都带该 key → 按该业务键建索引，键集 + 逐条比对（缺 id 但有稳定业务键的主数据/号段）。
  3) **整集合无序比对**：既无 id 也无可用 key（码表 / tree dict / 行项无稳定主键）→
     退化为 set-of-frozenset 无序逐条 exact 比对（mode=subset 时按 CLI 字段子集投影后比）。

每行 opts（可选第 4 元素 dict）：
  - key:        稳定索引键，str 或 tuple[str,...]（复合键）。两侧都有则走第 2 段。
  - set_compare:True → 强制走第 3 段（声明「无稳定主键」，别试 id/key）。
  - sdk_kwargs: dict，合并进 `.list()` 调用（如 mm.bom 的 material_id、md.exchange_rate 三参）。
  - no_size_all:True → 该 entity 的 `.list()` 不接受 all/size（bare-array / tree / filterless），
                 调用时**不**传 all/size（否则 TypeError）。

实际索引时仍以**记录里是否真有该字段**为准（id/key 二段都先探字段在场）——声明只是意图，
拿不到就自动降级，故有凭证后即便真实主键与 §6 文档估值有出入也不会硬炸，只会落到更宽松的段。
"""
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"

# parity 双侧锁同一 tenant：SDK 端 IN3(tenant=_PARITY_TENANT)、CLI 端 exec --tenant _PARITY_TENANT。
# 默认 zhuzheng（提交基线、单侧无回归）；`IN3_PARITY_TENANT=aquaman pytest -m slow` 可对数据更全的
# 租户复跑（如 aquaman 有 sd/qm/wm 业务单据真数据）。两侧用同一变量 → 永不跨租户错比。
_PARITY_TENANT = os.environ.get("IN3_PARITY_TENANT", "zhuzheng")


def _cli_raw(args):
    """绕过 dispatcher 直连 module binary（args[0]=module key, args[1:]=binary 参数）。

    dispatcher 的 price-scrub / price gate 是**客户端策略**（SDK 不复制）——在 price-denied 但
    后端实返含价数据的租户上，dispatcher 路径会把 SDK 正确取到的价格判成 diff。raw 模式直连裸
    binary（同租户凭据、后端原始响应），隔离出「SDK 解析是否正确」与 dispatcher 价格策略无关。
    仅在 `IN3_PARITY_RAW_CLI` 显式开启时走（默认关，正常 run 仍走 dispatcher 全路径）。
    """
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    import in3_cli  # noqa: PLC0415  仅 raw 模式按需 import dispatcher，复用 binary 解析 + tenant env
    ws = in3_cli._load_workspace()
    proc = subprocess.run(
        [str(in3_cli._resolve_binary(ws, args[0])), *args[1:]],
        env=in3_cli._build_env(ws, _PARITY_TENANT),
        capture_output=True, text=True, check=True,
    )
    d = json.loads(proc.stdout)
    return d if isinstance(d, list) else d.get("items", d)


def _cli(args):
    if os.environ.get("IN3_PARITY_RAW_CLI"):
        return _cli_raw(args)
    proc = subprocess.run(
        [sys.executable, "in3_cli.py", "exec", "--tenant", _PARITY_TENANT, *args],
        cwd=str(_SCRIPTS), capture_output=True, text=True, check=True,
    )
    # 兼容两种 CLI 输出形态：带 {items:[...]} 信封 vs 裸顶层数组 [...]（如 wm rd-category）。
    # 裸数组取整个 list；信封取 ["items"]（缺则原对象兜底，与 .get 同义不炸）。
    d = json.loads(proc.stdout)
    # price-denied 租户：dispatcher 对 price-blocked 实体回 PRIVILEGE_DENIED 信封（无 items）。
    # 这不是 SDK/端点问题——该实体在本租户不可 parity，干净 skip（换 price_viewer 租户即可比对），
    # 别让下游 _frozen/索引拿到 error dict 崩成 AttributeError 误报。
    if (isinstance(d, dict) and isinstance(d.get("error"), dict)
            and d["error"].get("type") == "PRIVILEGE_DENIED"):
        pytest.skip(
            f"CLI price-denied on tenant {_PARITY_TENANT!r} "
            f"(price-blocked entity 需 price_viewer 角色租户): {args}")
    return d if isinstance(d, list) else d.get("items", d)


def _resolve(in3, accessor):
    obj = in3
    for part in accessor.split("."):
        obj = getattr(obj, part)
    return obj


def _sdk_items(in3, accessor, *, sdk_kwargs=None, no_size_all=False):
    """accessor 形如 "md.material" → in3.md.material.list(...).items。

    自适应调用形：基础 kwargs 是 all=False/size=20（与 CLI 默认页对齐做 apples-to-apples），
    但很多 v1.x entity 的 .list() 签名**不接受** all/size（bare-array / tree / filterless）——
    `no_size_all=True` 时不传，避免 TypeError。`sdk_kwargs` 合并必填/补全参（material_id 等），
    优先级高于基础 kwargs。最后按签名过滤掉对方不接受的 key（防 unexpected-keyword TypeError）。
    """
    obj = _resolve(in3, accessor)
    kwargs = {} if no_size_all else {"all": False, "size": 20}
    kwargs.update(sdk_kwargs or {})
    try:
        params = inspect.signature(obj.list).parameters
        if not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
            kwargs = {k: v for k, v in kwargs.items() if k in params}
    except (ValueError, TypeError):  # builtin / 无签名 → 原样传，让调用方暴露真实错
        pass
    return obj.list(**kwargs).items


# ---------------------------------------------------------------------------
# 索引比对降级 helper（三段：id → 声明 key → 整集合无序）
# ---------------------------------------------------------------------------
def _key_present(items, fields):
    """fields（str 或 tuple）声明的键是否在**所有**记录里在场（缺一即不可用，降级）。"""
    if not items:
        return False
    fields = (fields,) if isinstance(fields, str) else fields
    return all(all(f in it for f in fields) for it in items)


def _index_by(items, fields):
    fields = (fields,) if isinstance(fields, str) else fields
    if len(fields) == 1:
        return {it[fields[0]]: it for it in items}
    return {tuple(it[f] for f in fields): it for it in items}


def _frozen(rec):
    """记录 → 可哈希 frozenset（值不可哈希时 JSON 串化），供无序集合比对。

    疑似 big-int id 字段先按「JS Number 往返」规整（int→double→int），让 SDK 全精度值与 CLI
    丢精度值塌缩到同一 token——两侧无序集合才不会因 JS 精度损失误判为不同条目（见 _js_equal）。
    """
    out = []
    for k, v in rec.items():
        bi = _as_bigint(v) if (isinstance(k, str) and (k == "id" or k.endswith("_id"))) else None
        if bi is not None:
            v = int(float(bi))  # JS Number 往返规整，CLI 与 SDK 同 id 塌缩到同一 int
        try:
            hash(v)
            out.append((k, v))
        except TypeError:
            out.append((k, json.dumps(v, sort_keys=True, ensure_ascii=False)))
    return frozenset(out)


# ---------------------------------------------------------------------------
# big-int id 字段的 JS 精度容忍（只放宽这类字段，其它字段仍严格 exact）
# ---------------------------------------------------------------------------
# 背景：CLI 用 JS `Number`（IEEE754 双精度，53 bit 尾数）表示 id；后端雪花 id > 2^53 时，
# JS 序列化把超出精度的尾位归零（如 ...617344 → ...617300），而 SDK（Python int）保全精度。
# 这是 **CLI 丢精度、SDK 是对的**，harness 不该判 diff。容忍准则：把两侧值都按「JS Number
# 往返」（int→IEEE754 double）规整后比——两值若映射到**同一个 double**，则它们作为 JS Number
# 不可区分（= 同一逻辑 id 的精度损失），视为相等。真正不同的 id 会落到不同 double，仍判 diff。
_JS_SAFE_INT = 2 ** 53  # JS Number.MAX_SAFE_INTEGER + 1；超过即可能丢精度


def _suspect_bigint_id(field, a, b):
    """该字段是否「疑似 big-int id」——只对这类字段放宽 JS 精度。

    判据（任一即疑似）：字段名以 `_id` 结尾或恰为 `id`；或两侧值都是 > 2^53 的整数/纯数字串。
    """
    if isinstance(field, str) and (field == "id" or field.endswith("_id")):
        return True
    return _as_bigint(a) is not None and _as_bigint(b) is not None


def _as_bigint(v):
    """v 若为 > 2^53 的整数 / 纯数字整串 → 返回该 int；否则 None（不视作 big-int id）。"""
    if isinstance(v, bool):  # bool 是 int 子类，排除
        return None
    if isinstance(v, int):
        return v if abs(v) > _JS_SAFE_INT else None
    if isinstance(v, str):
        s = v[1:] if v[:1] in "+-" else v
        if s.isdigit():
            iv = int(v)
            return iv if abs(iv) > _JS_SAFE_INT else None
    return None


def _js_equal(a, b):
    """两个 big-int id 值在 JS Number 精度下是否等价：int→double 往返后映射到同一 double。"""
    ia, ib = _as_bigint(a), _as_bigint(b)
    if ia is None or ib is None:
        return a == b  # 非 big-int → 退回严格相等
    return float(ia) == float(ib)


def _field_equal(field, a, b):
    """字段级比对：疑似 big-int id 字段容忍 JS 精度损失，其它字段严格 exact。

    递归进入嵌套 dict/list（如 field_values 自定义字段数组）——内层 id/*_id 同样按 JS 精度
    容忍：CLI 的 JS Number 对**嵌套**雪花 id 一样丢尾位精度（…281730→…282000），SDK 全精度
    是对的，不该判 diff。非 id 字段在每一层仍走严格相等，真实差异照常暴露。
    """
    if a == b:
        return True
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_field_equal(k, a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_field_equal(field, x, y) for x, y in zip(a, b))
    if _suspect_bigint_id(field, a, b):
        return _js_equal(a, b)
    return False


# ---------------------------------------------------------------------------
# harness 自测（fast，无网络）：锁住嵌套 big-int 精度容忍 + 防过度放宽
# ---------------------------------------------------------------------------
def test_field_equal_nested_bigint_precision():
    """field_values 嵌套数组里的 id 同样按 JS 精度容忍；非 id 字段真实差异仍判不等。"""
    sdk = [{"id": 8750038170462281730, "field_no": "A", "biz_type": "SD_CONTRACT_HEAD"}]
    cli = [{"id": 8750038170462282000, "field_no": "A", "biz_type": "SD_CONTRACT_HEAD"}]  # JS 丢尾位
    assert _field_equal("field_values", sdk, cli)
    # 嵌套非 id 字段真实差异 → 仍不等（不被递归掩盖）
    cli_bad = [{"id": 8750038170462281730, "field_no": "B", "biz_type": "SD_CONTRACT_HEAD"}]
    assert not _field_equal("field_values", sdk, cli_bad)
    # 长度/键集不同 → 不等
    assert not _field_equal("field_values", sdk, sdk + sdk)
    assert not _field_equal("x", {"a": 1}, {"a": 1, "b": 2})
    # 顶层标量行为不回归
    assert _field_equal("id", 8750038170462281730, 8750038170462282000)  # 仍容忍
    assert not _field_equal("qty", 5, 6)  # 普通字段仍严格


_CASES = [
    # 每行：(accessor, cli_args, mode[, opts])。opts 见模块 docstring。
    # ---- #3 v1 原始四行（有 id，行为不变）----
    ("md.currency", ["md", "currency", "list"], "exact"),
    ("md.material", ["md", "material", "list"], "exact"),
    ("mm.supplier", ["mm", "supplier", "list"], "exact"),
    ("sd.sales_order_item", ["sd", "sales-order-item", "list"], "subset",
     # SOI 是 list-only 行项（后端无 /{id}）；若记录带 id 走 id 段，否则按 (so_no, material_id)
     # 复合业务键索引，再不行整集合无序。
     {"key": ("so_no", "material_id")}),
    # ---- Wave 1 M1/M2 扩张（29 实体）：@slow 本阶段不跑（cli_args/key 来自各模块 §6 文档）----
    # md M1 simple-list-get
    ("md.plant", ["md", "plant", "list"], "exact", {"key": "plant_no"}),  # list-only，§6 主键 plant_no
    ("md.measure_unit", ["md", "measure-unit", "list"], "exact"),  # list+get → 有 id
    ("md.account", ["md", "account", "list"], "exact"),  # list+get → 有 id
    ("md.account_contact", ["md", "account-contact", "list"], "exact",
     {"set_compare": True}),  # list-only，无单一稳定业务键 → 整集合无序
    ("md.sales_organization", ["md", "sales-organization", "list"], "exact",
     {"key": "sales_organization_code"}),  # list-only，§6 主键 sales_organization_code
    # md M2 bare-array
    ("md.company_code", ["md", "company-code", "list"], "exact",
     {"key": "company_code", "no_size_all": True}),  # 裸数组 list(*, filter)，§6 主键 company_code
    ("md.material_category", ["md", "material-category", "list"], "exact",
     {"set_compare": True, "no_size_all": True}),  # 裸 List、list() 无参、无稳定主键 → 整集合无序
    ("md.exchange_rate",
     ["md", "exchange-rate", "list", "--exchange-rate-type", "M", "--from", "USD", "--to", "CNY"],
     "exact",
     # 三必填参（缺则 fail-loud 不打网络）；裸 List 无 all/size、无单一主键 → 整集合无序。
     # 真实币对：rate type=M、USD→CNY 在 aquaman 有 27 条（2026-06-04 live 实测；zhuzheng 汇率表空→
     # 默认 xfail，aquaman 上 parity 验绿）。zhuzheng 之前用占位 STANDARD/USD/CNY 探不到任何数据。
     {"set_compare": True, "no_size_all": True,
      "sdk_kwargs": {"exchange_rate_type": "M",
                     "from_currency_code": "USD",
                     "to_currency_code": "CNY"}}),
    ("md.product_level", ["md", "product-level", "list"], "exact",
     {"set_compare": True, "no_size_all": True}),  # 单 tree root dict、list(*, q, valid) → 整集合无序
    # mm M1 simple-list-get
    ("mm.info_record", ["mm", "info-record", "list"], "exact"),
    ("mm.rfq", ["mm", "rfq", "list"], "exact"),
    # mm M2 bare-array（bom list 必填 --material；占位 token 由 parity 阶段填真实 material_id）
    ("mm.bom", ["mm", "bom", "list", "--material", "7ff44de8156044a592fc6ad64043faca"], "exact",
     # material_id 必填（缺则 fail-loud）；返整棵 BOM 结构（组件行项），无稳定 top-level 主键 → 整集合无序。
     {"set_compare": True,
      "sdk_kwargs": {"material_id": "7ff44de8156044a592fc6ad64043faca"}}),  # parity 真实 material_id（zhuzheng）
    ("mm.currency", ["mm", "currency", "list"], "exact", {"key": "currency_no"}),  # 裸数组，主键 currency_no
    # sd M1 simple-list-get
    ("sd.sales_dept", ["sd", "sales-dept", "list"], "exact"),  # list+get → 有 id
    ("sd.contract_category", ["sd", "contract-category", "list"], "exact"),  # list+get → 有 id
    ("sd.so_item_category", ["sd", "so-item-category", "list"], "exact"),  # list+get → 有 id
    ("sd.delivery_group_no", ["sd", "delivery-group-no", "list"], "exact",
     {"key": "group_no"}),  # 号段，list+get；若无 id 退 group_no
    ("sd.sd_info_record", ["sd", "sd-info-record", "list"], "exact"),  # list+get → 有 id
    ("sd.delivery_receipt_type", ["sd", "delivery-receipt-type", "list"], "exact"),  # list+get → 有 id
    # sd M2 list-only
    ("sd.contract_item", ["sd", "contract-item", "list"], "exact",
     {"key": ("contract_no", "material_id")}),  # 行项 list-only，复合业务键，退化整集合无序
    # wm M2 bare-array list-only
    ("wm.move_type", ["wm", "move-type", "list"], "exact",
     {"key": "move_type_no"}),  # 主数据 list-only，§6 主键 move_type_no
    ("wm.rd_category", ["wm", "rd-category", "list"], "exact",
     {"set_compare": True}),  # 全量无 filter 码表，无声明主键 → 整集合无序
    # cr M2 subset
    ("cr.service_person", ["cr", "service-person", "list"], "exact"),  # 裸 List<TenantUserVO>，用户有 id
    ("cr.fee_category", ["cr", "fee-category", "list"], "exact",
     {"set_compare": True}),  # 裸 List 字典枚举，无声明主键 → 整集合无序
    ("cr.work_log_category", ["cr", "work-log-category", "list"], "exact",
     {"set_compare": True}),  # 裸 List 字典枚举，无声明主键 → 整集合无序
    # fn M2 subset
    ("fn.company_code", ["fn", "company-code", "list"], "exact"),  # 裸 List + get(id) → 有 id
    ("fn.posting_period", ["fn", "posting-period", "list"], "exact"),
    # ↑ 裸 List，§docstring 明记 items[].id 在场（payment_receipt 的 from/to_posting_period_id 来源）→ id 段
    # pp M2 subset
    ("pp.mrp_history", ["pp", "mrp-history", "list"], "exact",
     {"no_size_all": True}),  # flat List + get(id)，list() filterless 无 all/size → 有 id
    ("pp.mrp_rule", ["pp", "mrp-rule", "list"], "exact",
     {"set_compare": True, "no_size_all": True}),  # flat List，list(*, include_items)，主键不明 → 整集合无序
    # ---- Wave 2 M3 业务单据（15 实体）：@slow 本阶段不跑。
    # 仅注册 .list() 能无必填参直跑的简单行；坑层 bespoke 形态见文件末 PARITY-ARMING TODO，不强塞。----
    # mm M3 business-docs（无 companion → exact；POST-body 的 quotation 也无 companion → exact）
    ("mm.contract", ["mm", "contract", "list"], "exact"),
    ("mm.purchase_requirement", ["mm", "purchase-requirement", "list"], "exact"),
    ("mm.source_list", ["mm", "source-list", "list"], "exact"),
    ("mm.ecn", ["mm", "ecn", "list"], "exact"),
    ("mm.quotation", ["mm", "quotation", "list"], "exact"),
    # sd M3 business-docs（含币种 alpha companion → subset：CLI 字段 ⊆ SDK，不比 SDK 多出的 companion）
    ("sd.sales_order", ["sd", "sales-order", "list"], "subset"),
    ("sd.contract", ["sd", "contract", "list"], "subset"),
    ("sd.quotation", ["sd", "quotation", "list"], "subset"),
    # pp M3 business-docs（header 无 companion → exact；production_plan 金额 companion 在 items 层非 header）
    ("pp.production_plan", ["pp", "production-plan", "list"], "exact"),
    ("pp.demand_supply", ["pp", "demand-supply", "list"], "exact"),
    ("pp.sales_order", ["pp", "sales-order", "list"], "exact"),
    ("pp.kitting_template", ["pp", "kitting-template", "list"], "exact"),
    # ---- Wave 3a M4/M5 装配收口（10 实体）：注册可经 list(all=False, size=20) 无必填参直跑的
    # 简单行；坑层 bespoke 形态见文件末 PARITY-ARMING TODO，不强塞 _CASES 简单行。----
    # qm M4（5 实体的标准 .list()——multi-verb 的 get_all/search_by_lot/check_and_next 等见末注记）
    ("qm.rule_group", ["qm", "rule-group", "list"], "exact"),
    ("qm.check_sheet", ["qm", "check-sheet", "list"], "exact"),
    ("qm.reject_order", ["qm", "reject-order", "list"], "exact"),
    ("qm.inspection_lot", ["qm", "inspection-lot", "list"], "exact"),
    ("qm.inspection_order", ["qm", "inspection-order", "list"], "exact"),
    # cr M5（opp GET-query / service_order POST-body 的标准 .list()——无必填参可直跑）
    ("cr.opp", ["cr", "opp", "list"], "exact"),  # GET-query + get(id) → 有 id
    ("cr.service_order", ["cr", "service-order", "list"], "exact"),  # POST-body + get(id) → 有 id
    # cr.fee：price-privileged——has-privilege parity 需 price_viewer 角色 tenant，见末注记；
    # 此处注册 .list() 行，parity 阶段在有权限 tenant 上跑（no-privilege fail-loud 已由桩单测覆盖）。
    ("cr.fee", ["cr", "fee", "list"], "exact"),
    # ---- Wave 3b M6 wm 最重模块（15 实体）：注册 .list(all=False, size=20) 能无必填参直跑的标准 list 行，
    # @slow 本阶段不跑。no-id / list-only（storage_location/storage_bin/mo）已配 stable key，按业务号
    # 索引；custom-verb 子面 / delivery_order summary 两参必填 / wm_config 6 leaf 见末 PARITY-ARMING TODO。
    # wm 全只读、无币种 companion → exact。----
    # 批 A · simple 5（storage_location/storage_bin list-only 无 get → no-id，配业务号 key）
    ("wm.storage_location", ["wm", "storage-location", "list"], "exact",
     {"key": "storage_location_no"}),  # list-only，§6 主键 storage_location_no
    ("wm.storage_bin", ["wm", "storage-bin", "list"], "exact",
     {"key": "storage_bin_no"}),  # list-only，§6 主键 storage_bin_no
    ("wm.warehouse", ["wm", "warehouse", "list"], "exact"),  # list+get → 有 id
    ("wm.unit", ["wm", "unit", "list"], "exact", {"key": "sn"}),  # 库存单元/SN：list 记录无 top-level id，按业务号 sn 索引（aquaman live 实测）
    ("wm.requisition", ["wm", "requisition", "list"], "exact"),  # list+get → 有 id
    # 批 B · custom-verbs：仅注册标准 .list() 行（custom verb bespoke 见末注记）
    ("wm.material_doc", ["wm", "material-doc", "list"], "exact"),  # list+get → 有 id
    ("wm.trans_order", ["wm", "trans-order", "list"], "exact"),  # 单据 list+get → 有 id
    ("wm.warehouse_request", ["wm", "warehouse-request", "list"], "exact"),  # list+get → 有 id
    ("wm.inventory_check_task", ["wm", "inventory-check-task", "list"], "exact"),  # list+get → 有 id
    ("wm.assembly_order", ["wm", "assembly-order", "list"], "exact"),  # list+get → 有 id
    ("wm.check_order", ["wm", "check-order", "list"], "exact"),  # list+get → 有 id
    ("wm.sales_order_shipment", ["wm", "sales-order-shipment", "list"], "exact"),  # list+get → 有 id
    ("wm.mo", ["wm", "mo", "list"], "exact", {"key": "mo_no"}),  # 工单只读视图，按业务号 mo_no 索引
]


# 行规整：补齐缺省 opts，统一成 (accessor, cli_args, mode, opts) 四元组。
def _norm(row):
    accessor, cli_args, mode = row[0], row[1], row[2]
    opts = row[3] if len(row) > 3 else {}
    return accessor, cli_args, mode, opts


_NORM_CASES = [_norm(r) for r in _CASES]

# ---------------------------------------------------------------------------
# parity-arming defer：标 xfail（strict=False）的实体——保留行 + reason，凭证/数据齐时复跑转绿。
# 别删行：xfail 让它们不再算 fail，但仍在参数化集合里跑，一旦后端补权限/数据会 XPASS 提醒收口。
# ---------------------------------------------------------------------------
# (1) cr 6 实体：zhuzheng 无 cr 权限，list() 打 cr 端点直接 401（已 live 验，见 cr.service_person）。
#     2026-06-04 复核：aquaman / guanghui 两独立公司租户**同样 401**——本 workspace 6 个租户
#     无一开通 cr（慧客服）产品。需先有 cr 读权限的租户才能复跑（非 SDK/端点问题）。
_DEFER_CR_NO_PRIVILEGE = {
    "cr.service_person", "cr.fee_category", "cr.work_log_category",
    "cr.service_order", "cr.fee", "cr.opp",
}
# (2) no-data defer：CLI + SDK 两侧均空（zhuzheng 该实体真无数据），撞「空结果无法 parity」
#     断言。端点/索引意图均已对（非 drift），仅缺数据；tenant 上有数据后即可复跑转绿。
#
#     ── 2026-06-04 aquaman live 复核（`IN3_PARITY_TENANT=aquaman pytest -m slow --runxfail`）──
#     aquaman 是另一独立公司租户、业务单据数据更全。用 tenant 旋钮对其复跑后，这 23 个全部分类
#     （**零 SDK bug**，详见 docs/in3-cli-cemcp/PARITY-AQUAMAN-2026-06-04.md）：
#       ✅ 12 已 live 验 SDK 与 CLI 逐位一致（real data）：wm.warehouse_request / wm.requisition /
#          wm.sales_order_shipment / sd.delivery_group_no / sd.delivery_receipt_type / sd.contract /
#          qm.check_sheet / qm.inspection_order / qm.rule_group / qm.inspection_lot /
#          pp.kitting_template / mm.rfq。（仍留 xfail：默认租户 zhuzheng 该实体无数据，非 SDK 欠账。）
#       ✅ 5 price-bearing：**已 full dispatcher-parity 验绿（aquaman）**。先前 weidandan 无 price_viewer
#          时本 workspace 无「有 price_viewer + 有数据」的租户、dispatcher 会 scrub → 当时用 raw 模式
#          （`IN3_PARITY_RAW_CLI=1` 绕 scrub 直连裸 binary）验过 SDK 解析正确；**2026-06-04 weidandan
#          已配 price_viewer 角色后**，dispatcher 不再 scrub → 这 5 个走**标准** dispatcher 路径直接
#          逐位一致：wm.unit / sd.contract_item / sd.sd_info_record / sd.quotation / mm.quotation。
#          复跑：`IN3_PARITY_TENANT=aquaman pytest -m slow --runxfail -k "wm.unit or sd.contract_item
#          or sd.sd_info_record or sd.quotation or mm.quotation"` → 5 passed。（仍留 xfail：默认 zhuzheng
#          这 5 个无数据。`IN3_PARITY_RAW_CLI` 仍保留作通用能力——验 SDK 独立于 dispatcher 价格策略。）
#       ✅ +1 md.exchange_rate：填真实币对后验绿——rate type=**M**、USD→CNY 在 aquaman 有 27 条
#          （占位 STANDARD 探不到任何数据；已把 _CASES 行改成 M/USD/CNY）。zhuzheng 汇率表空→默认仍 xfail。
#       🔴 1 live 数据 churn（SDK 对，仅 last_modified_date 在 SDK/CLI 两次调用间被后端改写 ~1s）：
#          qm.reject_order。属 live parity 固有时序，非 bug，不放宽时间戳比对。
#       🟡 4 端点已核实对后端 controller（2026-06-04 读 ibrain-pp/ibrain-wm 源码，SDK 端点与
#          @RequestMapping/@PostMapping 逐一对上、官方 CLI 返回同样空 → **非 SDK bug**）。裸 list
#          空的真因分两类：
#          · pp.sales_order —— **2026-06-04 复核纠正旧「穷举无数据/id 不通用」误判**。soId 就是 sd SO
#            id（后端 queryMaterialStatisticBySoIds → getInternalSoByIds 查 t_sd_so）；**数据存在**：
#            get(soId) → GET /sales-orders/{soId}/material-view 在 aquaman 真实 SO 普遍有物料分解
#            （live 12/12 各 2-6 行）→ **get 路径 parity 已武装**（test_sales_order_material_view_get_parity_live）。
#            旧穷举全 total=0 的真因：种子误用 production_plan.document_id（origin_type 全是 MO 工单、非 SO
#            id），且只走 list()=POST /so-material-view/page——该路径按 SO 行项 plantId 过滤
#            （ProjectViewService.java:1302），缺正确 plantId 即空。pp.sales_order 仍留本集仅因其 _CASES
#            **list() 行**默认空（filter-gated by plant，非无数据、非 SDK bug）；物料视图 parity 由上述
#            get @slow 覆盖。要 parity list 路径需先拿到 SO 行项真实 plantId。
#          · pp.demand_supply —— filter-gated（必带 historyId+plantId）。后端 t_pp_demand_supply_<tid>
#            仅在 MRP run 算出净需求时 INSERT（MrpCalculatorManager.computeMrp）；zhuzheng 561 个 MRP run
#            × 慧工未来 plant 复跑全 total=0 = 这些 run 未算出净需求（**真工作流空，非 SDK bug、非种子错**）。
#            有「MRP 真算出需求行」的租户后可补 list(filter={historyId,plantId}) bespoke。
#          · 该租户未生成此类交易单据：wm.assembly_order（无装配/拆解单）、wm.check_order（无盘点单）。
#       —— 小计：18/23 live 验绿 + 4 端点经后端核实 + 1 churn(SDK 对)，**23 个全部非 SDK bug**。
#          4 端点 2026-06-04 再核实细分：pp.sales_order=**数据存在**(get 物料视图 parity 已武装；旧
#          「穷举无数据」误判已纠正) / pp.demand_supply=真工作流空(MRP run 未算出净需求) /
#          wm.assembly_order·wm.check_order=该租户未生成此类单据。
_DEFER_NO_DATA = {
    "wm.check_order", "wm.assembly_order", "wm.warehouse_request", "wm.requisition",
    "wm.sales_order_shipment", "wm.unit",
    "sd.delivery_group_no", "sd.sd_info_record", "sd.delivery_receipt_type",
    "sd.contract_item", "sd.contract", "sd.quotation",
    # ↓ 原 _DEFER_CLI_DRIFT 两员（ibrain-sd-cli v0.2.8 修对端点后）：默认 zhuzheng 两侧空（纯无数据，
    #   端点已对），aquaman 上 parity 通过 → 与其余 no-data 同列（详见下方 (3) RESOLVED 注）。
    "sd.sales_dept", "sd.contract_category",
    "qm.check_sheet", "qm.reject_order", "qm.inspection_order", "qm.rule_group",
    "qm.inspection_lot",
    "pp.demand_supply", "pp.sales_order", "pp.kitting_template",
    "mm.rfq", "mm.quotation",
    "md.exchange_rate",
}
# (3) CLI-drift defer —— **RESOLVED 2026-06-04（ibrain-sd-cli v0.2.7 → v0.2.8）。**
#     原状：3 个 sd master-data（contract_category/sales_dept/so_item_category）SDK 已走裸数组端点
#     （live 200 OK），但旧 shipped CLI 仍拼 /<entity>/page → 后端 405、CLI 退出码 4，harness `_cli()`
#     的 check=True 抛 CalledProcessError —— **CLI 的 bug、非 SDK**。
#     修复：ibrain-sd-cli v0.2.8 三命令改走裸 collection GET（http.getList + pagination.runBareList，
#     按 coerce_to_page 语义包 {items,page:0,total}）；workspace 已装 0.2.8、dist 无 /page；
#     cli-capability-snapshot.json sd 已 bump 0.2.8。
#     复核：`IN3_PARITY_TENANT=aquaman pytest -m slow --runxfail -k "contract_category or sales_dept
#     or so_item_category"` → **3 passed**（CLI 修复对三个实体全部正确，非"两侧恰好都空"假象）。
#     收口归类：
#       · so_item_category → 默认 zhuzheng 有 ZTA 真实行（id=8671393499909586944），转**正常 _CASES**
#         （不再 defer；本地复核 `pytest -m slow --runxfail -k so_item_category` 1 passed）。
#       · sales_dept / contract_category → 默认 zhuzheng 两侧空（端点已对、纯无数据），并入上方
#         _DEFER_NO_DATA（与其余 no-data 同列，aquaman 上 parity 通过）。
#     → CLI-drift 类别现已无成员，删除该 defer 集与 _param 对应分支。


def _param(row):
    """把每行包成 pytest.param，对 defer 实体附 xfail(strict=False) mark（保留行 + reason）。"""
    accessor = row[0]
    if accessor in _DEFER_CR_NO_PRIVILEGE:
        marks = pytest.mark.xfail(
            reason="defer: zhuzheng 无 cr 权限，cr 端点 401（需 cr 读权限 tenant 复跑）",
            strict=False,
        )
    elif accessor in _DEFER_NO_DATA:
        marks = pytest.mark.xfail(
            reason="defer: zhuzheng 该实体两侧均空（真无数据，端点/索引意图已对，有数据后复跑）",
            strict=False,
        )
    else:
        marks = ()
    return pytest.param(*row, marks=marks, id=accessor)


_PARAMS = [_param(r) for r in _NORM_CASES]


@pytest.mark.slow
def test_purchase_order_parity_live_with_include_items():
    """mm.purchase_order 基础 list + include_items 对 CLI 逐位一致（含 line item open_qty 兜底）。

    size 对齐到 CLI 默认 20 做 apples-to-apples；记录级全字段（含 items / _open_qty_source）比对。
    """
    import in3_client  # noqa: PLC0415

    in3 = in3_client.IN3(tenant=_PARITY_TENANT)
    sdk = {r["id"]: r for r in in3.mm.purchase_order.list(all=False, size=20, include_items=True).items}

    proc = subprocess.run(
        [sys.executable, "in3_cli.py", "exec", "mm", "purchase-order", "list", "--include-items"],
        cwd=str(_SCRIPTS), capture_output=True, text=True, check=True,
    )
    cli = {r["id"]: r for r in json.loads(proc.stdout)["items"]}

    assert len(sdk) > 0 and set(sdk) == set(cli)
    mismatches = {k for k in sdk if sdk[k] != cli[k]}
    assert not mismatches, f"PO 记录级不一致: {mismatches}"


def _parity_indexed(accessor, mode, sdk_items, cli_items, fields):
    """第 1/2 段：按 id 或声明 key 建索引，键集 + 逐条比对（exact/subset）。"""
    si, ci = _index_by(sdk_items, fields), _index_by(cli_items, fields)
    assert set(si) == set(ci), (
        f"{accessor} 键集不一致（key={fields}）: "
        f"SDK-only={set(si)-set(ci)}, CLI-only={set(ci)-set(si)}"
    )
    if mode == "exact":
        # big-int id 字段容忍 JS 精度（_field_equal）；其它字段仍严格 exact。
        mismatches = {k: {f: (si[k].get(f), ci[k].get(f))
                          for f in set(si[k]) | set(ci[k])
                          if not _field_equal(f, si[k].get(f), ci[k].get(f))}
                      for k in si}
        mismatches = {k: d for k, d in mismatches.items() if d}
        assert not mismatches, f"{accessor} 记录级不一致: {mismatches}"
    else:  # subset：CLI 字段 ⊆ SDK 字段且值一致（big-int id 字段容忍 JS 精度）
        violations = [(k, f, si[k].get(f), v)
                      for k in si for f, v in ci[k].items()
                      if not _field_equal(f, si[k].get(f), v)]
        assert not violations, f"{accessor} subset-parity 违例: {violations[:5]}"


def _parity_setwise(accessor, mode, sdk_items, cli_items):
    """第 3 段：无稳定主键 → set-of-frozenset 无序逐条比对。

    exact：两侧记录集相等。subset：把每条 SDK 记录投影到 CLI 字段域后，CLI 集 ⊆ SDK 投影集
    （SDK 多旁挂的 companion 不参与，与 indexed subset 同义）。
    """
    if mode == "exact":
        sset = {_frozen(r) for r in sdk_items}
        cset = {_frozen(r) for r in cli_items}
        assert sset == cset, (
            f"{accessor} 整集合无序比对不一致: "
            f"SDK-only={len(sset-cset)} 条, CLI-only={len(cset-sset)} 条"
        )
    else:
        cli_fields = set().union(*(c.keys() for c in cli_items)) if cli_items else set()
        sset = {_frozen({k: v for k, v in r.items() if k in cli_fields}) for r in sdk_items}
        cset = {_frozen(r) for r in cli_items}
        assert cset <= sset, (
            f"{accessor} subset 整集合比对违例: CLI-only={len(cset-sset)} 条不在 SDK 投影集内"
        )


@pytest.mark.slow
@pytest.mark.parametrize("accessor,cli_args,mode,opts", _PARAMS)
def test_entity_parity_live(accessor, cli_args, mode, opts):
    import in3_client  # noqa: PLC0415

    in3 = in3_client.IN3(tenant=_PARITY_TENANT)
    sdk_items = _sdk_items(
        in3, accessor,
        sdk_kwargs=opts.get("sdk_kwargs"),
        no_size_all=opts.get("no_size_all", False),
    )
    cli_items = _cli(cli_args)

    assert len(sdk_items) > 0 and len(cli_items) > 0, f"{accessor}: 空结果无法 parity"

    # 三段降级：id → 声明 key → 整集合无序。
    if not opts.get("set_compare") and _key_present(sdk_items, "id") and _key_present(cli_items, "id"):
        _parity_indexed(accessor, mode, sdk_items, cli_items, "id")
    elif (not opts.get("set_compare") and opts.get("key")
          and _key_present(sdk_items, opts["key"]) and _key_present(cli_items, opts["key"])):
        _parity_indexed(accessor, mode, sdk_items, cli_items, opts["key"])
    else:
        _parity_setwise(accessor, mode, sdk_items, cli_items)


@pytest.mark.slow
def test_sales_order_material_view_get_parity_live():
    """pp.sales_order.get(soId) ↔ CLI `pp sales-order get <soId>` 物料视图逐位一致。

    **为何走 get 而非 list**（2026-06-04 live + 后端核实，纠正旧「穷举无数据」误判）：
    pp.sales_order 两条后端路径数据源**相同**（都查 t_sd_so 真实销售订单），但语义不同——
      · list() → POST /sales-orders/so-material-view/page（ProjectViewService.queryMaterialStatisticBySoIds）：
        getMdSalesOrderList 在 ibrain-pp ProjectViewService.java:1302 **按 SO 行项的 plantId 过滤**
        （`line.plantId == 入参 plantId`）。必带与该 SO 行项完全一致的 plantId 才出数；sd SO header
        不暴露该 plant、production_plan 的 plant 又是 MO plant（另一套）→ 不传/传错即空。**filter-gated、
        非无数据、非 SDK bug。**（旧 docstring 的「穷举无数据/id 不通用」已证伪：soId 就是 sd SO id。）
      · get(soId) → GET /sales-orders/{soId}/material-view（queryMaterialStatisticBySo，301 行）：
        **不按 plant 过滤**，返回该 SO 全量物料分解视图。SDK 与 CLI 同端点、同 {id,items} 信封
        （cli/src/commands/sales-order.ts:40-56）→ 理想 parity 靶。

    数据：aquaman 真实 SO 普遍有物料分解（2026-06-04 live 实测 12/12 个 SO 各 2-6 物料行）；
    zhuzheng 的 SO 无物料分解（get 返空）→ 当前租户无合格 SO 时 **skip**（换数据更全租户复跑：
    `IN3_PARITY_TENANT=aquaman pytest -m slow -k sales_order_material_view`）。物料行有稳定 material_id
    主键 → 按 material_id 索引逐字段比对（嵌套 big-int id 容忍 JS 精度，同 _field_equal）。
    """
    import in3_client  # noqa: PLC0415

    in3 = in3_client.IN3(tenant=_PARITY_TENANT)
    # 找一个 get() 返非空物料视图的真实 SO（最多探 15 个，避免在无数据租户上久跑）。
    # 搜索阶段对单个候选的失败（如 zhuzheng 的 SO 不支持 material-view、后端返 400）宽容跳过，
    # 继续试下一个；全部不合格才 skip 整个测试（非断言阶段，吞异常只为选种子）。
    so_id, sdk_items = None, None
    for r in in3.sd.sales_order.list(all=False, size=30).items[:15]:
        sid = r.get("id")
        if not sid:
            continue
        try:
            items = in3.pp.sales_order.get(sid).get("items") or []
        except Exception:  # noqa: BLE001  该 SO 不支持 material-view → 试下一个候选
            continue
        if items:
            so_id, sdk_items = sid, items
            break
    if not so_id:
        pytest.skip(
            f"tenant {_PARITY_TENANT!r} 无带物料分解的 SO（get material-view 空/400）；"
            f"换数据更全租户复跑：IN3_PARITY_TENANT=aquaman")

    cli_items = _cli(["pp", "sales-order", "get", so_id])

    assert len(sdk_items) > 0 and len(cli_items) > 0, f"pp.sales_order.get({so_id}): 空结果无法 parity"
    # 物料视图行无 top-level id、但每物料一行 → 按 material_id 索引；若个别行缺 material_id 则整集合无序兜底。
    if _key_present(sdk_items, "material_id") and _key_present(cli_items, "material_id"):
        _parity_indexed(f"pp.sales_order.get[{so_id}]", "exact", sdk_items, cli_items, "material_id")
    else:
        _parity_setwise(f"pp.sales_order.get[{so_id}]", "exact", sdk_items, cli_items)


# =============================================================================
# PARITY-ARMING TODO（有 zhuzheng 凭证 + live CLI 后逐条落实的 bespoke @slow 清单）
# -----------------------------------------------------------------------------
# 本块登记**不进 _CASES 参数化简单行**的实体/verb —— 它们的 list(all=False, size=20) 调用形
# 不成立（必填位置参 / 多端点分叉 / 富 verb / 无 list-get），或语义需独立断言。不实现，只登记；
# 有凭证后逐条补成 bespoke @slow，绑 tenant=zhuzheng + live CLI。
#
# ---- 覆盖账本（76 个 v1.x entity accessor）----
#   _CASES 参数化简单行：67 个（含本次为 no-id 实体配 stable key 的行）。
#   独立 @slow 专测已在场：mm.purchase_order（本文件 include_items 专测）、
#     wm.available_stock / wm.stock（test_wm_available_stock_live.py / test_wm_stock_live.py）。
#   下列 7 个登记 bespoke（无 list-get / 必填参 / 多端点）：wm.delivery_order、wm.wm_config、
#     fn.payment_receipt、fn.fapiao、pp.bom_tree、pp.production_plan_record、sd.delivery_receipt_item。
#   → 67 + 3 专测 + （7 ⊂ 下列 bespoke）= 76 全覆盖，无遗漏。
#
# ---- Wave 2 M3 bespoke ----
#   - pp.bom_tree           get-only（无 .list）：bulk POST 吃 CSV/list material_ids → 多树。
#                           bespoke：get("<mat1>,<mat2>") 比对 CLI `pp bom-tree get <csv>`。
#   - pp.production_plan_record  list(production_plan_id) 必填位置参（ppId 进 URL 路径段）。
#                           bespoke：先 list production_plan 取一个 ppId，再 list(ppId) 比对 CLI。
#   - sd.delivery_receipt_item   list 三必填参 company/ps_flag/account（缺则 raise，不打网络）。
#                           bespoke：list(source='so', company=.., ps_flag=.., account=..) 比对 CLI
#                           dual-source 两端点；wrapper 形 {items,total,source}（无标准 id 集断言）。
#
# ---- Wave 1 坑层攒下的 parity-arming（@slow 逐条）----
#   - mm.purchase_requirement  bulk-get detail 主键：list 取 PR header，逐 header bulk-get detail
#                           比对 CLI（PR detail 主键钉死后补 detail-级 @slow，header 级已进 _CASES）。
#   - sd.sales_order / sd.contract  include_items 逐 header：list header（已进 _CASES subset），
#                           parity 阶段再对每个 header 拉 include_items 比对 CLI items 层逐位一致。
#
# ---- Wave 3a M4/M5 bespoke ----
#   - fn.payment_receipt     list 必填 module=ar|ap **且** from/to_posting_period_id REQUIRED
#                           （缺任一 client-side fail-loud，不打网络）→ list(all=False, size=20) 无参
#                           调用形不成立。bespoke：先 fn posting-period list 取一个 posting_period_id，
#                           再分别对 module=ar / module=ap 两端点（/receipts vs /payments）
#                           list(module=.., filter={from/to_posting_period_id}) 比对 CLI
#                           `fn payment-receipt list --module ar|ap --filter from_posting_period_id=..
#                           --filter to_posting_period_id=..`；fncc header 经 cred 默认或
#                           --company-code 覆盖，parity 阶段两 module 各跑一遍。
#   - fn.fapiao             list 必填 module=ar|ap（posting_period OPTIONAL，差异于 payment_receipt）
#                           → 无 module 调用形不成立。bespoke：module=ar / module=ap 两端点（/ar vs
#                           /ap，端点段刻意不同于 payment_receipt 的 /receipts /payments）各 list 比对
#                           CLI `fn fapiao list --module ar|ap`；AP 独有 from/to_certificate_date
#                           只透传不校验。
#   - qm.rule_group         multi-verb bespoke（标准 list 已进 _CASES）：get_all(group_ids≥1 必传，
#                           空 fail-loud；repeated query 不 join) / list_options([check_type]) 返
#                           {items} 非分页 → 走 _wrap_items 不走 normalize，无标准 id 集断言。
#                           bespoke：get_all 取 list() 头几条 id 比对 CLI `qm rule-group get-all
#                           --filter group_ids=A --filter group_ids=B`。
#   - qm.check_sheet        bespoke verb：list_items(POST 分页，filter 进 body)/search_by_lot(4 参全
#                           required 缺则 fail-loud)/get vs get_by_no（两路取同一记录返同一对象，#15 AC：
#                           单测已用双 FakeTransport 证不退化，真同源强证明需 @slow live 对真后端）。
#   - qm.reject_order       bespoke verb：get(repair_code multi query scope)/list_by_lot(inspection_lot_id
#                           path-id)/list_nonqualified_types(无参码表)；8 个 multi-filter 在 list 走
#                           repeated query 绝不 join——parity 阶段逐 key 断 not isinstance(v,str)。
#   - qm.inspection_lot     bespoke verb：list_partials(path-id+/partials)/check_and_next(?id= query-id，
#                           断 params['id']==lot_id 且 '/lot_id' not in url，与 get(path-id) 对照)；
#                           双时间体系（date vs datetime ISO 同 list 并存）parity 阶段各给对的格式校正。
#   - qm.inspection_order   7-verb 最重，bespoke：list_by_lot/get_belong_info(project/eqpt 双 bool toggle)/
#                           get_reject_order_id(?inspection_order_id= query-id，返 RejectOrderDetailVO
#                           跨实体类型，断返 reject_order_* 键非 inspection-order)/list_unqualified_items
#                           (POST 非分页，断 query 无 page/size，区别 check_sheet.list_items 的 POST 分页)/
#                           list_basic_info。逐 verb @slow 绑 tenant=zhuzheng 校正。
#   - cr.fee                has-privilege parity 需 price_viewer 角色 tenant（_CASES 已注册 list 行，
#                           延后到测试环境就绪跑）；no-privilege fail-loud（403 PRIVILEGE_DENIED 冒泡，
#                           不吞空 Page）已由桩单测覆盖。
#
# ---- Wave 3b M6 wm bespoke（标准 .list() 行已进 _CASES；AC #40 要求最重 4 个
#   trans_order/inventory_check_task/mo/check_order 优先）----
#   - 全片端点单复数未 live 验：trans-order-items / mos/{mo_no}/info / disassembly-orders /
#                           check-orders/pending / wm-config 6 leaf / delivery-orders/summary 等
#                           多处 custom-verb 子路径单复数为 PLAN 逐字按 §6 写、自标「抓 CLI 确认」。
#                           parity 阶段先 `exec wm <entity> --help` 或 live wm __schema 钉死真实
#                           path/filter_keys，再补 @slow（端点错 → live 即炸，正是 parity 价值）。
#   - wm.trans_order        【AC #40 重点】custom items（无 id = 跨单行项独立查询，端点
#                           /trans-order-items/page，收自己 material_id/lot_name/bin_no filter，不收
#                           entity_id）。bespoke：items(filter={material_id=..}) 比对 CLI
#                           `wm trans-order items --material-id ..`；与 warehouse_request.items(id)
#                           语义相反，逐 verb 至少一条 @slow 绑 tenant=zhuzheng。
#   - wm.warehouse_request   items(id) = 该申请明细行（端点 .../<id>/items/page，收 entity_id）。
#                           bespoke：先 list 取一个 request id，再 items(id) 比对 CLI
#                           `wm warehouse-request items <id>`。
#   - wm.inventory_check_task【AC #40 重点】get(include_items/is_blind_pda) + items(id, diffOnly)。
#                           ⚠️ camelCase 坑：items 入参 include_diff_only(snake) → query key diffOnly
#                           (驼峰)——parity 阶段断 query 实发 diffOnly 非 diff_only/include_diff_only。
#                           时间 filter ISO date（非 datetime）格式校正。bespoke：list 取 task id，
#                           items(id, include_diff_only=True) 比对 CLI `... items <id> --include-diff-only`。
#   - wm.mo                 【AC #40 重点】info(mo_no)/kitting_items(mo_no)——按 mo_no（业务号非 id），
#                           方法名贴 verb 无 get（标准 list 已进 _CASES，按 mo_no key 索引）。bespoke：
#                           list 取 mo_no，info(mo_no) 比对 CLI `wm mo info <mo_no>`、
#                           kitting_items(mo_no) 比对 `wm mo kitting-items <mo_no>`。
#                           pp_plan_*_date ISO datetime；端点单复数 /mos/{mo_no}/info 抓 CLI 钉死。
#   - wm.check_order        【AC #40 重点】details(id)=单据明细、pending()=独立待检列表（非某单明细，
#                           端点 .../check-orders/pending）。check_at_* ISO date（非 datetime）；
#                           order_type/status 多选逗号。bespoke：list 取 check_order id，details(id)
#                           比对 CLI `... details <id>`；pending() 比对 `... pending`（独立查询）。
#   - wm.assembly_order      装配/拆解双套四方法合一：disassembly_list/disassembly_get 走独立端点
#                           /disassembly-orders[/page|/{id}]。bespoke：disassembly_list() 比对 CLI
#                           `wm assembly-order disassembly-list`、disassembly_get(id) 比对 `... disassembly-get <id>`。
#   - wm.sales_order_shipment lines(id)=发运单行项明细（端点 .../<id>/lines/page）。start/end_date ISO
#                           date（非 datetime）。bespoke：list 取 shipment id，lines(id) 比对 CLI
#                           `wm sales-order-shipment lines <id>`。
#   - wm.material_doc        list+get（Spring Slice total=null → 只比业务字段不比 total，与本 harness
#                           不比 total 一致）；时间 filter ISO datetime（doc_at_*/posting_at_*）。
#                           items 标 DEPRECATED → 不实现、无 parity 面。
#   - wm.delivery_order      【不进 _CASES】仅 summary(delivery_order_name + ref_order_id 两参必填，
#                           缺则本地 fail-loud ValueError 不打网络，无 list/get/id）→ list(all=False)
#                           调用形不成立。bespoke：summary(delivery_order_name=.., ref_order_id=..)
#                           比对 CLI `wm delivery-order summary --delivery-order-name X --ref-order-id Y`；
#                           返 summary 旁路 lookup 无标准 id 集断言。两参缺任一的 client-side fail-loud
#                           已由 wm.py 桩单测覆盖。
#   - wm.wm_config           【不进 _CASES】仅 6 子 verb（document_configs/document_lot_strategies/
#                           movement_lot_strategies/delivery_order_config/delivery_order_creation_config/
#                           movement_creation_config），无 list/get → list(all=False) 调用形不成立。
#                           bespoke：逐 leaf verb 比对 CLI `wm wm-config <leaf> --all`（全只读查策略，
#                           6 端点 path 单复数抓 CLI 钉死）；无标准 id 集断言。
# =============================================================================
