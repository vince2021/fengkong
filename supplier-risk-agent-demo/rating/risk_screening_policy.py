from __future__ import annotations

from copy import deepcopy

from rating.enterprise_indicator_pool import evaluate_indicator_pool


DEFAULT_RISK_SCREENING_POLICY = {
    "enabled": True,
    "aggregation": "most_restrictive",
    "rules": [
        {
            "id": "RSP-DATA-GAP",
            "name": "风险指标数据完整度不足",
            "enabled": True,
            "metric": "completeness",
            "operator": "<",
            "value": 0.75,
            "action": {
                "rating_notch_down": 0,
                "limit_cap_ratio": 0.8,
                "term_cap_days": 60,
                "access_strategy": "人工复核",
                "monitoring_frequency": "月度",
            },
        },
        {
            "id": "RSP-ELEVATED",
            "name": "企业风险筛查分偏低",
            "enabled": True,
            "metric": "normalized_score",
            "operator": "<",
            "value": 60,
            "action": {
                "rating_notch_down": 1,
                "limit_cap_ratio": 0.6,
                "term_cap_days": 45,
                "access_strategy": "限制准入",
                "monitoring_frequency": "月度",
            },
        },
        {
            "id": "RSP-CRITICAL",
            "name": "企业风险关键指标命中",
            "enabled": True,
            "metric": "critical_indicator_count",
            "operator": ">=",
            "value": 1,
            "action": {
                "rating_notch_down": 1,
                "limit_cap_ratio": 0.5,
                "term_cap_days": 30,
                "access_strategy": "限制准入",
                "monitoring_frequency": "月度",
            },
        },
        {
            "id": "RSP-SEVERE",
            "name": "企业风险筛查严重异常",
            "enabled": True,
            "metric": "normalized_score",
            "operator": "<",
            "value": 35,
            "action": {
                "rating_notch_down": 2,
                "limit_cap_ratio": 0,
                "term_cap_days": 0,
                "access_strategy": "禁入",
                "monitoring_frequency": "实时监控",
            },
        },
    ],
}

SUPPORTED_METRICS = {"normalized_score", "completeness", "critical_indicator_count", "missing_count"}
SUPPORTED_OPERATORS = {"<", "<=", ">", ">=", "=="}
ACCESS_SEVERITY = {"正常准入": 0, "优先准入": 0, "审慎准入": 1, "人工复核": 2, "限制准入": 3, "禁入": 4}
MONITORING_SEVERITY = {"年度": 0, "半年度": 1, "季度": 2, "月度": 3, "周度": 4, "实时监控": 5}


def get_risk_screening_policy(config: dict) -> dict:
    configured = config.get("risk_screening_policy")
    return deepcopy(configured if isinstance(configured, dict) else DEFAULT_RISK_SCREENING_POLICY)


def apply_risk_screening_policy(counterparty: dict, config: dict, result: dict) -> dict:
    """Apply a post-score strategy layer that may only tighten the base conclusion."""
    if not result.get("ok"):
        return result

    screening = evaluate_indicator_pool(counterparty, config)
    policy = get_risk_screening_policy(config)
    metrics = {
        "normalized_score": screening["normalized_score"],
        "completeness": screening["completeness"],
        "critical_indicator_count": sum(
            item["data_status"] == "已取得" and float(item["score"]) <= 1 for item in screening["details"]
        ),
        "missing_count": screening["missing_count"],
    }
    before = _strategy_snapshot(result)
    hits = []
    if policy.get("enabled", True):
        for rule in policy.get("rules", []):
            if not isinstance(rule, dict) or not rule.get("enabled", True):
                continue
            metric = rule.get("metric")
            operator = rule.get("operator")
            if metric not in metrics or operator not in SUPPORTED_OPERATORS:
                continue
            actual = metrics[metric]
            expected = rule.get("value")
            if _matches(float(actual), operator, float(expected)):
                hits.append(
                    {
                        "id": rule.get("id", ""),
                        "name": rule.get("name", rule.get("id", "未命名策略")),
                        "metric": metric,
                        "operator": operator,
                        "value": expected,
                        "actual": actual,
                        "expression": f"{metric} {operator} {expected:g}（实际 {actual:g}）",
                        "action": deepcopy(rule.get("action", {})),
                    }
                )

    adjusted = dict(result)
    if hits:
        _tighten_strategy(adjusted, counterparty, config, hits)
    after = _strategy_snapshot(adjusted)
    adjusted["enterprise_risk_screening"] = screening
    adjusted["risk_screening_policy"] = {
        "enabled": bool(policy.get("enabled", True)),
        "aggregation": policy.get("aggregation", "most_restrictive"),
        "metrics": metrics,
        "hits": hits,
        "before": before,
        "after": after,
        "changed": before != after,
        "formula": "主模型结论 → 企业风险指标池筛查 → 命中策略按最严格结果收紧；评级、额度、账期和准入结论均不得放宽",
    }
    return adjusted


def validate_risk_screening_policy(policy: object) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(policy, dict):
        return ["企业风险贷策必须是对象"], warnings
    rules = policy.get("rules")
    if not isinstance(rules, list) or not rules:
        return ["企业风险贷策至少需要一条规则"], warnings
    ids = []
    for rule in rules:
        if not isinstance(rule, dict):
            errors.append("企业风险贷策规则必须是对象")
            continue
        rule_id = str(rule.get("id", ""))
        ids.append(rule_id)
        if not rule_id:
            errors.append("企业风险贷策规则必须包含编号")
        if rule.get("metric") not in SUPPORTED_METRICS:
            errors.append(f"贷策规则 {rule_id or '未知'} 的指标无效")
        if rule.get("operator") not in SUPPORTED_OPERATORS:
            errors.append(f"贷策规则 {rule_id or '未知'} 的运算符无效")
        try:
            float(rule.get("value"))
        except (TypeError, ValueError):
            errors.append(f"贷策规则 {rule_id or '未知'} 的阈值必须是数值")
        action = rule.get("action")
        if not isinstance(action, dict):
            errors.append(f"贷策规则 {rule_id or '未知'} 必须配置收紧动作")
            continue
        try:
            notch = int(action.get("rating_notch_down", 0))
            ratio = float(action.get("limit_cap_ratio", 1))
            days = int(action.get("term_cap_days", 3650))
            if notch < 0 or notch > 3:
                errors.append(f"贷策规则 {rule_id or '未知'} 的评级下调档数必须介于 0 至 3")
            if ratio < 0 or ratio > 1:
                errors.append(f"贷策规则 {rule_id or '未知'} 的额度上限比例必须介于 0% 至 100%")
            if days < 0 or days > 3650:
                errors.append(f"贷策规则 {rule_id or '未知'} 的账期上限必须介于 0 至 3650 天")
        except (TypeError, ValueError):
            errors.append(f"贷策规则 {rule_id or '未知'} 的收紧动作数值无效")
        if action.get("access_strategy") not in ACCESS_SEVERITY:
            errors.append(f"贷策规则 {rule_id or '未知'} 的准入策略无效")
        if action.get("monitoring_frequency") not in MONITORING_SEVERITY:
            errors.append(f"贷策规则 {rule_id or '未知'} 的监控频率无效")
    if len(ids) != len(set(ids)):
        errors.append("企业风险贷策规则编号不能重复")
    if not any(rule.get("enabled", True) for rule in rules if isinstance(rule, dict)):
        warnings.append("企业风险贷策没有启用规则，筛查结果不会影响最终授信结论")
    return errors, warnings


def _tighten_strategy(result: dict, counterparty: dict, config: dict, hits: list[dict]) -> None:
    actions = [hit["action"] for hit in hits]
    notch = max(int(action.get("rating_notch_down", 0)) for action in actions)
    cap_ratio = min(float(action.get("limit_cap_ratio", 1)) for action in actions)
    term_cap = min(int(action.get("term_cap_days", 3650)) for action in actions)
    access = max((str(action.get("access_strategy", "正常准入")) for action in actions), key=lambda item: ACCESS_SEVERITY.get(item, -1))
    monitoring = max((str(action.get("monitoring_frequency", "年度")) for action in actions), key=lambda item: MONITORING_SEVERITY.get(item, -1))

    mapping = _downgraded_mapping(result.get("rating", ""), notch, config.get("strategy_mapping", []))
    if mapping:
        result["rating"] = mapping["rating"]
        result["risk_segment"] = mapping.get("risk_segment", result.get("risk_segment"))
        if "limit_multiplier" in mapping:
            result["suggested_limit"] = min(
                result["suggested_limit"], int(counterparty.get("requested_limit", 0) * float(mapping["limit_multiplier"]))
            )
        if "payment_term_days" in mapping:
            result["suggested_payment_term_days"] = min(result["suggested_payment_term_days"], int(mapping["payment_term_days"]))
        mapped_access = str(mapping.get("access_strategy", result.get("access_strategy", "正常准入")))
        if ACCESS_SEVERITY.get(mapped_access, 0) > ACCESS_SEVERITY.get(result.get("access_strategy", "正常准入"), 0):
            result["access_strategy"] = mapped_access
        mapped_monitoring = str(mapping.get("monitoring_frequency", result.get("monitoring_frequency", "年度")))
        if MONITORING_SEVERITY.get(mapped_monitoring, 0) > MONITORING_SEVERITY.get(result.get("monitoring_frequency", "年度"), 0):
            result["monitoring_frequency"] = mapped_monitoring

    result["suggested_limit"] = min(result["suggested_limit"], int(counterparty.get("requested_limit", 0) * cap_ratio))
    result["suggested_payment_term_days"] = min(result["suggested_payment_term_days"], term_cap)
    if ACCESS_SEVERITY.get(access, 0) > ACCESS_SEVERITY.get(result.get("access_strategy", "正常准入"), 0):
        result["access_strategy"] = access
    if MONITORING_SEVERITY.get(monitoring, 0) > MONITORING_SEVERITY.get(result.get("monitoring_frequency", "年度"), 0):
        result["monitoring_frequency"] = monitoring
    result["review_required"] = bool(result.get("review_required")) or bool(hits)


def _downgraded_mapping(rating: str, notch: int, mappings: list[dict]) -> dict | None:
    if not mappings:
        return None
    ordered = sorted(mappings, key=lambda item: float(item.get("score_min", 0)), reverse=True)
    ratings = []
    for item in ordered:
        if item.get("rating") not in ratings:
            ratings.append(item.get("rating"))
    if rating not in ratings:
        return None
    target = ratings[min(ratings.index(rating) + notch, len(ratings) - 1)]
    return next((item for item in ordered if item.get("rating") == target), None)


def _strategy_snapshot(result: dict) -> dict:
    return {
        "rating": result.get("rating"),
        "risk_segment": result.get("risk_segment"),
        "access_strategy": result.get("access_strategy"),
        "suggested_limit": result.get("suggested_limit", 0),
        "suggested_payment_term_days": result.get("suggested_payment_term_days", 0),
        "monitoring_frequency": result.get("monitoring_frequency"),
        "review_required": bool(result.get("review_required")),
    }


def _matches(actual: float, operator: str, expected: float) -> bool:
    return {
        "<": actual < expected,
        "<=": actual <= expected,
        ">": actual > expected,
        ">=": actual >= expected,
        "==": actual == expected,
    }[operator]
