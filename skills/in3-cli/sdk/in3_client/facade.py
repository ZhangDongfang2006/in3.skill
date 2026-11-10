"""IN3 门面：import in3_client → in3.<mod>.<entity>.list() 的入口（A surface）。

v1.x 全覆盖：8 模块 78 entity（md/mm/wm/sd/pp/qm/cr/fn）+ 价值面 df / join / sole_source 均已接。
各模块 entity 见对应 _XxNamespace；成熟度分层（哪些 live-parity 已验、哪些仅单测绿）见 SKILL.md。
一个 IN3 实例共享一个 auth.Session（token 只换一次）和一个 HttpClient。
sd / fn 的币种归一字典懒加载（首次访问 sd/fn 时从 md.currency 取并缓存，共享同一字典），
避免 eager 网络调用——两者均含金额/币种字段，需 currency_index 旁挂 companion 归一。
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from .auth import Session
from .config import Credentials, load_credentials
from .gotchas import build_currency_index
from .http import HttpClient
from . import value as _value
from .entities.md import (
    AccountContactEntity,
    AccountEntity,
    CompanyCodeEntity as MdCompanyCodeEntity,
    CurrencyEntity,
    ExchangeRateEntity,
    MaterialCategoryEntity,
    MaterialEntity,
    MeasureUnitEntity,
    PlantEntity,
    ProductLevelEntity,
    SalesOrganizationEntity,
)
from .entities.mm import (
    BomEntity,
    ContractEntity as MmContractEntity,
    CurrencyEntity as MmCurrencyEntity,
    EcnEntity,
    InfoRecordEntity,
    PurchaseOrderEntity,
    PurchaseRequirementEntity,
    QuotationEntity as MmQuotationEntity,
    RfqEntity,
    SourceListEntity,
    SupplierEntity,
)
from .entities.sd import (
    ContractCategoryEntity,
    ContractEntity as SdContractEntity,
    ContractItemEntity,
    DeliveryGroupNoEntity,
    DeliveryReceiptEntity,
    DeliveryReceiptItemEntity,
    DeliveryReceiptTypeEntity,
    QuotationEntity as SdQuotationEntity,
    SalesDeptEntity,
    SalesOrderEntity as SdSalesOrderEntity,
    SalesOrderItemEntity,
    SdInfoRecordEntity,
    SoItemCategoryEntity,
)
from .entities.wm import (
    AvailableStockEntity,
    MoveTypeEntity,
    RdCategoryEntity,
    StockEntity,
    # #17 M6 wm 最重模块（simple 5 + custom-verbs 10）→ 全 eager（wm 无币种字段，照现有 _WmNamespace）。
    AssemblyOrderEntity,
    CheckOrderEntity,
    DeliveryOrderEntity,
    InventoryCheckTaskEntity,
    MaterialDocEntity,
    MoEntity,
    RequisitionEntity,
    SalesOrderShipmentEntity,
    StorageBinEntity,
    StorageLocationEntity,
    TransOrderEntity,
    UnitEntity,
    WarehouseEntity,
    WarehouseRequestEntity,
    WmConfigEntity,
)
from .entities.cr import (
    FeeCategoryEntity,
    FeeEntity,
    OppEntity,
    ServiceOrderEntity,
    ServicePersonEntity,
    WorkLogCategoryEntity,
)
from .entities.fn import (
    CompanyCodeEntity as FnCompanyCodeEntity,
    FapiaoEntity,
    PaymentReceiptEntity,
    PaymentReceiptOrderEntity,
    PostingPeriodEntity,
)
from .entities.qm import (
    CheckSheetEntity,
    InspectionLotEntity,
    InspectionOrderEntity,
    RejectOrderEntity,
    RuleGroupEntity,
)
from .entities.pp import (
    BomTreeEntity,
    DemandSupplyEntity,
    KittingTemplateEntity,
    MrpHistoryEntity,
    MrpRuleEntity,
    ProductionPlanEntity,
    ProductionPlanRecordEntity,
    SalesOrderEntity as PpSalesOrderEntity,
)


class _MdNamespace:
    def __init__(self, cred, session, http):
        self.currency = CurrencyEntity(cred, session, http)
        self.material = MaterialEntity(cred, session, http)
        # #12 M1 simple-list-get
        self.plant = PlantEntity(cred, session, http)
        self.measure_unit = MeasureUnitEntity(cred, session, http)
        self.account = AccountEntity(cred, session, http)
        self.account_contact = AccountContactEntity(cred, session, http)
        self.sales_organization = SalesOrganizationEntity(cred, session, http)
        # #13 M2 bare-array
        self.company_code = MdCompanyCodeEntity(cred, session, http)
        self.material_category = MaterialCategoryEntity(cred, session, http)
        self.exchange_rate = ExchangeRateEntity(cred, session, http)
        self.product_level = ProductLevelEntity(cred, session, http)


class _MmNamespace:
    def __init__(self, cred, session, http):
        self.supplier = SupplierEntity(cred, session, http)
        self.purchase_order = PurchaseOrderEntity(cred, session, http)
        # #12 M1 simple-list-get
        self.info_record = InfoRecordEntity(cred, session, http)
        self.rfq = RfqEntity(cred, session, http)
        # #13 M2 bare-array
        self.bom = BomEntity(cred, session, http)
        self.currency = MmCurrencyEntity(cred, session, http)
        # #14 M3 business-docs（无币种 companion → eager 直装，无 currency_index 注入）
        self.contract = MmContractEntity(cred, session, http)
        self.purchase_requirement = PurchaseRequirementEntity(cred, session, http)
        self.source_list = SourceListEntity(cred, session, http)
        self.ecn = EcnEntity(cred, session, http)
        self.quotation = MmQuotationEntity(cred, session, http)


class _WmNamespace:
    def __init__(self, cred, session, http):
        self.available_stock = AvailableStockEntity(cred, session, http)
        self.stock = StockEntity(cred, session, http)
        # #13 M2 bare-array list-only
        self.move_type = MoveTypeEntity(cred, session, http)
        self.rd_category = RdCategoryEntity(cred, session, http)
        # #17 M6 wm 最重模块收口（simple 5 + custom-verbs 10）→ 纯装配扩张，全 eager 直装
        # （wm 无币种字段、无懒加载需求，照本 namespace 现有模式；各 entity 继承 PagedEntity，
        #  标准 (cred, session, http) 构造签名，无 currency_index 注入）。
        # 批 A · simple 5
        self.storage_location = StorageLocationEntity(cred, session, http)  # list-only（无 get）
        self.storage_bin = StorageBinEntity(cred, session, http)            # list-only（无 get）
        self.warehouse = WarehouseEntity(cred, session, http)
        self.unit = UnitEntity(cred, session, http)                        # 库存单元/SN（非计量单位）
        self.requisition = RequisitionEntity(cred, session, http)
        # 批 B · custom-verbs 10（方法名贴 verb：items/lines/details/pending/info/kitting_items/
        #   summary/disassembly_*/config 子 verb，绝不硬塞 get）
        self.material_doc = MaterialDocEntity(cred, session, http)
        self.trans_order = TransOrderEntity(cred, session, http)
        self.warehouse_request = WarehouseRequestEntity(cred, session, http)
        self.inventory_check_task = InventoryCheckTaskEntity(cred, session, http)
        self.mo = MoEntity(cred, session, http)                            # 工单只读视图（非 pp 写接口）
        self.assembly_order = AssemblyOrderEntity(cred, session, http)
        self.check_order = CheckOrderEntity(cred, session, http)           # wm 侧只读视图（区别 qm）
        self.sales_order_shipment = SalesOrderShipmentEntity(cred, session, http)  # 主单据
        self.delivery_order = DeliveryOrderEntity(cred, session, http)     # summary 旁路 lookup
        self.wm_config = WmConfigEntity(cred, session, http)               # 全只读查策略


class _CrNamespace:
    def __init__(self, cred, session, http):
        self.service_person = ServicePersonEntity(cred, session, http)
        self.fee_category = FeeCategoryEntity(cred, session, http)
        self.work_log_category = WorkLogCategoryEntity(cred, session, http)
        # #16 M5 非 tenant 路径业务实体（opp /ssme、service_order /flsc、fee /flsc/v3）→ eager 直装
        # （无币种懒加载需求；fee 是 price-privileged，list 错误天然 fail-loud 由 entity 层保证）。
        self.opp = OppEntity(cred, session, http)
        self.service_order = ServiceOrderEntity(cred, session, http)
        self.fee = FeeEntity(cred, session, http)


class _FnNamespace:
    """fn 命名空间：懒装配（首次访问 IN3.fn 时建币种字典）。

    payment_receipt/fapiao 含金额/币种字段（§6 行 781-809），按 sd companion 模式旁挂归一，
    需 currency_index（来自 md.currency）注入——故 fn 整体走懒装配（AC #15 行 35），照 _SdNamespace。
    company_code/posting_period（M2）无币种字段，随 fn 懒入口一起装、不挂 companion（传 index 无害）。
    fncc header 默认值（cred.default_company_code_id）仍由 entity 层 _company_code_headers
    内部读取，无需 facade 透传。
    """

    def __init__(self, cred, session, http, currency_index):
        self.company_code = FnCompanyCodeEntity(cred, session, http)
        self.posting_period = PostingPeriodEntity(cred, session, http)
        # payment_receipt_order：顶层收付款单（无 module 双轨、不发 fncc header）；
        # 金额字段若在场旁挂 companion → 注入 currency_index（缺字段不臆造）。
        self.payment_receipt_order = PaymentReceiptOrderEntity(
            cred, session, http, currency_index=currency_index
        )
        # #15 M4 双轨 apar 单据（module=ar|ap 端点分叉）：含金额/币种字段 → 注入 currency_index
        # 旁挂 alpha companion 归一（懒装配已建表，无 eager 网络调用）。
        self.payment_receipt = PaymentReceiptEntity(cred, session, http, currency_index=currency_index)
        self.fapiao = FapiaoEntity(cred, session, http, currency_index=currency_index)


class _QmNamespace:
    def __init__(self, cred, session, http):
        # #15 M4 质量检验 5 实体（富自定义 verb）→ eager 直装（qm 无币种字段、无懒加载需求），
        # 照 _MmNamespace 同构。tenant-templated 路径，各实体继承 PagedEntity/PostPagedEntity。
        self.rule_group = RuleGroupEntity(cred, session, http)
        self.check_sheet = CheckSheetEntity(cred, session, http)
        self.reject_order = RejectOrderEntity(cred, session, http)
        self.inspection_lot = InspectionLotEntity(cred, session, http)
        self.inspection_order = InspectionOrderEntity(cred, session, http)


class _PpNamespace:
    def __init__(self, cred, session, http):
        self.mrp_history = MrpHistoryEntity(cred, session, http)
        self.mrp_rule = MrpRuleEntity(cred, session, http)
        # production_plan 是产量/物料导向，§6 schema 无金额/币种字段 → eager 直装，无 currency_index 注入。
        self.production_plan = ProductionPlanEntity(cred, session, http)
        self.demand_supply = DemandSupplyEntity(cred, session, http)
        self.sales_order = PpSalesOrderEntity(cred, session, http)
        self.bom_tree = BomTreeEntity(cred, session, http)
        self.production_plan_record = ProductionPlanRecordEntity(cred, session, http)
        self.kitting_template = KittingTemplateEntity(cred, session, http)


class IN3:
    def __init__(
        self,
        tenant: Optional[str] = None,
        workspace: Optional[Path] = None,
        pointer_path: Optional[Path] = None,
        cred: Optional[Credentials] = None,
        transport: Optional[Callable] = None,
        auth_transport: Optional[Callable] = None,
        session: Optional[Session] = None,
    ):
        if cred is None:
            cred = load_credentials(workspace=workspace, alias=tenant, pointer_path=pointer_path)
        self.cred = cred
        if session is not None:
            self.session = session
        elif cred.auth_mode == "token":
            # token 模式（login --paste-token / 浏览器捕获）：用存的 Bearer，不走 password-grant。
            self.session = Session.from_token(
                cred, access_token=cred.access_token, refresh_token=cred.refresh_token,
                tenant_id=cred.tenant_id, tenant_domain=cred.tenant_domain,
                user_id=cred.user_id, transport=auth_transport,
            )
        else:
            self.session = Session(cred, transport=auth_transport)
        self.http = HttpClient(self.session, transport=transport)
        self.md = _MdNamespace(cred, self.session, self.http)
        self.mm = _MmNamespace(cred, self.session, self.http)
        self.wm = _WmNamespace(cred, self.session, self.http)
        # cr/qm/pp 无币种字段 → eager 直装（不需懒加载 currency_index）。
        # fn 含金额/币种字段（payment_receipt/fapiao，§6 行 781-809）→ 懒装配（同 sd），见 fn @property。
        self.cr = _CrNamespace(cred, self.session, self.http)
        self.qm = _QmNamespace(cred, self.session, self.http)
        self.pp = _PpNamespace(cred, self.session, self.http)
        self._currency_index: Optional[dict] = None
        self._sd = None
        self._fn = None

    @classmethod
    def from_token(
        cls,
        api_host: str,
        access_token: str,
        refresh_token: str = "",
        tenant_id: str = "",
        tenant_domain: str = "",
        user_id: str = "",
        alias: str = "captured",
        transport: Optional[Callable] = None,
        auth_transport: Optional[Callable] = None,
    ) -> "IN3":
        """用现成 token（浏览器/devtools 抓的）构造 IN3，不走 password-grant。

        只需 api_host（拼 base_url）+ token 响应里的 access_token/tenant_id/tenant_domain/user_id
        （+ 可选 refresh_token 续期）。username/password 留空（token-paste 不需要）。
        """
        cred = Credentials(api_host=api_host, tenant_domain=tenant_domain or "",
                           username="", encrypted_password="", alias=alias)
        session = Session.from_token(
            cred, access_token=access_token, refresh_token=refresh_token,
            tenant_id=tenant_id, tenant_domain=tenant_domain, user_id=user_id,
            transport=auth_transport,
        )
        return cls(cred=cred, session=session, transport=transport)

    @classmethod
    def from_client_credentials(
        cls,
        api_host: str,
        tenant_domain: str,
        client_id: str,
        client_secret: str,
        alias: str = "agent",
        transport: Optional[Callable] = None,
        auth_transport: Optional[Callable] = None,
    ) -> "IN3":
        """用 AGENT `client_credentials` 机器令牌构造 IN3（无人值守，不需 username/password/浏览器）。

        token 惰性换取（首次用时 mint，24h；401 时无 refresh_token → 回退重新 mint）。
        **tenant_domain 必须是租户域名（如 "indx"），它会作 T-CODE 头**——机器令牌响应不带
        tenant_domain，靠它兜底；填数字 tenant_id 会 404。tenant_id（路径用）来自 token 响应。
        """
        cred = Credentials(api_host=api_host, tenant_domain=tenant_domain,
                           username="", encrypted_password="", alias=alias)
        session = Session(
            cred, transport=auth_transport,
            client_id=client_id, client_secret=client_secret,
            grant_mode="client_credentials",
        )
        return cls(cred=cred, session=session, transport=transport)

    def currency_index(self) -> dict:
        """从 md.currency 建 156↔CNY 归一字典，缓存一次。"""
        if self._currency_index is None:
            self._currency_index = build_currency_index(self.md.currency.list().items)
        return self._currency_index

    # ---- 价值面（#7）----
    def df(self, items):
        """归一 items → pandas DataFrame（缺 pandas 降级返回 items）。"""
        return _value.df(items)

    def join(self, *tables, on: str):
        """多表 left/outer join，孤儿保留并标 _orphan（防"当删→漏算"）。"""
        return _value.join(*tables, on=on)

    def sole_source(self, material_ids: list) -> dict:
        """独家供应风险（三态）：查这批物料的 PO 明细 → 按 material 统计 distinct 供应商。

        1 供应商=独家(风险)、≥2=非独家、0=孤儿（无 PO/供应商记录，不误判独家也不吞）。
        """
        page = self.mm.purchase_order.list(
            filter={"material_ids": list(material_ids)}, include_items=True, all=True
        )
        line_items = [it for po in page.items for it in (po.get("items") or [])]
        return _value.compute_sole_source(line_items, list(material_ids))

    @property
    def sd(self):
        """懒装配 sd 命名空间（首次访问才加载币种字典）。"""
        if self._sd is None:
            self._sd = _SdNamespace(self.cred, self.session, self.http, self.currency_index())
        return self._sd

    @property
    def fn(self):
        """懒装配 fn 命名空间（首次访问才加载币种字典）。

        payment_receipt/fapiao 的金额/币种字段需 currency_index（§6 行 781-809、AC #15 行 35）——
        故 fn 同 sd 走懒装配，首次访问 IN3.fn 才 build/复用 currency_index（与 sd 共享缓存）。
        """
        if self._fn is None:
            self._fn = _FnNamespace(self.cred, self.session, self.http, self.currency_index())
        return self._fn


class _SdNamespace:
    def __init__(self, cred, session, http, currency_index):
        self.sales_order_item = SalesOrderItemEntity(cred, session, http, currency_index=currency_index)
        # #12 M1 simple-list-get（无金额字段，但随 sd 懒入口一起装，保留 currency_index 入口不破坏）
        self.sales_dept = SalesDeptEntity(cred, session, http)
        self.contract_category = ContractCategoryEntity(cred, session, http)
        self.so_item_category = SoItemCategoryEntity(cred, session, http)
        self.delivery_group_no = DeliveryGroupNoEntity(cred, session, http)
        self.sd_info_record = SdInfoRecordEntity(cred, session, http)
        self.delivery_receipt_type = DeliveryReceiptTypeEntity(cred, session, http)
        # delivery_receipt（收货单 header）：simple-list-get，company_id 必填，无金额 companion。
        self.delivery_receipt = DeliveryReceiptEntity(cred, session, http)
        # #13 M2 list-only（行项可带币种 companion → 复用 sd 懒入口的 currency_index）
        self.contract_item = ContractItemEntity(cred, session, http, currency_index=currency_index)
        # #14 M3 business-docs：含金额 entity 复用同一 currency_index（懒入口已建表，无 eager 网络调用）。
        self.sales_order = SdSalesOrderEntity(cred, session, http, currency_index=currency_index)
        self.contract = SdContractEntity(cred, session, http, currency_index=currency_index)
        self.quotation = SdQuotationEntity(cred, session, http, currency_index=currency_index)
        # delivery_receipt_item：list-only，currency_index 形参对齐统一装配签名（当前不挂 companion）。
        self.delivery_receipt_item = DeliveryReceiptItemEntity(
            cred, session, http, currency_index=currency_index
        )
