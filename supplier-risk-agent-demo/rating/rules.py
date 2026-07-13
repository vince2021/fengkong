from __future__ import annotations

from collections.abc import Iterable

def get_field_value(data: dict, field_path: str):
    current = data
    for part in field_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def resolve_value(config: dict, value_ref: str | None, fallback=None):
    if not value_ref:
        return fallback
    return get_field_value(config, value_ref)


def evaluate_condition(counterparty: dict, config: dict, condition: dict) -> bool:
    left = get_field_value(counterparty, condition["field"])
    right = condition.get("value")
    if "value_ref" in condition:
        right = resolve_value(config, condition["value_ref"], right)

    operator = condition["operator"]

    if operator == ">":
        return left > right
    if operator == ">=":
        return left >= right
    if operator == "<":
        return left < right
    if operator == "<=":
        return left <= right
    if operator == "==":
        return left == right
    if operator == "!=":
        return left != right
    if operator == "in":
        return _contains(right, left)
    if operator == "not_in":
        return not _contains(right, left)

    raise ValueError(f"Unsupported operator: {operator}")


def evaluate_rule(counterparty: dict, config: dict, rule: dict) -> dict:
    if not rule.get("enabled", True):
        return {
            "hit": False,
            "rule_id": rule["id"],
            "rule_name": rule["name"],
            "matched_conditions": [],
            "action": rule["action"],
        }

    condition_results = []
    for condition in rule["conditions"]:
        matched = evaluate_condition(counterparty, config, condition)
        condition_results.append(
            {
                "label": condition["label"],
                "field": condition["field"],
                "operator": condition["operator"],
                "matched": matched,
                "actual_value": get_field_value(counterparty, condition["field"]),
            }
        )

    relation = rule.get("condition_relation", "all")
    if relation == "all":
        hit = all(item["matched"] for item in condition_results)
    elif relation == "any":
        hit = any(item["matched"] for item in condition_results)
    else:
        raise ValueError(f"Unsupported condition relation: {relation}")

    return {
        "hit": hit,
        "rule_id": rule["id"],
        "rule_name": rule["name"],
        "relation": relation,
        "matched_conditions": [item for item in condition_results if item["matched"]],
        "all_conditions": condition_results,
        "action": rule["action"],
    }


def evaluate_strong_rules(counterparty: dict, config: dict) -> list[dict]:
    hits = []
    for rule in config.get("strong_rules", []):
        result = evaluate_rule(counterparty, config, rule)
        if result["hit"]:
            hits.append(result)
    return hits


def apply_rule_actions(base_strategy: dict, rule_hits: list[dict], counterparty: dict) -> dict:
    final_strategy = dict(base_strategy)

    for hit in rule_hits:
        action = hit["action"]

        if "rating_override" in action:
            final_strategy["rating"] = action["rating_override"]

        if "risk_segment_override" in action:
            final_strategy["risk_segment"] = _pick_higher_priority(
                final_strategy["risk_segment"],
                action["risk_segment_override"],
                RISK_SEGMENT_PRIORITY,
            )

        if "access_strategy" in action:
            final_strategy["access_strategy"] = _pick_higher_priority(
                final_strategy["access_strategy"],
                action["access_strategy"],
                ACCESS_STRATEGY_PRIORITY,
            )

        if "limit_multiplier_cap" in action:
            cap_limit = int(counterparty.get("requested_limit", 0) * action["limit_multiplier_cap"])
            final_strategy["suggested_limit"] = min(final_strategy["suggested_limit"], cap_limit)

        if "payment_term_days_cap" in action:
            final_strategy["payment_term_days"] = min(final_strategy["payment_term_days"], action["payment_term_days_cap"])

        if action.get("review_required"):
            final_strategy["review_required"] = True

    return final_strategy


ACCESS_STRATEGY_PRIORITY = {
    "自动准入": 1,
    "准入": 2,
    "限制准入": 3,
    "审慎准入": 4,
    "人工复核": 5,
    "不建议准入": 6,
    "禁入": 6,
}

RISK_SEGMENT_PRIORITY = {
    "核心客商": 1,
    "优质客商": 2,
    "普通客商": 3,
    "关注客商": 4,
    "重点监控": 5,
    "高风险客商": 6,
    "不予额度": 7,
    "禁入客商": 7,
}


def _pick_higher_priority(current: str, incoming: str, priority: dict[str, int]) -> str:
    current_priority = priority.get(current, 0)
    incoming_priority = priority.get(incoming, 0)
    return incoming if incoming_priority > current_priority else current


def _contains(collection, value) -> bool:
    if isinstance(collection, str):
        return value == collection
    if isinstance(collection, Iterable):
        return value in collection
    return value == collection
