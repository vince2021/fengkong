from __future__ import annotations


def build_pilot_kickoff_package(flow: dict, guidance: dict) -> dict:
    company_name = flow["scenario_title"].split("｜", 1)[0]
    role_label = guidance["role_label"]
    rating_summary = _rating_summary(flow)
    success_criteria = guidance.get("success_criteria", [])
    focus_points = guidance.get("focus_points", [])

    return {
        "package_title": f"{company_name}｜{role_label}试点启动包",
        "cover_summary": {
            "试点样本": company_name,
            "目标角色": role_label,
            "当前评级结论": rating_summary,
            "建议下一步": guidance.get("next_action", "确认试点样本、字段清单和验收口径。"),
        },
        "启动会目标": [
            {"目标": "确认试点范围", "说明": "明确客商范围、业务流程、审批节点和试点边界。"},
            {"目标": "确认数据准备", "说明": "明确外部企业数据、内部订单合同发票履约数据、材料文档和报告模板。"},
            {"目标": "确认验收口径", "说明": "把演示认可转化为可验收的样本回放、规则解释和审计留痕指标。"},
        ],
        "客户准备清单": [
            {"准备事项": "首批试点样本", "建议内容": "10-30 家供应商/客户，覆盖优质、关注、限制、禁入等类型", "负责人": "客户业务/风控负责人"},
            {"准备事项": "内部字段字典", "建议内容": "订单、合同、发票、履约、逾期、争议、额度、账期字段", "负责人": "客户 IT/数据负责人"},
            {"准备事项": "审批规则与报告模板", "建议内容": "现有准入规则、人工复核要求、审核报告或尽调模板", "负责人": "客户风控/内控负责人"},
            {"准备事项": "系统对接边界", "建议内容": "确认 SRM、ERP、OA、风控系统或数据仓库的接口方式", "负责人": "客户 IT/数据负责人"},
        ],
        "我方准备清单": [
            {"准备事项": "字段映射初稿", "建议内容": "把客户字段映射到主体核验、外部风险、内部履约、财务信用和关系稳定维度", "负责人": "方案/数据顾问"},
            {"准备事项": "试点评分卡初稿", "建议内容": "基于客户行业模板配置权重、阈值、强规则和策略映射", "负责人": "风控方案"},
            {"准备事项": "样本回放计划", "建议内容": "安排样本导入、模型计算、人工复核、报告输出和复盘会议", "负责人": "项目经理"},
            {"准备事项": "风险问题清单", "建议内容": "提前准备数据缺失、模型解释、人工调整和审计留痕的应对口径", "负责人": "售前/方案"},
        ],
        "启动会议程": [
            {"议题": "确认试点范围", "时长": "15 分钟", "产出": "客商范围、业务流程、部门角色"},
            {"议题": "确认字段与接口", "时长": "25 分钟", "产出": "字段清单、数据来源、接口方式"},
            {"议题": "确认规则与报告", "时长": "20 分钟", "产出": "强规则、评分卡、报告模板调整点"},
            {"议题": "确认验收与排期", "时长": "15 分钟", "产出": "验收指标、里程碑、双方负责人"},
        ],
        "验收口径": _build_acceptance_rows(success_criteria, focus_points),
        "下一步任务": [
            {"任务": "客户提供样本和字段字典", "负责人": "客户项目组", "建议周期": "1-3 天"},
            {"任务": "我方完成字段映射和模板配置", "负责人": "方案/数据顾问", "建议周期": "2-4 天"},
            {"任务": "双方开展首轮样本回放", "负责人": "双方项目组", "建议周期": "5-7 天"},
            {"任务": "输出试点复盘和上线建议", "负责人": "项目经理", "建议周期": "2-3 天"},
        ],
    }


def build_pilot_kickoff_markdown(package: dict) -> str:
    lines = [f"# {package['package_title']}", ""]
    lines.extend(_rows_to_markdown("封面摘要", [{"项目": key, "内容": value} for key, value in package["cover_summary"].items()]))
    for section_name in ["启动会目标", "客户准备清单", "我方准备清单", "启动会议程", "验收口径", "下一步任务"]:
        lines.extend(_rows_to_markdown(section_name, package[section_name]))
    return "\n".join(lines).strip() + "\n"


def _rating_summary(flow: dict) -> str:
    summary = flow["summary"]
    return f"{summary['最终评级']} / {summary['准入策略']} / {summary['风险分层']}"


def _build_acceptance_rows(success_criteria: list[str], focus_points: list[str]) -> list[dict]:
    criteria = success_criteria or ["规则可配置", "证据可解释", "审计链路可追溯"]
    focus = "、".join(focus_points) if focus_points else "评分解释、人工复核、审计留痕"
    return [
        {"验收项": criteria[0], "验收口径": "业务负责人能看懂规则来源、命中原因和策略输出", "关联重点": focus},
        {"验收项": criteria[1] if len(criteria) > 1 else "证据可解释", "验收口径": "每个结论能追溯到字段、规则、模型版本和报告依据", "关联重点": focus},
        {"验收项": criteria[2] if len(criteria) > 2 else "审计链路可追溯", "验收口径": "人工调整保留原始结论、调整原因、复核人和时间", "关联重点": focus},
    ]


def _rows_to_markdown(title: str, rows: list[dict]) -> list[str]:
    lines = ["", f"## {title}", ""]
    for row in rows:
        lines.append("- " + "；".join(f"{key}：{value}" for key, value in row.items()))
    return lines
