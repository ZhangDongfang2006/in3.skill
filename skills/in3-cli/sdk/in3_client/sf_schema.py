"""SIM 的字段契约，来源：in-mom-sf 的 SimIssueQuery/List/DetailVO（2026-10-13）。"""

SF_FILTERS = {}
for _type, _multi, _names in (
    ("string", False, "key_text recorder_id work_unit_id org_id sponsor_org_id resp_org_id "
     "issue_no mo_no so_no ref_order_no ref_order_type ref_order_id sponsor_id sponsor_fullname "
     "resp_user_id resp_user_fullname user_id field_export_strategy column_a column_b column_c "
     "column_d column_e search_type to_do_type description"),
    ("string", True, "sim_level issue_type org_id_list sponsor_org_id_list resp_org_id_list "
     "ref_order_ids root_cause sort sim_issue_id_list"),
    ("integer", True, "status"),
    ("boolean", False, "over_date_only no_display_only include_action_history upgraded "
     "recent_three_days_over_date no_action has_action me_to_confirm personally_concerned "
     "dept_responsible dept_sponsor"),
    ("date", False, "start_reported_date end_reported_date start_cmt_cplt_date end_cmt_cplt_date "
     "start_finished_date end_finished_date start_completed_date end_completed_date start_date end_date"),
    ("datetime", False, "start_closed_date_time end_closed_date_time"),
):
    for _name in _names.split():
        SF_FILTERS[_name] = {"name": _name, "type": _type, "multi": _multi}

LIST_FIELDS = (
    "id issue_no mo_no mo_id sim_level sim_level_name work_unit_name sponsor_id sponsor_fullname "
    "sponsor_org_name resp_user_id resp_user_fullname resp_org_name issue_type issue_type_desc "
    "sim1_pf_date sim2_pf_date sim3_pf_date sim5_pf_date description reported_date created_date "
    "status status_name last_cmt_cplt_date upgraded sim_level_detail so_no so_name ref_count "
    "reason action_plan action_plan_date finished_date completed_time action_first_create_at "
    "action_last_update_at reported_date_time finished_date_time closed_date_time system_completed_at "
    "root_causes_remark root_cause_list root_causes can_upgrade column_a column_b column_c column_d "
    "column_e work_unit_id sponsor_org_id resp_org_id personally_concerned personally_concerned_by "
    "personally_concerned_full_name approval_time approval_type personally_concerned_time source_type "
    "title ai_reason recommendation_time available_actions recent_operation_history reject_field_list "
    "last_rejected_time"
).split()

DETAIL_FIELDS = (
    "id issue_no mo_id mo_no recorder_id recorder_fullname sponsor_id sponsor_org_id sponsor_org_name "
    "sponsor_fullname work_unit_id work_unit_name reported_date resp_user_id resp_org_id resp_org_name "
    "resp_user_fullname sim_level issue_type issue_type_desc status_name description completed_time "
    "reported_date_time finished_date_time system_completed_at completed_remark finished_date "
    "finished_remark action_list log_list status images upgraded so_no so_name root_cause_remark "
    "qas_check_result_id created_date sim_level_detail sim_issue_refs root_causes column_a column_b "
    "column_c column_d column_e rejected_fields personally_concerned personally_concerned_by "
    "personally_concerned_full_name approval_time approval_type rejection_fields can_complete can_reopen informers"
).split()

# 后端把排序字段直接拼入 SQL；仅允许已知列，绝不透传 SQL 表达式。
SORT_FIELDS = set(("id issue_no reported_date created_date status last_cmt_cplt_date completed_time "
                   "finished_date work_unit_id sim_level action_last_update_at").split())


def schema(version: str) -> dict:
    """提供免登录的命令、筛选条件及完整字段说明。"""
    return {
        "name": "in3-sf", "version": version,
        "global_flags": ["--workspace", "--tenant"],
        "commands": {"sim-issue": {
            "list": {
                "description": "SIM 问题全字段列表（POST 请求体分页）；--include-details 补齐完整详情",
                "flags": ["--all", "--page", "--size", "--max", "--max-pages",
                          "--filter", "--include-details", "--output"],
                "filter_keys": list(SF_FILTERS.values()), "item_fields": LIST_FIELDS,
                "returns": "{items, page, total, has_next, truncated}",
                "response_notes": [
                    "字段按服务端原样保留，包括新增字段、null、嵌套对象及数组。",
                    "--include-details 合并详情非 null 字段；每条 detail 保留完整详情原文。",
                    "全量范围为当前账号可访问且未删除的问题；默认不筛状态或日期。",
                    "按 has_next 翻页；触及 --max/--max-pages 时 truncated=true。",
                    "默认按 si.id,asc 稳定排序；数据变动期间分页不提供快照一致性。",
                ],
                "sort_fields": sorted(SORT_FIELDS),
            },
            "get": {"args": ["id"], "flags": ["--output"], "item_fields": DETAIL_FIELDS,
                    "response_notes": ["完整详情包含 action_list/log_list/images/sim_issue_refs/root_causes。"]},
        }},
        "error_envelope": {"shape": {"error": {"type": "string", "message": "string",
                                                "http_status": "integer|null"}}},
        "exit_codes": {"success": 0, "unknown": 1, "auth_failed": 2, "not_found": 3,
                       "validation": 4, "network_or_server": 5},
    }


def capability(version: str) -> dict:
    """返回与命令 schema 同源的能力声明。"""
    return {
        "module": "sf", "binary": "in3-cli exec sf", "version": version,
        "domain": "慧现场 SIM 问题协同",
        "entities": [{"name": "sim-issue", "verbs": ["list", "get"],
                      "filter_style": "snake_case", "filter_keys": list(SF_FILTERS),
                      "multi_value_keys": [name for name, spec in SF_FILTERS.items() if spec["multi"]],
                      "typed_flags": schema(version)["commands"]["sim-issue"]["list"]["flags"]}],
    }
