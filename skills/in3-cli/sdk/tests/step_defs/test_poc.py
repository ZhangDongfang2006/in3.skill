"""POC 北极星验收的 BDD step defs（issue #9）。绑定 features/in3-client-poc-acceptance.feature。

离线可跑 2 个：partial 失败 fail-loud（防 ¥111K 静默丢单）、孤儿物料保留（防漏算）。
其余 5 个需 zhuzheng 凭证或 HITL（真实 Top10 parity / token 降幅 / doctor BARS / M4 人裁决）
→ 在各自 `当` 步 pytest.skip 注明原因（step 仍绑定，保证 collection 通过）。
"""
import pytest
from pytest_bdd import scenarios, given, when, then

from in3_client.http import HttpError
from in3_client.value import join
from ._support import FakeResponse, make_in3

scenarios("../../features/in3-client-poc-acceptance.feature")


def _hitl_skip(reason: str):
    pytest.skip(f"需 zhuzheng 凭证 / HITL，离线不可跑：{reason}")


# ---------- 背景（所有场景共享） ----------

@given("2026-05 的采购订单、可用库存、供应商数据可查（跨 mm+wm+md）", target_fixture="bdd_context")
def _bg_data():
    return {}


@given("同一 POC 任务集分别走 CLI 现状路径与 SDK/run 路径")
def _bg_two_paths(bdd_context):
    bdd_context["two_paths"] = True


# ========== 离线可跑场景 ==========

# ---- RTM #7：partial 失败 fail-loud ----

@given("主任务中某个 fan-out 子查询失败")
def _g_fanout_fails(bdd_context):
    # available_stock.by_materials 的某子查询后端 500 → 应 fail-loud 冒泡，不静默吞成空集。
    in3, _, _ = make_in3([FakeResponse(500, text="server error")])
    bdd_context["in3"] = in3


@when("SDK 路径处理该失败")
def _w_handle_fanout_fail(bdd_context):
    try:
        bdd_context["result"] = bdd_context["in3"].wm.available_stock.by_materials(["m1"])
        bdd_context["error"] = None
    except Exception as e:  # noqa: BLE001
        bdd_context["error"] = e
        bdd_context["result"] = None


@then("它 fail-loud（抛错或显式标记）")
def _t_fail_loud(bdd_context):
    assert isinstance(bdd_context["error"], HttpError)  # 抛错冒泡，非静默


@then("绝不静默返回空集导致 Top10 金额/库存少算")
def _t_no_silent_empty(bdd_context):
    assert bdd_context["error"] is not None
    assert bdd_context["result"] is None  # 没有返回一个「空 Page」骗调用方


# ---- RTM #7：孤儿物料保留 ----

@given("某 material_id 在 md.material 无对应记录")
def _g_orphan_material(bdd_context):
    # 左表（采购金额）两个物料，右表（md.material）只有 a → b 是孤儿。
    bdd_context["left"] = [{"material_id": "a", "amount": 100}, {"material_id": "b", "amount": 50}]
    bdd_context["right"] = [{"material_id": "a", "material_name": "螺栓"}]


@when("主任务做跨模块 join")
def _w_cross_join(bdd_context):
    bdd_context["joined"] = join(bdd_context["left"], bdd_context["right"], on="material_id")


@then("该行被保留并标 _orphan")
def _t_orphan_flagged(bdd_context):
    b = next(r for r in bdd_context["joined"] if r["material_id"] == "b")
    assert b["_orphan"] is True
    assert b["amount"] == 50  # 金额仍在（没被丢）


@then("不被静默丢弃")
def _t_orphan_kept(bdd_context):
    assert len(bdd_context["joined"]) == len(bdd_context["left"])  # 左表行数全保留


# ========== 需凭证 / HITL 场景：skip 注明原因 ==========

# ---- RTM #7：主任务 1–3 轮 ----

@when("用 SDK/run 跑「本月采购金额 Top10 物料 × 各自 wm 可用库存 × 标独家供应」")
def _w_main_task():
    _hitl_skip("真实跨模块 Top10 主任务 + 推理轮次测量")


@then("完成所需 LLM 推理轮次落在 1–3 轮")
def _t_rounds():
    pass


@then("中间数据不进 LLM 上下文、只 print 最终结果")
def _t_no_intermediate():
    pass


# ---- RTM #32：parity 逐位 ----

@when("比对 SDK 路径与 CLI 路径对主任务的业务数字")
def _w_parity_main():
    _hitl_skip("真后端 Top10 采购金额/库存/独家供应 parity 逐位比对")


@then("Top10 采购金额、可用库存数量、独家供应标记、币种逐位一致")
def _t_parity_main():
    pass


@then("任一位不一致即整体验收 FAIL")
def _t_parity_veto_overall():
    pass


# ---- RTM #32：token 降幅 ----

@when("量同一任务端到端进 LLM 的 token")
def _w_token():
    _hitl_skip("端到端 token 降幅测量")


@then("SDK 路径相对 CLI 路径降幅达到阈值（暂定 ≥70%，以设计 PRD §5.2 为准）")
def _t_token_threshold():
    pass


# ---- RTM #32：doctor BARS ----

@when("用 in3-cli-doctor 对 SDK 版跑 BARS")
def _w_doctor():
    _hitl_skip("in3-cli-doctor BARS 评分（另起 doctor，HITL）")


@then("关键分项 #3/#14/#15 不低于当前基线且加权总分不退")
def _t_bars_no_regress():
    pass


@then('报告把"不退"与"翻 PASS"明确区分（翻 PASS 是 bonus、非门禁）')
def _t_bars_distinguish():
    pass


# ---- RTM #32：M4 人裁决 ----

@given("四指标实测值已记入 BEFORE-AFTER.md")
def _g_metrics_recorded(bdd_context):
    bdd_context["metrics_recorded"] = True


@when("团队/干系人评审")
def _w_review():
    _hitl_skip("M4 go/no-go 由人显式裁决，不由 agent 自判")


@then("按「①必过 + ②③达阈值 + ④不退」裁决是否 ship")
def _t_decision_rule():
    pass


@then("决策由人显式确认、不由 agent 自判")
def _t_human_confirm():
    pass
