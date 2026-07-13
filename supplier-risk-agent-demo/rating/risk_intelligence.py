from __future__ import annotations


HIGH_RISK_SEGMENTS = {"重点监控", "高风险客商", "禁入客商", "不予额度"}


def build_portfolio_dashboard(counterparties: list[dict], results: list[dict]) -> dict:
    valid_results = [item for item in results if item.get("ok")]
    counterparty_by_id = {item["id"]: item for item in counterparties}
    requested_limit_total = sum(counterparty_by_id[item["counterparty_id"]].get("requested_limit", 0) for item in valid_results)
    suggested_limit_total = sum(item.get("suggested_limit", 0) for item in valid_results)
    review_required = [item for item in valid_results if item.get("review_required")]
    high_risk = [item for item in valid_results if item.get("risk_segment") in HIGH_RISK_SEGMENTS or item.get("rating") == "D"]
    strong_rule_hits = [hit for item in valid_results for hit in item.get("strong_rule_hits", [])]
    watchlist = sorted(
        [
            {
                "客商名称": item["counterparty_name"],
                "评级": item["rating"],
                "风险分层": item["risk_segment"],
                "准入策略": item["access_strategy"],
                "建议额度": _money(item.get("suggested_limit", 0)),
                "触发原因": _watch_reason(item),
            }
            for item in valid_results
            if item.get("review_required") or item.get("risk_segment") in HIGH_RISK_SEGMENTS or item.get("strong_rule_hits")
        ],
        key=lambda row: (row["评级"] != "D", row["客商名称"]),
    )

    return {
        "total_counterparties": len(valid_results),
        "requested_limit_total": requested_limit_total,
        "suggested_limit_total": suggested_limit_total,
        "limit_reduction_amount": max(requested_limit_total - suggested_limit_total, 0),
        "review_required_count": len(review_required),
        "high_risk_count": len(high_risk),
        "strong_rule_hit_count": len(strong_rule_hits),
        "rating_distribution": _count_by(valid_results, "rating"),
        "segment_distribution": _count_by(valid_results, "risk_segment"),
        "watchlist": watchlist,
        "management_actions": _management_actions(valid_results, requested_limit_total, suggested_limit_total, review_required, high_risk, strong_rule_hits),
    }


def build_counterparty_profile(counterparty: dict, result: dict) -> dict:
    external = counterparty.get("external", {})
    internal = counterparty.get("internal", {})
    financial = counterparty.get("financial", {})
    tech = counterparty.get("tech_enterprise", {})

    profile = {
        "basic": {
            "企业名称": counterparty["name"],
            "统一社会信用代码": counterparty.get("credit_code", "-"),
            "客商类型": "客户" if counterparty.get("counterparty_type") == "customer" else "供应商",
            "当前状态": counterparty.get("cooperation_status", "-"),
            "申请额度": _money(counterparty.get("requested_limit", 0)),
            "模型评级": result.get("rating", "-"),
            "准入策略": result.get("access_strategy", "-"),
        },
        "主体画像": [
            f"登记状态：{external.get('registration_status', '-')}",
            f"成立年限：{external.get('established_years', '-')} 年",
            f"注册资本：{_money(external.get('registered_capital_amount', 0))}",
            f"纳税信用等级：{external.get('tax_credit_level', '-')}",
        ],
        "外部风险": [
            f"司法案件 {external.get('legal_cases_count', 0)} 条",
            f"重大诉讼金额 {_money(external.get('major_litigation_amount', 0))}",
            f"行政处罚 {external.get('admin_penalty_count', 0)} 条",
            f"经营异常 {external.get('operating_abnormal_count', 0)} 条",
            f"股权冻结 {external.get('equity_freeze_count', 0)} 条",
        ],
        "内部履约": [
            f"合作年限 {internal.get('cooperation_years', 0)} 年",
            f"近 12 月订单 {internal.get('orders_12m', 0)} 笔，金额 {_money(internal.get('order_amount_12m', 0))}",
            f"履约延期 {internal.get('delivery_delay_count', 0)} 次",
            f"发票匹配率 {_percent(internal.get('invoice_match_rate', 0))}",
            f"交付达成率 {_percent(internal.get('delivery_fulfillment_rate', 0))}",
        ],
        "财务质量": [
            f"应收余额 {_money(financial.get('receivable_amount', 0))}",
            f"逾期金额 {_money(financial.get('overdue_amount', 0))}",
            f"逾期率 {_percent(financial.get('overdue_rate', 0))}",
            f"平均回款天数 {financial.get('avg_collection_days', 0)} 天",
            f"额度使用率 {_percent(financial.get('limit_utilization_rate', 0))}",
        ],
        "科创能力": _tech_profile(tech),
    }
    profile["core_strengths"] = _core_strengths(counterparty, result)
    profile["core_risks"] = _core_risks(counterparty, result)
    profile["management_suggestions"] = _management_suggestions_for_counterparty(counterparty, result)
    return profile


def build_agent_timeline(counterparty: dict, result: dict) -> list[dict]:
    return [
        {
            "step": "资料接收",
            "owner": "AI Agent",
            "input": "企业名称、统一社会信用代码、申请额度、业务类型",
            "output": f"已创建 {counterparty['name']} 的评级任务",
            "human_boundary": "人工确认申请主体与业务背景是否一致",
        },
        {
            "step": "主体核验",
            "owner": "AI Agent",
            "input": "工商登记状态、成立年限、纳税信用",
            "output": "主体状态可继续" if counterparty.get("external", {}).get("registration_status") in {"存续", "在业"} else "主体状态异常",
            "human_boundary": "主体异常、名称不一致、疑似关联主体需人工确认",
        },
        {
            "step": "外部风险扫描",
            "owner": "AI Agent",
            "input": "司法、失信、行政处罚、经营异常、股权冻结",
            "output": _external_risk_summary(counterparty),
            "human_boundary": "重大诉讼、处罚性质、风险是否影响合作需人工判断",
        },
        {
            "step": "内部数据匹配",
            "owner": "AI Agent",
            "input": "订单、发票、履约、退货、合同争议、应收逾期",
            "output": _internal_summary(counterparty),
            "human_boundary": "内部数据缺失或口径冲突时由业务部门补充说明",
        },
        {
            "step": "评分卡计算",
            "owner": "AI Agent",
            "input": "模型版本、评分指标、权重、加减分项",
            "output": f"总分 {result['total_score']}，评级 {result['rating']}，分层 {result['risk_segment']}",
            "human_boundary": "模型只给出建议，不替代审批责任人",
        },
        {
            "step": "强规则判断",
            "owner": "AI Agent",
            "input": "主体异常、失信、重大诉讼、履约异常等强规则",
            "output": _strong_rule_summary(result),
            "human_boundary": "命中强规则时必须复核证据和例外审批理由",
        },
        {
            "step": "额度策略",
            "owner": "AI Agent",
            "input": "申请额度、评分区间、强规则额度上限",
            "output": f"建议额度 {_money(result.get('suggested_limit', 0))}，建议账期 {result.get('suggested_payment_term_days', 0)} 天",
            "human_boundary": "额度、账期、担保条件由授权审批人最终确认",
        },
        {
            "step": "人工复核",
            "owner": "人工复核",
            "input": "评分解释、证据、报告、业务补充材料",
            "output": "需提交人工复核" if result.get("review_required") else "可按模型建议进入后续流程",
            "human_boundary": "人工复核意见、调整原因和审批记录必须留痕",
        },
    ]


def _management_actions(
    results: list[dict],
    requested_limit_total: int | float,
    suggested_limit_total: int | float,
    review_required: list[dict],
    high_risk: list[dict],
    strong_rule_hits: list[dict],
) -> list[dict]:
    return [
        {
            "action": "额度暴露复核",
            "reason": f"申请额度合计 {_money(requested_limit_total)}，模型建议额度合计 {_money(suggested_limit_total)}",
            "next_step": "对额度压降较大的客商逐户查看原因",
        },
        {
            "action": "待复核客商处理",
            "reason": f"{len(review_required)} 家客商需要人工复核",
            "next_step": "优先处理强规则命中、申请额度高、关键客商",
        },
        {
            "action": "高风险客商管控",
            "reason": f"{len(high_risk)} 家客商处于重点监控/禁入/不予额度分层",
            "next_step": "触发准入限制、额度冻结或补充尽调",
        },
        {
            "action": "强规则证据核验",
            "reason": f"共命中 {len(strong_rule_hits)} 条强规则",
            "next_step": "核验工商、司法、履约证据并形成审计留痕",
        },
    ]


def _management_suggestions_for_counterparty(counterparty: dict, result: dict) -> list[str]:
    suggestions = []
    if result.get("review_required"):
        suggestions.append("进入人工复核队列，审批人需填写调整依据。")
    if result.get("strong_rule_hits"):
        suggestions.append("优先核验强规则命中证据，必要时限制准入或冻结额度。")
    if result.get("suggested_limit", 0) < counterparty.get("requested_limit", 0):
        suggestions.append("建议额度低于申请额度，应向业务说明额度压降原因。")
    if result.get("rating") in {"AA", "AAA"}:
        suggestions.append("可纳入优质客商池，按季度监控外部风险和履约变化。")
    if not suggestions:
        suggestions.append("按模型建议进入后续准入流程，并保留本次评级证据。")
    return suggestions


def _core_strengths(counterparty: dict, result: dict) -> list[str]:
    strengths = []
    external = counterparty.get("external", {})
    internal = counterparty.get("internal", {})
    tech = counterparty.get("tech_enterprise", {})
    if external.get("registration_status") in {"存续", "在业"} and external.get("dishonesty_count", 0) == 0:
        strengths.append("主体状态正常，未发现失信记录。")
    if internal.get("invoice_match_rate", 0) >= 0.95 and internal.get("delivery_fulfillment_rate", 0) >= 0.95:
        strengths.append("内部履约与发票匹配表现较稳定。")
    if tech and (tech.get("invention_patent_count", 0) > 0 or tech.get("software_copyright_count", 0) > 0):
        strengths.append("知识产权和技术资产能够支撑科创评分。")
    if tech and (tech.get("known_vc_invested") or tech.get("industrial_investor_invested")):
        strengths.append("存在优质投资机构或产业投资者背书。")
    if result.get("rating") in {"AA", "AAA"}:
        strengths.append("模型评级位于优先支持区间。")
    return strengths or ["暂未形成明显优势，需要补充业务材料和外部证据。"]


def _core_risks(counterparty: dict, result: dict) -> list[str]:
    risks = []
    external = counterparty.get("external", {})
    internal = counterparty.get("internal", {})
    financial = counterparty.get("financial", {})
    if external.get("major_litigation_amount", 0) > 0:
        risks.append(f"存在诉讼金额暴露：{_money(external.get('major_litigation_amount', 0))}。")
    if external.get("admin_penalty_count", 0) > 0 or external.get("operating_abnormal_count", 0) > 0:
        risks.append("存在行政处罚或经营异常记录，需判断对合作影响。")
    if internal.get("delivery_delay_count", 0) > 0 or internal.get("contract_dispute_count", 0) > 0:
        risks.append("内部履约存在延期或合同争议记录。")
    if financial.get("overdue_rate", 0) > 0.1:
        risks.append(f"逾期率达到 {_percent(financial.get('overdue_rate', 0))}，需关注回款质量。")
    if result.get("strong_rule_hits"):
        risks.append("命中强规则，必须形成复核意见和审批留痕。")
    return risks or ["未发现影响本次准入的核心风险。"]


def _tech_profile(tech: dict) -> list[str]:
    if not tech:
        return ["非科创评分模板，未采集科创专项字段。"]
    return [
        f"软件著作权 {tech.get('software_copyright_count', 0)} 项，发明专利 {tech.get('invention_patent_count', 0)} 项，实用新型 {tech.get('utility_model_patent_count', 0)} 项",
        f"专精特新级别：{_specialized_level(tech.get('specialized_new_enterprise_level', 'none'))}",
        f"三年研发费用/营收：{_percent(tech.get('rd_expense_revenue_ratio_3y', 0))}",
        f"核心研发人员占比：{_percent(tech.get('rd_staff_ratio', 0))}",
        f"核心团队持股比例：{_percent(tech.get('core_team_shareholding_ratio', 0))}",
    ]


def _watch_reason(result: dict) -> str:
    if result.get("strong_rule_hits"):
        return "命中强规则"
    if result.get("review_required"):
        return "模型要求人工复核"
    return result.get("risk_segment", "风险分层关注")


def _external_risk_summary(counterparty: dict) -> str:
    external = counterparty.get("external", {})
    return (
        f"司法案件 {external.get('legal_cases_count', 0)} 条，"
        f"重大诉讼 {_money(external.get('major_litigation_amount', 0))}，"
        f"失信 {external.get('dishonesty_count', 0)} 条"
    )


def _internal_summary(counterparty: dict) -> str:
    internal = counterparty.get("internal", {})
    financial = counterparty.get("financial", {})
    return (
        f"近 12 月订单 {internal.get('orders_12m', 0)} 笔，"
        f"履约延期 {internal.get('delivery_delay_count', 0)} 次，"
        f"逾期率 {_percent(financial.get('overdue_rate', 0))}"
    )


def _strong_rule_summary(result: dict) -> str:
    hits = result.get("strong_rule_hits", [])
    if not hits:
        return "未命中强规则"
    return "；".join(f"{hit['rule_id']} {hit['rule_name']}" for hit in hits)


def _count_by(items: list[dict], field: str) -> dict:
    counts: dict[str, int] = {}
    for item in items:
        key = item.get(field, "-")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _money(value: int | float) -> str:
    return f"{value:,.0f} 元"


def _percent(value: float) -> str:
    return f"{value:.0%}"


def _specialized_level(value: str) -> str:
    return {
        "national": "国家级",
        "provincial": "省级",
        "municipal": "市级",
        "none": "未认定",
    }.get(value, value)
