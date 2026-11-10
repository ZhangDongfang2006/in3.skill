"""坑层 helper（纯函数）。v1 逐 entity 手工移植的坑层下沉点（全部已落地）。

含：normalize_currency（156↔CNY 表示归一）/ build_currency_index / chunk_material_ids /
matched_filter_values / dedup_by / fan_out（fan-out 聚合）/ open_qty_fallback / as_string_array。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable

from .envelope import Page


def as_string_array(v) -> list:
    """清洗 material id 入参（移植 wm/cli asStringArray）：isReal = 字符串 且非空 且 != "undefined"。

    list → filter(isReal)；单个 real 字符串 → [v]；None / 非 real → []。
    剔 "undefined" 是 cac/CLI 占位 quirk（单值时多值选项被填字面 "undefined"）。
    """
    def is_real(x) -> bool:
        return isinstance(x, str) and x != "" and x != "undefined"

    if v is None:
        return []
    if isinstance(v, list):
        return [x for x in v if is_real(x)]
    return [v] if is_real(v) else []


def fan_out(ids: list, fetch_one: Callable, concurrency: int = 16) -> Page:
    """对一批 id 并发 fan-out（默认并发 16），skip-on-error，聚合成单页（移植 wm/cli fanOutByMaterialIds）。

    - 失败子调用（抛错）整个跳过、不抛、不影响其余（按 id 顺序保留成功项的 items）；
    - items = flatMap 各成功子调用 items（不去重，4 视图物理维度天然不重叠）；
    - total：成功项全数值 → 求和；任一成功项 total is None → 聚合 total=None（失败跳过项不计）；
    - 返回 Page{items, page=0, total, has_next=False}。
    """
    concurrency = max(1, int(concurrency or 16))
    results: list = [None] * len(ids)
    if ids:
        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            fut_to_i = {ex.submit(fetch_one, mid): i for i, mid in enumerate(ids)}
            for fut, i in fut_to_i.items():
                try:
                    results[i] = fut.result()
                except Exception:
                    results[i] = None  # skip-on-error

    items: list = []
    total: int | None = 0
    for r in results:
        if r is None:
            continue  # 失败跳过，不计 total（同 CLI if(!r) continue）
        items.extend(r.items)
        if r.total is None:
            total = None
        elif total is not None:
            total += r.total
    return Page(items=items, page=0, total=total, has_next=False)


def enrich_items_fanout(
    headers: list,
    fetch_items_for: Callable,
    concurrency: int = 5,
) -> list:
    """per-header bounded fan-out，FAIL-ISOLATED —— 给 client-side include_items 用。

    供 sd.sales-order / sd.contract / pp.production-plan：对每个表头 header 调
    fetch_items_for(header) 取其行项，成功时把行项挂回该 header 的 ``items`` 字段。

    fail-mode（区别于 fan_out 的 skip-on-error、PurchaseOrder bulk-get 的 fail-loud）：
    - 某 header 的 fetch_items_for 抛异常 → 该 header ``items=None`` + 旁挂 ``items_error``
      （错误摘要字符串），**异常不冒泡**；
    - 其余 header 照常返回其 items；
    - 失败 header 仍在结果里（不丢失），agent 能从 ``items=None + items_error`` 区分
      「取行项失败」与「确实没有行项」。

    返回与输入等长、保持 header 顺序的 list；每个元素是输入 header 的浅拷贝 + items(/items_error)，
    **不就地改写**入参 header。并发上限受 concurrency 约束（默认 5）。
    """
    concurrency = max(1, int(concurrency or 5))
    out: list = [None] * len(headers)
    if not headers:
        return []

    def work(header):
        enriched = dict(header)
        try:
            enriched["items"] = fetch_items_for(header)
        except Exception as e:  # fail-isolated：不冒泡，旁挂错误摘要
            enriched["items"] = None
            enriched["items_error"] = f"{type(e).__name__}: {e}"
        return enriched

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        fut_to_i = {ex.submit(work, h): i for i, h in enumerate(headers)}
        for fut, i in fut_to_i.items():
            out[i] = fut.result()  # work 内已吞异常，这里不会抛
    return out


def chunk_material_ids(ids: list, size: int = 80) -> list:
    """把 ids 切成 ≤size 的块（80→1、81→2、160→2、空→0）。

    用于 fan-out 前分块，避免一次性大 id 列表 413/被后端截断。
    """
    return [list(ids[i:i + size]) for i in range(0, len(ids), size)]


def matched_filter_values(items: list, requested: Iterable, key: str) -> list:
    """返回值 items[].<key> 与请求过滤值的交集（保留 requested 顺序）。

    暴露后端 multi-filter 的并集语义：后端可能多返（union），交集才是"我请求的里真匹配上的"。
    """
    returned = {it.get(key) for it in items}
    return [v for v in requested if v in returned]


def _is_number(v) -> bool:
    """数字判定（剔 bool —— True/False 是 int 子类）。"""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def open_qty_fallback(items: list) -> None:
    """对 PO line items 就地兜底 open_qty（逐位移植 mm/cli applyOpenQtyFallback）。

    open_qty 非 null（含 0）→ 不动；purchase_qty 非数 → 跳过不兜底；completed_qty 非数按 0；
    open_qty = max(0, purchase_qty - completed_qty)，并打 _open_qty_source。
    """
    for it in items:
        if it.get("open_qty") is not None:
            continue
        pq = it.get("purchase_qty")
        if not _is_number(pq):
            continue
        cq = it.get("completed_qty")
        cqn = cq if _is_number(cq) else 0
        it["open_qty"] = max(0, pq - cqn)
        it["_open_qty_source"] = "fallback:purchase_qty-completed_qty"


def dedup_by(items: list, keys) -> list:
    """按 keys（单 key 字符串或多 key 元组）组成的复合主键去重，保留首次出现。"""
    if isinstance(keys, str):
        keys = (keys,)
    seen = set()
    out = []
    for it in items:
        k = tuple(it.get(f) for f in keys)
        if k not in seen:
            seen.add(k)
            out.append(it)
    return out


def build_currency_index(currency_records: list) -> dict:
    """从 md.currency 记录建索引：数值 ISO（iso_currency_no）与字母（currency_code/
    iso_currency_code）都映到规范字母形（currency_code 优先，回退 iso_currency_code）。

    缺字段的记录跳过对应映射，不抛。
    """
    index: dict = {}
    for rec in currency_records:
        alpha = rec.get("currency_code") or rec.get("iso_currency_code")
        if not alpha:
            continue
        index[alpha] = alpha
        iso_no = rec.get("iso_currency_no")
        if iso_no is not None and iso_no != "":
            index[str(iso_no)] = alpha
    return index


def normalize_currency(code, index: dict):
    """把币种码（数值 ISO 如 156/"156" 或字母如 "CNY"）归一到规范字母形。

    仅做表示归一，**不做 FX 汇率换算**。未知码 / None / 空串原样返回（兜底，不抛）。
    """
    if code is None or code == "":
        return code
    return index.get(str(code), code)
