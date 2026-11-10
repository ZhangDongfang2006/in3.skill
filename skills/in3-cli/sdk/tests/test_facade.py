"""IN3 门面最小接线单测：import in3_client → in3.md.currency.list() 直跑（story 8）。

完整 df/join/sole_source 是 issue #7；本片只验 md.currency 经门面可达且共享一个 Session。
"""
from dataclasses import dataclass, field

import in3_client
from in3_client.config import Credentials


@dataclass
class FakeResponse:
    status_code: int
    _json: object = None
    content_type: str = "application/json"
    text: str = ""

    @property
    def headers(self):
        return {"content-type": self.content_type}

    def json(self):
        return self._json


@dataclass
class FakeTransport:
    responses: list
    calls: list = field(default_factory=list)

    def __call__(self, method, url, headers=None, params=None, **kw):
        self.calls.append({"method": method, "url": url, "headers": headers, "params": params})
        return self.responses.pop(0)


_CRED = Credentials(
    api_host="https://apiv3.industics.com/service",
    tenant_domain="indx",
    username="corp:zhuzheng@indx",
    encrypted_password="AESCIPHER==",
    alias="zhuzheng",
)
_TOKEN = {"access_token": "jwt", "tenant_id": "10030", "tenant_domain": "indx", "user_id": "u-42"}


def test_in3_exposes_md_currency_and_runs_list():
    auth_tr = FakeTransport([FakeResponse(200, _TOKEN)])
    data_tr = FakeTransport([FakeResponse(200, {"content": [{"currency_code": "CNY"}], "last": True})])
    in3 = in3_client.IN3(cred=_CRED, transport=data_tr, auth_transport=auth_tr)
    page = in3.md.currency.list()
    assert [it["currency_code"] for it in page.items] == ["CNY"]


def test_in3_shares_single_session():
    auth_tr = FakeTransport([FakeResponse(200, _TOKEN)])
    data_tr = FakeTransport([
        FakeResponse(200, {"content": [{"currency_code": "CNY"}], "last": True}),
        FakeResponse(200, {"content": [{"currency_code": "USD"}], "last": True}),
    ])
    in3 = in3_client.IN3(cred=_CRED, transport=data_tr, auth_transport=auth_tr)
    in3.md.currency.list()
    in3.md.currency.list()
    # 两次 list 共享一个 Session → token 只换一次
    assert len(auth_tr.calls) == 1


# ============================================================
# Wave 1 装配收口：29 个 M1/M2 实体经门面可达 + 类型正确 + list-only 忠实不假装 get
# ============================================================
from in3_client.entities import md as _md  # noqa: E402
from in3_client.entities import mm as _mm  # noqa: E402
from in3_client.entities import sd as _sd  # noqa: E402
from in3_client.entities import wm as _wm  # noqa: E402
from in3_client.entities import cr as _cr  # noqa: E402
from in3_client.entities import fn as _fn  # noqa: E402
from in3_client.entities import pp as _pp  # noqa: E402
from in3_client.entities import qm as _qm  # noqa: E402


def _make_in3():
    auth_tr = FakeTransport([FakeResponse(200, _TOKEN)])
    # currency-list response 备给 sd 懒入口（首次访问 in3.sd 触发 currency_index → md.currency.list）。
    data_tr = FakeTransport([FakeResponse(200, {"content": [{"currency_code": "CNY"}], "last": True})])
    return in3_client.IN3(cred=_CRED, transport=data_tr, auth_transport=auth_tr)


# (accessor 路径, 期望类型, 是否 list-only=断言 not hasattr .get)
# Wave 1 行保持 3 元组（list_only）；Wave 2 get-only 实体用第 4 元组 no_list 标注（默认 False）。
_ACCESSOR_TYPES = [
    # md M1 simple-list-get
    ("md.plant", _md.PlantEntity, True),
    ("md.measure_unit", _md.MeasureUnitEntity, False),
    ("md.account", _md.AccountEntity, False),
    ("md.account_contact", _md.AccountContactEntity, True),
    ("md.sales_organization", _md.SalesOrganizationEntity, True),
    # md M2 bare-array
    ("md.company_code", _md.CompanyCodeEntity, False),
    ("md.material_category", _md.MaterialCategoryEntity, True),
    ("md.exchange_rate", _md.ExchangeRateEntity, True),
    ("md.product_level", _md.ProductLevelEntity, True),
    # mm M1 simple-list-get
    ("mm.info_record", _mm.InfoRecordEntity, False),
    ("mm.rfq", _mm.RfqEntity, False),
    # mm M2 bare-array
    ("mm.bom", _mm.BomEntity, False),
    ("mm.currency", _mm.CurrencyEntity, False),
    # sd M1 simple-list-get（懒入口）
    ("sd.sales_dept", _sd.SalesDeptEntity, False),
    ("sd.contract_category", _sd.ContractCategoryEntity, False),
    ("sd.so_item_category", _sd.SoItemCategoryEntity, False),
    ("sd.delivery_group_no", _sd.DeliveryGroupNoEntity, False),
    ("sd.sd_info_record", _sd.SdInfoRecordEntity, False),
    ("sd.delivery_receipt_type", _sd.DeliveryReceiptTypeEntity, False),
    # sd M2 list-only
    ("sd.contract_item", _sd.ContractItemEntity, True),
    # wm M2 bare-array list-only
    ("wm.move_type", _wm.MoveTypeEntity, True),
    ("wm.rd_category", _wm.RdCategoryEntity, True),
    # cr M2 subset
    ("cr.service_person", _cr.ServicePersonEntity, True),
    ("cr.fee_category", _cr.FeeCategoryEntity, True),
    ("cr.work_log_category", _cr.WorkLogCategoryEntity, True),
    # fn M2 subset
    ("fn.company_code", _fn.CompanyCodeEntity, False),
    ("fn.posting_period", _fn.PostingPeriodEntity, True),
    # pp M2 subset
    ("pp.mrp_history", _pp.MrpHistoryEntity, False),
    ("pp.mrp_rule", _pp.MrpRuleEntity, True),
    # ---- Wave 2 M3 业务单据（15 实体）：经门面可达 + 类型 + get/list-only 诚实 ----
    # mm M3 business-docs（皆 list+get）
    ("mm.contract", _mm.ContractEntity, False),
    ("mm.purchase_requirement", _mm.PurchaseRequirementEntity, False),
    ("mm.source_list", _mm.SourceListEntity, False),
    ("mm.ecn", _mm.EcnEntity, False),
    ("mm.quotation", _mm.QuotationEntity, False),
    # sd M3 business-docs（sales_order/contract/quotation 含币种 → 懒入口注入 currency_index；皆 list+get）
    ("sd.sales_order", _sd.SalesOrderEntity, False),
    ("sd.contract", _sd.ContractEntity, False),
    ("sd.quotation", _sd.QuotationEntity, False),
    # delivery_receipt_item：list-only（无 get）
    ("sd.delivery_receipt_item", _sd.DeliveryReceiptItemEntity, True),
    # pp M3 business-docs
    ("pp.production_plan", _pp.ProductionPlanEntity, False),
    ("pp.demand_supply", _pp.DemandSupplyEntity, False),
    ("pp.sales_order", _pp.SalesOrderEntity, False),
    # bom_tree：get-only（有 get、无 list）→ list_only=False（get 在场）；not hasattr list 由专测断言
    ("pp.bom_tree", _pp.BomTreeEntity, False),
    ("pp.production_plan_record", _pp.ProductionPlanRecordEntity, False),
    ("pp.kitting_template", _pp.KittingTemplateEntity, False),
    # ---- Wave 3a M4/M5 装配收口（10 实体）：经门面可达 + 类型 + get/list-only 诚实 ----
    # fn M4 双轨 apar 单据（module=ar|ap 分叉；皆 list+get → list_only=False）
    ("fn.payment_receipt", _fn.PaymentReceiptEntity, False),
    ("fn.fapiao", _fn.FapiaoEntity, False),
    # qm M4 质量检验（新 _QmNamespace，5 实体皆 list+get → list_only=False；富 verb 由专测/parity 覆盖）
    ("qm.rule_group", _qm.RuleGroupEntity, False),
    ("qm.check_sheet", _qm.CheckSheetEntity, False),
    ("qm.reject_order", _qm.RejectOrderEntity, False),
    ("qm.inspection_lot", _qm.InspectionLotEntity, False),
    ("qm.inspection_order", _qm.InspectionOrderEntity, False),
    # cr M5（opp/service_order 皆 list+get → False；fee 是 list-only 无 get → True）
    ("cr.opp", _cr.OppEntity, False),
    ("cr.service_order", _cr.ServiceOrderEntity, False),
    ("cr.fee", _cr.FeeEntity, True),
    # ---- Wave 3b M6 wm 最重模块收口（15 实体）：经门面可达 + 类型 + get/list-only 诚实 ----
    # 批 A · simple 5
    ("wm.storage_location", _wm.StorageLocationEntity, True),   # list-only（无 /{id} get）
    ("wm.storage_bin", _wm.StorageBinEntity, True),             # list-only（无 /{id} get）
    ("wm.warehouse", _wm.WarehouseEntity, False),              # 标准 list+get
    ("wm.unit", _wm.UnitEntity, False),                        # 库存单元/SN，标准 list+get
    ("wm.requisition", _wm.RequisitionEntity, False),          # 标准 list+get
    # 批 B · custom-verbs（list+get 标准面进表；纯 verb 面由专测断言）
    ("wm.material_doc", _wm.MaterialDocEntity, False),         # list+get（items DEPRECATED 不实现）
    ("wm.trans_order", _wm.TransOrderEntity, False),          # list+get（+ 跨单 items 无 id）
    ("wm.warehouse_request", _wm.WarehouseRequestEntity, False),  # list+get（+ items(id) 明细）
    ("wm.inventory_check_task", _wm.InventoryCheckTaskEntity, False),  # list+get（+ items(id)）
    ("wm.assembly_order", _wm.AssemblyOrderEntity, False),    # list+get（+ disassembly_*）
    ("wm.check_order", _wm.CheckOrderEntity, False),         # list+get（+ details/pending）
    ("wm.sales_order_shipment", _wm.SalesOrderShipmentEntity, False),  # 主单据 list+get（+ lines）
    # wm.mo：list + info(mo_no)/kitting_items(mo_no)——无 get（方法名贴 verb）→ list_only=True
    ("wm.mo", _wm.MoEntity, True),
    # wm.delivery_order：仅 summary(两参必填)——无 list/get → list_only=True（not hasattr get）
    ("wm.delivery_order", _wm.DeliveryOrderEntity, True),
    # wm.wm_config：仅 6 子 verb config 方法——无 list/get → list_only=True（not hasattr get）
    ("wm.wm_config", _wm.WmConfigEntity, True),
]


def _resolve(in3, accessor):
    obj = in3
    for part in accessor.split("."):
        obj = getattr(obj, part)
    return obj


def test_in3_exposes_all_wave1_entities_with_correct_types():
    """29 个 M1/M2 实体经 IN3() 门面均可达且类型正确（含 cr/fn/pp 新命名空间 + sd 懒入口扩张）。"""
    in3 = _make_in3()
    for accessor, expected_type, _ in _ACCESSOR_TYPES:
        ent = _resolve(in3, accessor)
        assert isinstance(ent, expected_type), f"{accessor} 类型错: {type(ent)} != {expected_type}"


def test_in3_list_only_entities_have_no_get():
    """list-only 实体经门面诚实不假装 get（照 sales_order_item / sd.contract_item 约定）。"""
    in3 = _make_in3()
    for accessor, _, list_only in _ACCESSOR_TYPES:
        ent = _resolve(in3, accessor)
        if list_only:
            assert not hasattr(ent, "get"), f"{accessor} 不该有 get（list-only 忠实）"
        else:
            assert hasattr(ent, "get"), f"{accessor} 应有 get（simple-list-get / 有 get 的 bare-array）"


def test_in3_new_namespaces_present():
    """cr/qm/pp 命名空间 eager 挂到 IN3.__init__；fn 走懒装配 @property（含币种字段需 currency_index）。

    Wave 3a 新增 _QmNamespace（5 qm 实体 eager 直装，照 _MmNamespace 同构）。
    fn 懒装配（sd companion 模式旁挂归一金额/币种，§6 行 781-809、AC #15）——访问 in3.fn 触发币种字典。
    """
    in3 = _make_in3()
    from in3_client.facade import (  # noqa: PLC0415
        _CrNamespace,
        _FnNamespace,
        _PpNamespace,
        _QmNamespace,
    )

    assert isinstance(in3.cr, _CrNamespace)
    assert isinstance(in3.fn, _FnNamespace)
    assert isinstance(in3.qm, _QmNamespace)
    assert isinstance(in3.pp, _PpNamespace)


def test_in3_qm_namespace_eager_no_currency_index():
    """qm 5 实体 eager 直装（无币种字段、无懒加载需求）；标准 list+get 均在场。

    门面级 currency 懒缓存不被 qm 触发（仍 None，直到 sd 首次访问）。
    """
    in3 = _make_in3()
    for name in ("rule_group", "check_sheet", "reject_order", "inspection_lot", "inspection_order"):
        ent = getattr(in3.qm, name)
        assert hasattr(ent, "list"), f"qm.{name} 应有标准 list"
        assert hasattr(ent, "get"), f"qm.{name} 应有 get"
        assert not hasattr(ent, "_currency_index"), f"qm.{name} 不该挂 currency_index（无币种）"
    assert in3._currency_index is None


def test_in3_fn_twin_apar_and_cr_fee_present():
    """fn.payment_receipt/fapiao（双轨 apar）+ cr.opp/service_order/fee 经门面可达。

    cr.fee 是 price-privileged list-only（无 get），错误天然 fail-loud 由 entity 层保证。
    """
    in3 = _make_in3()
    assert isinstance(in3.fn.payment_receipt, _fn.PaymentReceiptEntity)
    assert isinstance(in3.fn.fapiao, _fn.FapiaoEntity)
    assert isinstance(in3.cr.opp, _cr.OppEntity)
    assert isinstance(in3.cr.service_order, _cr.ServiceOrderEntity)
    assert isinstance(in3.cr.fee, _cr.FeeEntity)
    # fee list-only：忠实不假装 get（区分'真没费用'vs'没权限'靠 list 错误冒泡，非 get）。
    assert not hasattr(in3.cr.fee, "get"), "cr.fee 不该有 get（list-only 忠实）"


def test_in3_sd_lazy_expansion_preserves_currency_index():
    """sd 懒入口扩张后仍保留 currency_index 装配（contract_item / sales_order_item 拿到非空字典）。"""
    in3 = _make_in3()
    # 访问 in3.sd 触发 currency_index() → md.currency.list（FakeTransport 已备 currency 响应）
    assert in3.sd.sales_order_item._currency_index is not None
    assert in3.sd.contract_item._currency_index is not None
    # 同一懒入口共享同一 currency_index 实例（不重复建表）
    assert in3.sd.sales_order_item._currency_index is in3.sd.contract_item._currency_index


def test_in3_fn_is_lazy_and_wires_currency_index():
    """fn 走懒装配（§6 行 781-809、AC #15）：访问前 _currency_index 仍 None；访问 in3.fn 才建表。

    payment_receipt/fapiao 拿到非空 currency_index（含金额/币种字段 → sd companion 旁挂归一）；
    company_code/posting_period（M2，无币种）随 fn 懒入口一起装、不挂 _currency_index。
    """
    in3 = _make_in3()
    assert in3._currency_index is None  # 访问 fn 之前，门面级懒缓存未触发
    pr_idx = in3.fn.payment_receipt._currency_index
    assert pr_idx is not None  # 双轨单据拿到非空币种字典
    assert in3.fn.fapiao._currency_index is pr_idx  # 同一懒入口共享同一实例
    assert in3._currency_index is not None  # 访问后门面级缓存已建
    # M2 子集随 fn 入口一起装，但无币种字段 → 不挂 _currency_index。
    assert not hasattr(in3.fn.company_code, "_currency_index")
    assert not hasattr(in3.fn.posting_period, "_currency_index")


def test_in3_fn_and_sd_share_same_currency_index():
    """fn 与 sd 懒入口复用门面同一 currency_index（一个 IN3 实例只建一次表，不重复打 md.currency）。"""
    in3 = _make_in3()
    # _make_in3 只备一份 currency 响应 → 若 fn/sd 各建一次表会 IndexError；共享缓存则只消耗一份。
    fn_idx = in3.fn.payment_receipt._currency_index
    sd_idx = in3.sd.sales_order_item._currency_index
    assert fn_idx is sd_idx is in3._currency_index


# ============================================================
# Wave 2 装配收口：15 M3 业务单据经门面可达 + 含币种 sd/pp 懒装配复用 currency_index
#   + get-only(bom_tree) / list-only(delivery_receipt_item) 诚实不假装
# ============================================================
def test_in3_sd_m3_money_entities_share_currency_index():
    """sd.sales_order/contract/quotation 含金额 → 复用 sd 懒入口同一 currency_index（非空、同实例）。"""
    in3 = _make_in3()
    so_idx = in3.sd.sales_order._currency_index
    assert so_idx is not None
    assert in3.sd.contract._currency_index is so_idx
    assert in3.sd.quotation._currency_index is so_idx
    # 与既有 sales_order_item 同一实例（一个懒入口只建一次表）
    assert in3.sd.sales_order_item._currency_index is so_idx


def test_in3_pp_is_eager_without_currency_index():
    """pp 是产量/物料导向（§6 无金额字段）→ eager 直装，production_plan 不挂 currency_index。"""
    in3 = _make_in3()
    # pp eager：访问不触发 currency_index() 网络调用（FakeTransport 的 currency 响应留给 sd 懒入口）。
    assert not hasattr(in3.pp.production_plan, "_currency_index")
    # 门面级 currency 懒缓存未被 pp 触发（仍为 None，直到 sd 首次访问）。
    assert in3._currency_index is None


def test_in3_get_only_entity_has_no_list():
    """pp.bom_tree 是 get-only（bulk POST CSV→多树）：忠实不假装 list（has get、not hasattr list）。"""
    in3 = _make_in3()
    bt = in3.pp.bom_tree
    assert hasattr(bt, "get"), "pp.bom_tree 应有 get（get-only 实体）"
    assert not hasattr(bt, "list"), "pp.bom_tree 不该有 list（get-only 忠实不假装）"


# ============================================================
# Wave 3b 装配收口：15 M6 wm 实体经门面可达（_WmNamespace 纯装配扩张，AC #38）
#   + list-only(storage_location/storage_bin) 不假装 get
#   + 非 id custom-verb 方法名贴 verb（info/kitting_items/summary/disassembly_*/details/pending/lines/items）
#   + wm_config 6 子 verb 全在场 + 只读边界（无 create/update/delete）
# ============================================================
_WM_M6_NAMES = (
    "storage_location",
    "storage_bin",
    "warehouse",
    "unit",
    "requisition",
    "material_doc",
    "trans_order",
    "warehouse_request",
    "inventory_check_task",
    "mo",
    "assembly_order",
    "check_order",
    "sales_order_shipment",
    "delivery_order",
    "wm_config",
)


def test_in3_wm_m6_all_reachable_via_facade():
    """15 个 M6 wm 实体经 _WmNamespace 纯装配扩张均可达（AC #38），且既有 4 实体未被挤掉。"""
    in3 = _make_in3()
    for name in _WM_M6_NAMES:
        assert hasattr(in3.wm, name), f"wm.{name} 应经门面可达（_WmNamespace 装配扩张）"
    # 既有 4 实体仍在场（装配只追加不替换）
    for name in ("available_stock", "stock", "move_type", "rd_category"):
        assert hasattr(in3.wm, name), f"既有 wm.{name} 不该被扩张挤掉"


def test_in3_wm_list_only_entities_have_no_get():
    """storage_location/storage_bin list-only（schema 明写无 /{id} get）→ 忠实不假装 get，但有 list。"""
    in3 = _make_in3()
    for name in ("storage_location", "storage_bin"):
        ent = getattr(in3.wm, name)
        assert hasattr(ent, "list"), f"wm.{name} 应有 list"
        assert not hasattr(ent, "get"), f"wm.{name} 不该有 get（list-only 忠实，schema 无 /{{id}}）"


def test_in3_wm_custom_verb_method_names_present():
    """非 id custom-verb 方法名贴 verb（绝不硬塞 get），逐 entity 断言对应 verb 方法在场。"""
    in3 = _make_in3()
    wm = in3.wm
    # trans_order：跨单 items（无 id）+ 标准 list/get
    assert hasattr(wm.trans_order, "items") and hasattr(wm.trans_order, "get")
    # warehouse_request：items(id) 明细
    assert hasattr(wm.warehouse_request, "items")
    # inventory_check_task：items(id, diffOnly)
    assert hasattr(wm.inventory_check_task, "items")
    # mo：info(mo_no)/kitting_items(mo_no)——无 get（贴 verb）
    assert hasattr(wm.mo, "info") and hasattr(wm.mo, "kitting_items")
    assert not hasattr(wm.mo, "get"), "wm.mo 非 id verb，不该硬塞 get"
    # assembly_order：装配 list/get + 拆解 disassembly_list/disassembly_get
    assert hasattr(wm.assembly_order, "disassembly_list") and hasattr(wm.assembly_order, "disassembly_get")
    # check_order：details(id)/pending()
    assert hasattr(wm.check_order, "details") and hasattr(wm.check_order, "pending")
    # sales_order_shipment：lines(id)
    assert hasattr(wm.sales_order_shipment, "lines")
    # delivery_order：仅 summary（旁路 lookup，无 list/get）
    assert hasattr(wm.delivery_order, "summary")
    assert not hasattr(wm.delivery_order, "list") and not hasattr(wm.delivery_order, "get")
    # material_doc：items DEPRECATED → 不实现
    assert not hasattr(wm.material_doc, "items"), "wm.material_doc.items 标 DEPRECATED，不该实现"


def test_in3_wm_config_six_leaf_verbs_present():
    """wm_config 6 子 verb 全只读查策略：6 方法在场，且无 list/get（仅 leaf config 方法）。"""
    in3 = _make_in3()
    cfg = in3.wm.wm_config
    for verb in (
        "document_configs",
        "document_lot_strategies",
        "movement_lot_strategies",
        "delivery_order_config",
        "delivery_order_creation_config",
        "movement_creation_config",
    ):
        assert hasattr(cfg, verb), f"wm.wm_config.{verb} 应在场（6 子 verb）"
    assert not hasattr(cfg, "list") and not hasattr(cfg, "get"), "wm_config 仅 leaf config，无 list/get"


def test_in3_wm_m6_readonly_no_mutators():
    """只读边界：15 个 M6 wm 实体绝不暴露 create/update/delete/post/put/remove/save（wm_config 名像配置仍只读）。"""
    in3 = _make_in3()
    _mutators = ("create", "update", "delete", "post", "put", "remove", "save")
    for name in _WM_M6_NAMES:
        ent = getattr(in3.wm, name)
        for m in _mutators:
            assert not hasattr(ent, m), f"wm.{name} 不该有写方法 .{m}（只读边界）"
