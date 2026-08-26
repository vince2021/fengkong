"""Rule condition evaluation and conservative action merging."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from rating.expression_engine import (
    ExpressionSecurityError,
    ExpressionSyntaxError,
    evaluate_expression,
)


_RATING_SEVERITY = {
    "AAA": 0,
    "AA": 1,
    "A": 2,
    "BBB": 3,
    "BB": 4,
    "B": 5,
    "C": 6,
    "D": 7,
}

_ACCESS_STRATEGY_SEVERITY = {
    "自动准入": 0,
    "优先准入": 0,
    "正常准入": 1,
    "标准准入": 1,
    "准入": 1,
    "限制准入": 2,
    "审慎准入": 3,
    "人工复核": 4,
    "不建议准入": 5,
    "禁入": 5,
}

_RISK_SEGMENT_SEVERITY = {
    "核心客商": 0,
    "优质客商": 1,
    "优先支持": 1,
    "正常客商": 2,
    "普通客商": 2,
    "重点支持": 2,
    "关注客商": 3,
    "审慎支持": 4,
    "重点监控": 5,
    "高风险客商": 6,
    "不予额度": 7,
    "禁入客商": 7,
}

_SEVERITY = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
    "低": 0,
    "中": 1,
    "高": 2,
    "重大风险": 3,
}

_SUPPORTED_STRATEGIES = {"first_hit", "all_hits", "most_restrictive"}


def flatten_context(data: dict, prefix: str = "") -> dict:
    """Flatten nested mappings into expression-safe underscore names."""
    result: dict = {}
    for key, value in data.items():
        flat_key = f"{prefix}_{key}" if prefix else str(key)
        if isinstance(value, dict):
            result.update(flatten_context(value, flat_key))
        else:
            result[flat_key] = value
    return result


def _compare(value: Any, operator: str, threshold: Any) -> bool:
    if operator in ("", "bool", None):
        return bool(value)
    try:
        if operator == "==":
            return value == threshold
        if operator == "!=":
            return value != threshold
        if operator == ">":
            return value > threshold
        if operator == ">=":
            return value >= threshold
        if operator == "<":
            return value < threshold
        if operator == "<=":
            return value <= threshold
    except (ArithmeticError, TypeError, ValueError):
        return False
    return False


def evaluate_rule_conditions(
    rule: Any, context: dict
) -> tuple[bool, list[dict]]:
    """Evaluate one rule and return its trigger state and condition evidence."""
    flat_context = flatten_context(context)
    conditions = getattr(rule, "conditions_json", None) or []
    details = []

    for condition in conditions:
        expression = condition.get("expression", "")
        operator = condition.get("operator", "bool")
        threshold = condition.get("value")
        try:
            actual_value = evaluate_expression(expression, flat_context)
        except (
            ExpressionSecurityError,
            ExpressionSyntaxError,
            ArithmeticError,
            KeyError,
            TypeError,
            ValueError,
        ):
            actual_value = None

        matched = (
            _compare(actual_value, operator, threshold)
            if actual_value is not None
            else False
        )
        details.append(
            {
                "expression": expression,
                "actual_value": actual_value,
                "threshold": threshold,
                "operator": operator,
                "matched": matched,
                "label": condition.get("label", ""),
            }
        )

    relation = getattr(rule, "condition_relation", None) or "all"
    if not details:
        triggered = False
    elif relation == "all":
        triggered = all(item["matched"] for item in details)
    elif relation == "any":
        triggered = any(item["matched"] for item in details)
    else:
        triggered = False
    return triggered, details


def evaluate_rule_set(rule_set: Any, rules: list, context: dict) -> list[dict]:
    """Evaluate enabled rules explicitly referenced by a rule set."""
    strategy = (
        getattr(rule_set, "evaluation_strategy", None) or "most_restrictive"
    )
    if strategy not in _SUPPORTED_STRATEGIES:
        return []

    referenced_codes = set(getattr(rule_set, "rule_codes", None) or [])
    candidates = [
        rule
        for rule in rules
        if getattr(rule, "code", None) in referenced_codes
        and getattr(rule, "enabled", True)
    ]
    candidates.sort(key=_rule_sort_key)

    triggered = []
    for rule in candidates:
        hit, details = evaluate_rule_conditions(rule, context)
        if hit:
            triggered.append({"rule": rule, "details": details})
            if strategy == "first_hit":
                break
    return triggered


def _rule_sort_key(rule: Any) -> tuple[int, str]:
    try:
        priority = int(getattr(rule, "priority", 999))
    except (TypeError, ValueError):
        priority = 999
    return priority, str(getattr(rule, "code", ""))


def apply_rule_actions(triggered: list[dict], context: dict) -> dict:
    """Apply all triggered actions without allowing a previous result to relax."""
    result = deepcopy(context.get("current_result", {}))
    base_limit = _number(result.get("suggested_limit"))
    limit_caps: list[float] = []
    term_caps: list[int] = []
    score_adjustments: list[float] = []

    for item in triggered:
        rule = item.get("rule")
        for action in getattr(rule, "actions_json", None) or []:
            action_type = action.get("type", "")
            value = action.get("value")

            if action_type == "rating_override":
                _apply_ordered_value(result, "rating", value, _RATING_SEVERITY)
            elif action_type == "access_strategy":
                _apply_ordered_value(
                    result,
                    "access_strategy",
                    value,
                    _ACCESS_STRATEGY_SEVERITY,
                )
            elif action_type == "risk_segment_override":
                _apply_ordered_value(
                    result,
                    "risk_segment",
                    value,
                    _RISK_SEGMENT_SEVERITY,
                )
            elif action_type == "limit_multiplier_cap":
                cap = _number(value)
                if cap is not None and 0 <= cap <= 1:
                    limit_caps.append(cap)
            elif action_type == "payment_term_days_cap":
                cap = _integer(value)
                if cap is not None and cap >= 0:
                    term_caps.append(cap)
            elif action_type == "review_required" and bool(value):
                result["review_required"] = True
            elif action_type == "score_adjustment":
                adjustment = _number(value)
                if adjustment is not None and adjustment < 0:
                    score_adjustments.append(adjustment)
            elif action_type == "severity":
                _apply_ordered_value(result, "max_severity", value, _SEVERITY)

    if base_limit is not None and limit_caps:
        result["suggested_limit"] = _preserve_number_type(
            result.get("suggested_limit"), base_limit * min(limit_caps)
        )

    if term_caps:
        _apply_term_cap(result, min(term_caps))

    if score_adjustments:
        current_score = _number(result.get("total_score"))
        if current_score is not None:
            result["total_score"] = current_score + sum(score_adjustments)

    return result


def _apply_ordered_value(
    result: dict, key: str, value: Any, severity: dict[str, int]
) -> None:
    incoming = str(value)
    if incoming not in severity:
        return
    current = str(result.get(key, ""))
    if severity[incoming] >= severity.get(current, -1):
        result[key] = incoming


def _apply_term_cap(result: dict, cap: int) -> None:
    if "suggested_payment_term_days" in result:
        current = _integer(result.get("suggested_payment_term_days"))
        result["suggested_payment_term_days"] = min(current, cap) if current is not None else cap
    elif "payment_term_days" in result:
        current = _integer(result.get("payment_term_days"))
        result["payment_term_days"] = min(current, cap) if current is not None else cap
    else:
        result["suggested_payment_term_days"] = cap


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


def _preserve_number_type(original: Any, value: float) -> int | float:
    return int(value) if isinstance(original, int) and not isinstance(original, bool) else value
