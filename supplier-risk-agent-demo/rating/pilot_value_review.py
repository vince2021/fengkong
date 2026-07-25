from __future__ import annotations


HIGH_RISK_SEGMENTS = {"重点监控", "高风险客商", "禁入客商", "不予额度"}


def build_pilot_value_review(mapping_package: dict, task_board: dict, rating_results: list[dict]) -> dict:
    valid_results = [item for item in rating_results if item.get("ok", True)]
    sample_count = len(valid_results)
    review_required = [item for item in valid_results if item.get("review_required")]
    high_risk = [
        item
        for item in valid_results
        if item.get("risk_segment") in HIGH_RISK_SEGMENTS or item.get("rating") == "D" or item.get("strong_rule_hits")
    ]
    strong_rule_hit_count = sum(len(item.get("strong_rule_hits", [])) for item in valid_results)
    field_gap_count = len(task_board.get("risk_tasks", []))
    saved_hours = round(sample_count * 1.0, 1)
    recommendation = _recommendation(sample_count, field_gap_count, high_risk)

    return {
        "title": f"{mapping_package['industry_label']}试点复盘与价值评估",
        "summary": {
            "行业模板": mapping_package["industry_label"],
            "模型版本": mapping_package["model_version"],
            "样本数量": f"{sample_count} 家",
            "风险识别": f"{len(high_risk)} 家",
            "人工复核": f"{len(review_required)} 家",
            "强规则命中": f"{strong_rule_hit_count} 条",
            "字段缺口": f"{field_gap_count} 项",
            "建议结论": recommendation,
        },
        "value_metrics": _build_value_metrics(sample_count, high_risk, review_required, strong_rule_hit_count, field_gap_count, saved_hours),
        "risk_findings": _build_risk_findings(high_risk),
        "efficiency_estimate": _build_efficiency_estimate(sample_count, saved_hours),
        "field_gap_impact": _build_field_gap_impact(task_board),
        "poc_recommendation": _build_poc_recommendation(recommendation, sample_count, field_gap_count, strong_rule_hit_count),
        "next_actions": _build_next_actions(field_gap_count, recommendation),
    }


def build_pilot_value_review_markdown(review: dict) -> str:
    lines = [f"# {review['title']}", ""]
    lines.extend(_rows_to_markdown("封面摘要", [{"项目": key, "内容": value} for key, value in review["summary"].items()]))
    lines.extend(_rows_to_markdown("价值指标", review["value_metrics"]))
    lines.extend(_rows_to_markdown("风险识别结果", review["risk_findings"]))
    lines.extend(_rows_to_markdown("效率测算", review["efficiency_estimate"]))
    lines.extend(_rows_to_markdown("字段缺口影响", review["field_gap_impact"]))
    lines.extend(_rows_to_markdown("POC 建议", review["poc_recommendation"]))
    lines.extend(_rows_to_markdown("下一步动作", review["next_actions"]))
    return "\n".join(lines).strip() + "\n"


def _build_value_metrics(
    sample_count: int,
    high_risk: list[dict],
    review_required: list[dict],
    strong_rule_hit_count: int,
    field_gap_count: int,
    saved_hours: float,
) -> list[dict]:
    return [
        {
            "指标": "样本覆盖",
            "试点表现": f"{sample_count} 家客商完成回放",
            "业务解释": "覆盖准入、限制准入、人工复核和禁入等典型风险判断路径。",
        },
        {
            "指标": "风险识别",
            "试点表现": f"识别 {len(high_risk)} 家需关注客商",
            "业务解释": "将外部风险、内部履约和强规则结果转成可解释的风险处置建议。",
        },
        {
            "指标": "人机协同",
            "试点表现": f"{len(review_required)} 家触发人工复核",
            "业务解释": "机器负责计算、证据聚合和预警，人负责例外审批和最终责任判断。",
        },
        {
            "指标": "强规则有效性",
            "试点表现": f"命中 {strong_rule_hit_count} 条强规则",
            "业务解释": "底线风险不会被综合分数稀释，适合向内控和审计解释。",
        },
        {
            "指标": "字段完备性",
            "试点表现": f"{field_gap_count} 项字段需要补齐或确认替代方案",
            "业务解释": "字段缺口已转化为客户任务，可作为 POC 启动前的数据准备清单。",
        },
        {
            "指标": "效率收益",
            "试点表现": f"预计节省 {saved_hours:g} 小时人工整理时间",
            "业务解释": "主体核验、风险扫描、评分解释和报告汇总由 Agent 先行完成。",
        },
    ]


def _build_risk_findings(high_risk: list[dict]) -> list[dict]:
    rows = []
    for item in high_risk[:8]:
        rows.append(
            {
                "客商": item.get("counterparty_name", item.get("counterparty_id", "-")),
                "评级": item.get("rating", "-"),
                "准入策略": item.get("access_strategy", "-"),
                "风险分层": item.get("risk_segment", "-"),
                "风险原因": _risk_reason(item),
                "管理动作": "进入人工复核并保留证据链" if item.get("review_required") else "纳入持续监控",
            }
        )
    return rows


def _build_efficiency_estimate(sample_count: int, saved_hours: float) -> list[dict]:
    baseline = round(sample_count * 1.5, 1)
    agent_time = round(sample_count * 0.5, 1)
    return [
        {"环节": "样本资料整理", "人工方式": f"{sample_count * 0.5:g} 小时", "Agent 辅助": f"{sample_count * 0.2:g} 小时", "收益": "减少重复查询和复制粘贴"},
        {"环节": "风险证据汇总", "人工方式": f"{sample_count * 0.6:g} 小时", "Agent 辅助": f"{sample_count * 0.2:g} 小时", "收益": "自动生成证据组和风险解释"},
        {"环节": "报告初稿生成", "人工方式": f"{sample_count * 0.4:g} 小时", "Agent 辅助": f"{sample_count * 0.1:g} 小时", "收益": "模型结果、字段快照和审计留痕自动合并"},
        {"环节": "总体估算", "人工方式": f"{baseline:g} 小时", "Agent 辅助": f"{agent_time:g} 小时", "收益": f"预计节省 {saved_hours:g} 小时"},
    ]


def _build_field_gap_impact(task_board: dict) -> list[dict]:
    rows = []
    for task in task_board.get("risk_tasks", [])[:8]:
        rows.append(
            {
                "字段名": task["字段名"],
                "当前状态": task["状态"],
                "责任人": task["客户负责人"],
                "上线影响": task["阻塞影响"],
                "建议处理": task["当前动作"],
            }
        )
    return rows


def _build_poc_recommendation(recommendation: str, sample_count: int, field_gap_count: int, strong_rule_hit_count: int) -> list[dict]:
    return [
        {
            "评估项": "建议结论",
            "结论": recommendation,
            "依据": f"已完成 {sample_count} 家样本回放，识别字段缺口 {field_gap_count} 项，强规则命中 {strong_rule_hit_count} 条。",
        },
        {
            "评估项": "进入条件",
            "结论": "客户确认字段口径、接口边界、人工复核职责和报告模板。",
            "依据": "字段、任务、复核和报告链路已经在 Demo 中形成闭环。",
        },
        {
            "评估项": "管理层关注",
            "结论": "重点看风险识别准确性、字段准备成本和上线后的流程责任边界。",
            "依据": "企业数据模型需要观察期，POC 应以样本回放和流程验证为主。",
        },
    ]


def _build_next_actions(field_gap_count: int, recommendation: str) -> list[dict]:
    return [
        {"动作": "确认复盘结论", "负责人": "客户业务/风控负责人", "建议周期": "T+1 天", "产出": recommendation},
        {"动作": "补齐高优先级字段", "负责人": "客户 IT/数据负责人", "建议周期": "T+3 天", "产出": f"处理 {field_gap_count} 项关键字段缺口"},
        {"动作": "确定 POC 样本池", "负责人": "双方项目组", "建议周期": "T+5 天", "产出": "30-100 家样本及历史审批结果"},
        {"动作": "固化验收指标", "负责人": "方案/项目经理", "建议周期": "T+7 天", "产出": "风险识别率、人工节省、报告可用性、审计留痕完整性"},
    ]


def _recommendation(sample_count: int, field_gap_count: int, high_risk: list[dict]) -> str:
    if sample_count == 0:
        return "暂不进入 POC，需先准备样本数据"
    if field_gap_count >= 6:
        return "建议进入受控 POC，先补齐关键字段并设定模型观察期"
    if high_risk:
        return "建议进入正式 POC，重点验证风险识别和人工复核闭环"
    return "建议进入正式 POC，重点验证规模化效率收益"


def _risk_reason(result: dict) -> str:
    hits = result.get("strong_rule_hits", [])
    if hits:
        return "；".join(f"{hit['rule_id']} {hit['rule_name']}" for hit in hits[:2])
    deductions = result.get("main_deductions", [])
    if deductions:
        return "；".join(item.get("reason", item.get("indicator", "-")) for item in deductions[:2])
    if result.get("review_required"):
        return "模型策略要求人工复核"
    return result.get("risk_segment", "风险分层关注")


def _rows_to_markdown(title: str, rows: list[dict]) -> list[str]:
    lines = ["", f"## {title}", ""]
    if not rows:
        lines.append("- 暂无数据")
        return lines
    for row in rows:
        lines.append("- " + "；".join(f"{key}：{value}" for key, value in row.items()))
    return lines
