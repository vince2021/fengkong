from __future__ import annotations


INDUSTRY_LABELS = {
    "general": "通用",
    "pharma": "医药流通",
    "manufacturing": "制造业",
    "construction": "工程建筑",
    "logistics": "物流供应链",
    "tech_enterprise": "科创企业",
}


def build_sample_scenarios(counterparties: list[dict], results: list[dict]) -> list[dict]:
    counterparty_by_id = {item["id"]: item for item in counterparties}
    rows = []
    for result in results:
        if not result.get("ok"):
            continue
        counterparty = counterparty_by_id.get(result["counterparty_id"])
        if not counterparty:
            continue
        rows.append(
            {
                "样本企业": counterparty["name"],
                "行业": INDUSTRY_LABELS.get(counterparty.get("industry"), counterparty.get("industry", "-")),
                "类型": "客户" if counterparty.get("counterparty_type") == "customer" else "供应商",
                "评级": result["rating"],
                "风险分层": result["risk_segment"],
                "准入策略": result["access_strategy"],
                "风险故事": _risk_story(counterparty, result),
                "演示用途": _demo_use_case(result),
            }
        )
    return rows


def count_scenarios_by_industry(scenarios: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for item in scenarios:
        industry = item["行业"]
        counts[industry] = counts.get(industry, 0) + 1
    return counts


def _risk_story(counterparty: dict, result: dict) -> str:
    external = counterparty.get("external", {})
    internal = counterparty.get("internal", {})
    financial = counterparty.get("financial", {})
    stories = []
    if external.get("dishonesty_count", 0) > 0 or external.get("registration_status") not in {"存续", "在业"}:
        stories.append("主体或失信风险触发底线规则")
    if external.get("major_litigation_amount", 0) >= 5000000:
        stories.append("重大诉讼暴露较高")
    if internal.get("delivery_delay_count", 0) >= 3 or internal.get("contract_dispute_count", 0) >= 2:
        stories.append("内部履约或合同争议需要复核")
    if financial.get("overdue_rate", 0) >= 0.1:
        stories.append("应收逾期和额度使用压力较高")
    if result.get("rating") in {"AA", "AAA"} and not stories:
        stories.append("主体、履约和财务表现较稳定")
    if not stories:
        stories.append("适合展示常规准入和持续监控")
    return "；".join(stories)


def _demo_use_case(result: dict) -> str:
    if result.get("access_strategy") == "禁入" or result.get("rating") == "D":
        return "展示强规则禁入和人工复核"
    if result.get("review_required"):
        return "展示人工复核、额度压降和证据解释"
    if result.get("rating") in {"AA", "AAA"}:
        return "展示优质客商自动准入"
    return "展示普通准入和风险分层"
