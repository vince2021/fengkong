from __future__ import annotations


STATUS_ORDER = ["待客户提供", "已收到", "待映射", "有缺口", "已确认"]


def build_pilot_task_board(mapping_package: dict) -> dict:
    tasks = [_build_task(row) for row in mapping_package["data_readiness_checklist"]]
    columns = {status: [task for task in tasks if task["状态"] == status] for status in STATUS_ORDER}
    status_summary = [{"状态": status, "任务数": len(columns[status])} for status in STATUS_ORDER]
    risk_tasks = [
        task
        for task in tasks
        if task["状态"] in {"待客户提供", "待映射", "有缺口"} and task["是否必填"] == "是"
    ]

    return {
        "title": f"{mapping_package['industry_label']}试点任务看板",
        "industry_label": mapping_package["industry_label"],
        "model_version": mapping_package["model_version"],
        "summary": {
            "行业模板": mapping_package["industry_label"],
            "模型版本": mapping_package["model_version"],
            "任务总数": f"{len(tasks)} 项",
            "待客户处理": f"{len(columns['待客户提供']) + len(columns['有缺口'])} 项",
            "阻塞任务": f"{len(risk_tasks)} 项",
        },
        "status_summary": status_summary,
        "columns": columns,
        "tasks": tasks,
        "risk_tasks": risk_tasks,
    }


def build_pilot_task_board_markdown(board: dict) -> str:
    lines = [f"# {board['title']}", ""]
    lines.extend(_rows_to_markdown("封面摘要", [{"项目": key, "内容": value} for key, value in board["summary"].items()]))
    lines.extend(_rows_to_markdown("状态汇总", board["status_summary"]))
    for status in STATUS_ORDER:
        lines.extend(_rows_to_markdown(status, board["columns"][status]))
    lines.extend(_rows_to_markdown("阻塞任务", board["risk_tasks"]))
    return "\n".join(lines).strip() + "\n"


def _build_task(row: dict) -> dict:
    status = _derive_status(row)
    action = _next_action(status, row)
    return {
        "字段名": row["字段名"],
        "字段组": row["字段组"],
        "状态": status,
        "是否必填": row["是否必填"],
        "来源系统": row["来源系统"],
        "客户负责人": row["客户负责人"],
        "我方负责人": row["我方负责人"],
        "当前动作": action,
        "截止时间": _deadline(status),
        "阻塞影响": _blocking_impact(status, row),
    }


def _derive_status(row: dict) -> str:
    field_name = row["字段名"]
    customer_owner = row["客户负责人"]
    is_required = row["是否必填"] == "是"

    if field_name == "模型版本":
        return "已确认"
    if field_name == "企业名称":
        return "已收到"
    if not is_required:
        return "有缺口"
    if customer_owner == "无需客户准备":
        return "待映射"
    return "待客户提供"


def _next_action(status: str, row: dict) -> str:
    actions = {
        "待客户提供": f"请客户提供 {row['字段名']} 或导出对应系统字段。",
        "已收到": "校验字段口径，补充样本批次和数据更新时间。",
        "待映射": "映射到模型字段，完成接口返回值与规则字段校验。",
        "有缺口": "确认替代方案，决定试点补采或纳入二期范围。",
        "已确认": "纳入模型配置快照和审计留痕。",
    }
    return actions[status]


def _deadline(status: str) -> str:
    deadlines = {
        "待客户提供": "T+2 天",
        "已收到": "T+1 天",
        "待映射": "T+3 天",
        "有缺口": "T+5 天",
        "已确认": "已完成",
    }
    return deadlines[status]


def _blocking_impact(status: str, row: dict) -> str:
    if status == "待客户提供" and row["是否必填"] == "是":
        return "未收到前无法完成字段映射、样本回放或准入判断。"
    if status == "待映射":
        return "不影响客户准备，但影响规则命中和报告解释。"
    if status == "有缺口":
        return "影响材料完整性或审计附件链，需要确认替代方案。"
    if status == "已收到":
        return "低风险，需完成口径校验。"
    return "无阻塞，进入审计留痕。"


def _rows_to_markdown(title: str, rows: list[dict]) -> list[str]:
    lines = ["", f"## {title}", ""]
    if not rows:
        lines.append("- 暂无任务")
        return lines
    for row in rows:
        lines.append("- " + "；".join(f"{key}：{value}" for key, value in row.items()))
    return lines
