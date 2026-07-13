from __future__ import annotations


def build_detail_workbench(counterparty: dict, result: dict, profile: dict, timeline: list[dict]) -> dict:
    return {
        "dossier": _build_dossier(counterparty, result),
        "evidence_groups": _build_evidence_groups(counterparty, result, profile),
        "approval_panel": _build_approval_panel(counterparty, result, profile),
        "audit_timeline": _build_audit_timeline(result, timeline),
    }


def _build_dossier(counterparty: dict, result: dict) -> dict:
    external = counterparty.get("external", {})
    internal = counterparty.get("internal", {})
    financial = counterparty.get("financial", {})
    return {
        "企业名称": counterparty["name"],
        "统一社会信用代码": counterparty.get("credit_code", "-"),
        "客商类型": "客户" if counterparty.get("counterparty_type") == "customer" else "供应商",
        "合作状态": counterparty.get("cooperation_status", "-"),
        "是否关键客商": "是" if counterparty.get("is_key_counterparty") else "否",
        "登记状态": external.get("registration_status", "-"),
        "成立年限": f"{external.get('established_years', '-')} 年",
        "申请额度": _money(counterparty.get("requested_limit", 0)),
        "当前额度": _money(counterparty.get("current_limit", 0)),
        "模型建议额度": _money(result.get("suggested_limit", 0)),
        "当前评级": counterparty.get("current_rating", "-"),
        "模型评级": result.get("rating", "-"),
        "逾期率": _percent(financial.get("overdue_rate", 0)),
        "合作年限": f"{internal.get('cooperation_years', 0)} 年",
    }


def _build_evidence_groups(counterparty: dict, result: dict, profile: dict) -> list[dict]:
    return [
        {
            "title": "外部风险证据",
            "items": profile["外部风险"],
            "conclusion": _risk_conclusion(profile["core_risks"], "外部"),
        },
        {
            "title": "内部履约证据",
            "items": profile["内部履约"],
            "conclusion": _risk_conclusion(profile["core_risks"], "履约"),
        },
        {
            "title": "财务质量证据",
            "items": profile["财务质量"],
            "conclusion": _risk_conclusion(profile["core_risks"], "逾期"),
        },
        {
            "title": "科创评价证据",
            "items": profile["科创能力"],
            "conclusion": _tech_conclusion(counterparty),
        },
        {
            "title": "评分解释证据",
            "items": _score_explanations(result),
            "conclusion": f"模型总分 {result['total_score']}，评级 {result['rating']}，策略 {result['access_strategy']}",
        },
    ]


def _build_approval_panel(counterparty: dict, result: dict, profile: dict) -> dict:
    requested_limit = counterparty.get("requested_limit", 0)
    suggested_limit = result.get("suggested_limit", 0)
    return {
        "建议动作": _approval_action(result),
        "模型准入策略": result.get("access_strategy", "-"),
        "模型评级": result.get("rating", "-"),
        "风险分层": result.get("risk_segment", "-"),
        "申请额度": _money(requested_limit),
        "建议额度": _money(suggested_limit),
        "额度压降": _money(max(requested_limit - suggested_limit, 0)),
        "建议账期": f"{result.get('suggested_payment_term_days', 0)} 天" if result.get("suggested_payment_term_days") else "预付款",
        "需人工复核": bool(result.get("review_required")),
        "强规则命中": len(result.get("strong_rule_hits", [])),
        "审批关注点": "；".join(profile["core_risks"][:3]),
    }


def _build_audit_timeline(result: dict, timeline: list[dict]) -> list[dict]:
    rows = [
        {
            "节点": item["step"],
            "执行方": item["owner"],
            "输出": item["output"],
            "留痕内容": item["human_boundary"],
        }
        for item in timeline
    ]
    rows.append(
        {
            "节点": "报告生成",
            "执行方": "系统",
            "输出": f"生成 {result['counterparty_name']} 的信用评级审核报告",
            "留痕内容": "记录模型版本、评分结论、人工复核意见和导出时间",
        }
    )
    return rows


def _score_explanations(result: dict) -> list[str]:
    rows = []
    for item in result.get("indicator_explanations", [])[:8]:
        if "score" in item:
            rows.append(f"{item['category']}｜{item['indicator']}：{item['score']} 分")
        else:
            rows.append(f"{item['dimension_label']}｜{item['indicator']}：扣分 {item['points']}")
    return rows or ["暂无评分解释"]


def _approval_action(result: dict) -> str:
    if result.get("access_strategy") in {"禁入", "不建议准入"}:
        return "建议拒绝或不予准入"
    if result.get("review_required"):
        return "提交人工复核"
    if result.get("rating") in {"AA", "AAA"}:
        return "建议准入并纳入优质客商池"
    return "建议按模型策略准入并持续监控"


def _risk_conclusion(risks: list[str], keyword: str) -> str:
    matched = [item for item in risks if keyword in item]
    return matched[0] if matched else "未发现该维度的突出风险。"


def _tech_conclusion(counterparty: dict) -> str:
    tech = counterparty.get("tech_enterprise")
    if not tech:
        return "非科创评分模板，未采集科创专项字段。"
    if tech.get("specialized_new_enterprise_level") in {"national", "provincial"}:
        return "具备专精特新或创新资质，可作为正向支持依据。"
    return "科创资质需结合知识产权、研发投入和订单背书综合判断。"


def _money(value: int | float) -> str:
    return f"{value:,.0f} 元"


def _percent(value: float) -> str:
    return f"{value:.0%}"
