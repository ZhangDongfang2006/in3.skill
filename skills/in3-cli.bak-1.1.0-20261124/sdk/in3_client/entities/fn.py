"""fn 模块 entity（#13 M2 子集）：company_code / posting_period。

本模块在 SDK 是首批 fn 实体（命名空间装配由收口阶段做，这里只写 entity 类）。

fn 这两实体是 **tenant-templated**（/v2/api/tenants/<tid>/，与 md/mm/wm/sd 同），区别于 cr
的 app-prefix 路径。两者后端均返裸 List（非 Spring Page 信封）→ 一律走 #10 基座的 `_list_bare`
（→ http._request 原值 → coerce_to_page 包 Page），**不**经 envelope.normalize、**不**被
get_json 的 or {} 吞空。

模块级坑（§6 行 733-809 + 750-769）：
- company_code 本身**不发** fncc header——它是 cc 的定义源（NOT under company-codes/*
  的 apar 链路）。本片不注入任何 extra_headers。
- posting_period 字段名陷阱（v0.1.1 QA 修正）：是 `posting_period_name` **不是** period_name；
  顶层 period 无单一 status，状态在嵌套数组 valuation_region_posting_periods[].{enabled,closed,
  current}——SDK 原样穿过裸 List 即可（不展平、不改字段名），parity 钉死这两点。
- posting_period 仅 list、无 get（裸 List /posting-periods/all，忠实不暴露 .get）。
- 只读边界：fn 全部 GET，本片只生成 list/get，无写。
"""
from __future__ import annotations

from typing import Optional

from ..auth import Session
from ..config import Credentials
from ..envelope import Page
from ..http import HttpClient
from ..filters import check_filter_keys
from ..pagination import iterate_all
from .base import PagedEntity
# 复用 sd 的非破坏性币种 companion（`*_currency_no`→`*_currency`，原字段不动）——
# §6 行 791/805 明确 fn 金额/币种字段按 sd companion 模式归一。
from .sd import _attach_currency_companions


class CompanyCodeEntity(PagedEntity):
    """fn.company_code（simple-list-get，裸 List 包 Page）。

    list 返回裸 List → _list_bare 包 Page（total/has_next 不可信由 coerce_to_page 兜：total=len、
    has_next=False、一页到底）；有真 get(id)。自身**不发** fncc header（cc 定义源）。

    filter_keys（§6）：company_code / company_code_name / taxpayer_identification——按 filter
    dict 透传进 query。

    端点（parity 2026-06-03 live 校正）：list = /company-codes/list（GET，裸 List），
      get = /company-codes/{id}（GET）。**不**带 apar/ 前缀（apar 前缀曾 404；CLI
      `fn company-code list` 实端点反查 dist/commands/company-code.js 确认）。与 md.company_code
      同后端（fn / md 两 CLI 共用 /v2/api/tenants/<tid>/company-codes/* 链路）。
    """

    MOD = "fn"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/company-codes/list"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/company-codes/{entity_id}"

    def list(self, *, filter: Optional[dict] = None, size: int = 20, all: bool = True) -> Page:
        # 裸 List 端点：base_params 作 query 透传（端点支持 filter），不走 normalize/分页。
        return self._list_bare(dict(filter or {}), size, all)

    def get(self, entity_id: str) -> dict:
        return self._get(entity_id)


class PostingPeriodEntity(PagedEntity):
    """fn.posting_period（list-only）：裸 List /posting-periods/all，仅 list、无 get。

    字段名回归点（v0.1.1 QA 修正）：`posting_period_name`（非 period_name）；状态在嵌套数组
    `valuation_region_posting_periods[].{enabled,closed,current}`（顶层无单一 status）——SDK 原样
    穿过裸 List，不展平不改名。tenant-level，不发 fncc header。items[].id 是 payment-receipt
    的 from/to_posting_period_id 来源（跨实体链接，本片不自动 join）。忠实不暴露 .get。

    filter_keys（§6 行 761-762）：`valuation_region_id`——按 filter 透传进 query（裸 List 端点
    base_params 即 query）。

    TODO: live fn __schema 复核端点单复数/filter_keys（parity 阶段校正）——
      路径 /posting-periods/all、字段名、及 /posting-periods/all 是否真吃 valuation_region_id
      query 均按 §6 文档写，未 live 验。
    """

    MOD = "fn"

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/posting-periods/all"

    def list(
        self,
        *,
        valuation_region_id: Optional[int] = None,
        filter: Optional[dict] = None,
        size: int = 200,
        all: bool = True,
    ) -> Page:
        # 裸 List 端点：base_params 作 query 透传（§6 行 761 定义 valuation_region_id filter），
        # size/all 仅形状统一不参与翻页。
        params: dict = dict(filter or {})
        if valuation_region_id is not None:
            params["valuation_region_id"] = valuation_region_id  # int 原样透传，不强转 str
        return self._list_bare(params or None, size, all)


# payment_receipt_order（顶层收付款单）后端 filter_keys（§6 行 773）。status 多值（list 透传）。
_PAYMENT_RECEIPT_ORDER_FILTER_KEYS = frozenset({
    "account_id", "ordered_by", "so_id", "status",
})


class PaymentReceiptOrderEntity(PagedEntity):
    """fn.payment_receipt_order：收付款单（顶层业务单据）。simple-list-get（§6 行 770-779，2pt）。

    坑：
      - **不发 fncc header**——NOT under company-codes/* 链路（与 payment_receipt/fapiao 不同，
        无 module 双轨），最接近 mm.supplier 的纯 simple-list-get。
      - Spring Page 响应 → 走标准 _list（GET 分页 + envelope.normalize），**不**走裸 List 的 _list_bare。
      - status 多值（list 透传成 repeated query，量小不触发 chunk/_matched_filter_values）。
      - 金额/币种字段若在场按 sd companion 模式旁挂归一（懒加载 currency_index，缺字段则不臆造）。
    TODO: live fn __schema 复核端点单复数/filter_keys（parity 阶段校正）。
    """

    MOD = "fn"

    def __init__(self, cred: Credentials, session: Session, http: HttpClient,
                 currency_index: Optional[dict] = None):
        super().__init__(cred, session, http)
        self._currency_index = currency_index

    def _list_path(self, tenant_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/payment-receipt-orders/page"

    def _get_path(self, tenant_id: str, entity_id: str) -> str:
        return f"/v2/api/tenants/{tenant_id}/payment-receipt-orders/{entity_id}"

    def _normalize_currency_fields(self, items: list) -> list:
        return _attach_currency_companions(items, self._currency_index)

    def list(self, *, filter: Optional[dict] = None, size: int = 20, all: bool = True) -> Page:
        params: dict = dict(filter or {})
        check_filter_keys("fn.payment_receipt_order", params, _PAYMENT_RECEIPT_ORDER_FILTER_KEYS)
        return self._list(params, size, all, transform=self._normalize_currency_fields)

    def get(self, entity_id: str) -> dict:
        return self._get(entity_id)


# ---------- #15 M4：fn 双轨 apar 单据（module=ar|ap 端点分叉 + fncc header）----------


class PaymentReceiptValidationError(Exception):
    """payment_receipt / fapiao 入参校验失败 —— client-side fail-loud，**绝不打网络**。

    覆盖三类：① module 缺失或非 ar/ap；② payment_receipt 的 from/to_posting_period_id REQUIRED
    缺任一。照 wm.StockValidationError 的 client-side 抛错约定（在发请求前抛，tr.calls 仍为空）。
    """


# module → list 端点段（payment-receipt 与 fapiao 段不同，照 §6 估值，不可互换）。
_PR_LIST_SEG = {"ar": "receipts", "ap": "payments"}
_FAPIAO_LIST_SEG = {"ar": "ar", "ap": "ap"}


def _validate_module(module: Optional[str]) -> str:
    """module 必填且 ∈ {ar, ap}，否则 fail-loud（不打网络）。返回规整后的小写 module。"""
    if not module or module not in ("ar", "ap"):
        raise PaymentReceiptValidationError(
            f"module 必填且须为 'ar' 或 'ap'（收到 {module!r}）—— payment_receipt/fapiao 按 module 分叉端点"
        )
    return module


class _TwinAparEntity:
    """payment_receipt / fapiao 共享的双轨基座：module 分叉端点 + fncc header 注入。

    **不**继承 PagedEntity——其单一 _list_path/_get_path 无法表达 module 双轨。自持 cred/session/http，
    按 module 构造 URL（custom-verbs 风格，照 PurchaseOrderEntity/StockEntity）。fncc header
    经 #11 的 extra_headers 注入：company_code 入参优先，否则取 cred.default_company_code_id；两者皆
    None 则不注入（不发空 header）。**这是 fn 招牌坑**：只有这两个实体发 header，company_code/
    posting_period（M2）/payment_receipt_order 绝不发——装配时各实体独立，无误发通道。

    list 是 Spring Page GET 分页（filter 进 query、page/size 进 query，照 mm/sd 标准）→ get_page
    归一；get 是 path-id 单条 → get_json。date filter 是 date 形（YYYY-MM-DD，同 mm，非 sd datetime）。
    """

    MOD = "fn"
    # 子类定：list 端点段映射 + apar 链路下的资源前缀。
    _LIST_SEG: dict = {}

    def __init__(
        self,
        cred: Credentials,
        session: Session,
        http: HttpClient,
        currency_index: Optional[dict] = None,
    ):
        self._cred = cred
        self._session = session
        self._http = http
        # 金额/币种归一字典（来自 md.currency，由 facade 懒装配注入；None 则 companion no-op）。
        self._currency_index = currency_index

    def _normalize_currency_fields(self, items: list) -> list:
        """对 list/get 行项旁挂币种 alpha companion（复用 sd 同款非破坏性机制）。

        无 currency_index 或字段不在场 → 原样穿过（不臆造 companion）。§6（行 791/805）
        要求 fn payment_receipt/fapiao 的金额/币种字段按 sd companion 模式归一。
        TODO: live fn __schema 复核真实币种字段名 —— §6 未枚举 fn 响应币种字段名
          （filter_keys 是过滤键非响应字段），此处照 sd 约定用 `*_currency_no`→`*_currency`
          companion 机制；若 fn 实际字段名不同则 companion 自然 no-op 不触发（诚实降级）。
        """
        return _attach_currency_companions(items, self._currency_index)

    def _tenant_id(self) -> str:
        return self._session.token().tenant_id

    def _base(self) -> str:
        return self._cred.base_url(self.MOD)

    def _company_code_headers(self, company_code: Optional[str]) -> Optional[dict]:
        """fncc header：入参覆盖 → 否则 cred 默认 → 皆 None 则不注入（返回 None）。"""
        cc = company_code if company_code is not None else self._cred.default_company_code_id
        return {"fncc": cc} if cc else None

    # ---- 子类覆写：module → list/get 路径 ----
    def _list_path(self, tenant_id: str, module: str) -> str:
        raise NotImplementedError

    def _get_path(self, tenant_id: str, module: str, entity_id: str) -> str:
        raise NotImplementedError

    def _list_module(
        self, module: str, base_params: dict, company_code: Optional[str], size: int, all_pages: bool
    ) -> Page:
        url = self._base() + self._list_path(self._tenant_id(), module)
        headers = self._company_code_headers(company_code)

        def fetch(page_no: int) -> Page:
            params = {**base_params, "page": str(page_no), "size": str(size)}
            page = self._http.get_page(url, params, requested_size=size, extra_headers=headers)
            page.items = self._normalize_currency_fields(page.items)  # 金额/币种 companion 归一
            return page

        if not all_pages:
            return fetch(0)
        agg = iterate_all(fetch)
        return Page(
            items=agg.items, page=None, total=None, has_next=agg.truncated, truncated=agg.truncated
        )

    def _get_module(self, entity_id: str, module: str, company_code: Optional[str]) -> dict:
        url = self._base() + self._get_path(self._tenant_id(), module, entity_id)
        headers = self._company_code_headers(company_code)
        rec = self._http.get_json(url, extra_headers=headers)
        # get 单条同样旁挂币种 companion（包成单元素 list 复用同一机制，原 dict 就地归一）。
        self._normalize_currency_fields([rec])
        return rec


class PaymentReceiptEntity(_TwinAparEntity):
    """fn.payment_receipt（custom-verbs，module 双轨）：收/付款单。

    module=ar|ap 必填分叉端点：list `/payment-receipts/receipts/page`（ar）vs
    `/payment-receipts/payments/page`（ap）、get 使用对应资源段加 `/{id}`；module 缺失或非 ar/ap →
    PaymentReceiptValidationError fail-loud（不打网络）。
    fncc header 注入：company_code 入参覆盖 → 否则 cred.default_company_code_id。

    **from/to_posting_period_id 是 REQUIRED filter**（缺任一在 SDK 侧 fail-loud，不发请求）——先调
    posting_period.list 拿 id（items[].id 即此处来源）。module-scoped filter：contract_ids/so_ids 仅
    AR、po_contract_ids/po_ids 仅 AP（最小实现只透传不校验非法 key）。date filter 是 date 形
    （YYYY-MM-DD，同 mm，非 sd datetime ISO）。金额/币种字段经 facade 懒装配注入的 currency_index
    旁挂 alpha companion 归一（`*_currency_no`→`*_currency`，非破坏性，原 `_no` 字段不动；故 fn 命名空间
    需懒装配）；无 index 时 companion no-op、原样透传。

    filter_keys（§6）：from_posting_period_id(REQUIRED) / to_posting_period_id(REQUIRED) /
    document_category_code / document_no / business_partner_id / status / voucher_status /
    verification_status / from_posting_date / to_posting_date / contract_ids(AR) / so_ids(AR) /
    po_contract_ids(AP) / po_ids(AP)。

    端点与 header 已于 2026-09-29 对 production frontend 和 HLKDQ live 查询校正。
    """

    _LIST_SEG = _PR_LIST_SEG

    def _list_path(self, tenant_id: str, module: str) -> str:
        return (
            f"/v2/api/tenants/{tenant_id}/company-codes/payment-receipts/"
            f"{_PR_LIST_SEG[module]}/page"
        )

    def _get_path(self, tenant_id: str, module: str, entity_id: str) -> str:
        return (
            f"/v2/api/tenants/{tenant_id}/company-codes/payment-receipts/"
            f"{_PR_LIST_SEG[module]}/{entity_id}"
        )

    def list(
        self,
        *,
        module: Optional[str] = None,
        filter: Optional[dict] = None,
        company_code: Optional[str] = None,
        size: int = 20,
        all: bool = True,
    ) -> Page:
        # module 默认 None（非 Python-required）→ 由 _validate_module 给 PaymentReceiptValidationError
        # 而非裸 TypeError；filter 同理（REQUIRED 校验在下方，缺省即触发 fail-loud）。
        module = _validate_module(module)
        f = dict(filter or {})
        # REQUIRED posting_period 校验：缺任一 fail-loud，绝不打网络。
        missing = [k for k in ("from_posting_period_id", "to_posting_period_id") if not f.get(k)]
        if missing:
            raise PaymentReceiptValidationError(
                f"payment_receipt list 缺 REQUIRED filter: {', '.join(missing)} —— "
                f"先调 posting_period.list 拿 id（items[].id）"
            )
        return self._list_module(module, f, company_code, size, all)

    def get(
        self, entity_id: str, *, module: Optional[str] = None, company_code: Optional[str] = None
    ) -> dict:
        module = _validate_module(module)
        return self._get_module(entity_id, module, company_code)


class FapiaoEntity(_TwinAparEntity):
    """fn.fapiao（custom-verbs，module 双轨）：发票。

    module=ar|ap 必填分叉端点：list `/fapiaos/ar/query-page`（ar）vs
    `/fapiaos/ap/query-page`（ap）、get `/fapiaos/ar/{id}` vs `/fapiaos/ap/{id}`
    （**注意端点段刻意不同于 payment_receipt 的 /receipts /payments**）；module 缺失或非 ar/ap →
    PaymentReceiptValidationError fail-loud（不打网络）。fncc header 注入同 payment_receipt。

    **差异点**：from/to_posting_period_id 此处 OPTIONAL（payment_receipt 是 REQUIRED）——不做强制校验，
    缺省也正常打网络。AP 独有 from/to_certificate_date（税务认证日期）；最小实现只透传不按 module 校验。
    date filter 是 date 形（YYYY-MM-DD）。金额/币种字段经 facade 懒装配的 currency_index 旁挂 alpha
    companion 归一（`*_currency_no`→`*_currency`，同 payment_receipt）；无 index 时 no-op 原样透传。

    filter_keys（§6）：fapiao_nums / fapiao_order_no / business_partner_ids / fapiao_type_code /
    status_list / verification_status_list / from_fapiao_date / to_fapiao_date /
    from_posting_period_id(OPTIONAL) / to_posting_period_id(OPTIONAL) / contract_ids(AR) /
    po_ids(AP) / from_certificate_date(AP) / to_certificate_date(AP)。

    端点与 header 已于 2026-09-29 对 production frontend 和 HLKDQ live 查询校正。
    """

    _LIST_SEG = _FAPIAO_LIST_SEG

    def _list_path(self, tenant_id: str, module: str) -> str:
        return (
            f"/v2/api/tenants/{tenant_id}/company-codes/fapiaos/"
            f"{_FAPIAO_LIST_SEG[module]}/query-page"
        )

    def _get_path(self, tenant_id: str, module: str, entity_id: str) -> str:
        return (
            f"/v2/api/tenants/{tenant_id}/company-codes/fapiaos/"
            f"{_FAPIAO_LIST_SEG[module]}/{entity_id}"
        )

    def list(
        self,
        *,
        module: Optional[str] = None,
        filter: Optional[dict] = None,
        company_code: Optional[str] = None,
        size: int = 20,
        all: bool = True,
    ) -> Page:
        module = _validate_module(module)
        # posting_period OPTIONAL：不校验，缺省照常打网络。
        return self._list_module(module, dict(filter or {}), company_code, size, all)

    def get(
        self, entity_id: str, *, module: Optional[str] = None, company_code: Optional[str] = None
    ) -> dict:
        module = _validate_module(module)
        return self._get_module(entity_id, module, company_code)
