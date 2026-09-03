from __future__ import annotations

import re
from copy import deepcopy

from backend.model_validation import build_model_validation_report
from backend.repository import content_hash
from rating.scorecard import rate_counterparty
from rating.enterprise_indicator_pool import evaluate_indicator_pool, get_model_indicator_selection, validate_indicator_selection
from rating.risk_screening_policy import get_risk_screening_policy, validate_risk_screening_policy
from rating.governed_scorecard import validate_scorecard_binding


VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
SUPPORTED_OPERATORS = {">", ">=", "<", "<=", "==", "!=", "in", "not_in"}


def build_candidate_config(base: dict, payload: dict) -> dict:
    candidate = deepcopy(base)
    candidate["version"] = payload["candidate_version"].strip()
    candidate["weights"] = deepcopy(payload["weights"])
    candidate["thresholds"] = deepcopy(payload["thresholds"])
    candidate["strong_rules"] = deepcopy(payload["strong_rules"])
    candidate["strategy_mapping"] = deepcopy(payload.get("strategy_mapping") or base.get("strategy_mapping", []))
    requested_selection = payload.get("indicator_selection")
    candidate["indicator_selection"] = deepcopy(
        requested_selection if requested_selection is not None else get_model_indicator_selection(base)
    )
    candidate["risk_screening_policy"] = deepcopy(payload.get("risk_screening_policy") or get_risk_screening_policy(base))
    if "scorecard_binding" in payload:
        candidate["scorecard_binding"] = deepcopy(payload["scorecard_binding"])
    candidate["change_reason"] = payload["change_reason"].strip()
    candidate["status"] = "active"
    return candidate


def validate_and_assess(base: dict, candidate: dict, counterparties: list[dict], template_key: str, monitoring_dataset: dict | None = None) -> tuple[dict, dict]:
    errors: list[str] = []
    warnings: list[str] = []
    if not VERSION_PATTERN.fullmatch(str(candidate.get("version", ""))):
        errors.append("候选版本只能包含字母、数字、点、下划线和连字符，长度为 3 至 128")
    if candidate.get("version") == base.get("version"):
        errors.append("候选版本必须不同于当前生效版本")

    weights = candidate.get("weights")
    expected_dimensions = set(base.get("weights", {}))
    if not isinstance(weights, dict) or set(weights) != expected_dimensions:
        errors.append("权重字段必须与当前模型的风险维度完整一致")
    else:
        try:
            numeric_weights = {key: float(value) for key, value in weights.items()}
            if any(value < 0 or value > 1 for value in numeric_weights.values()):
                errors.append("单项权重必须介于 0% 与 100% 之间")
            if abs(sum(numeric_weights.values()) - 1) > 0.0001:
                errors.append(f"权重合计必须等于 100%，当前为 {sum(numeric_weights.values()):.2%}")
        except (TypeError, ValueError):
            errors.append("权重必须是数值")

    thresholds = candidate.get("thresholds")
    if not isinstance(thresholds, dict) or set(thresholds) != set(base.get("thresholds", {})):
        errors.append("阈值字段必须与当前模型保持一致")
    else:
        try:
            numeric_thresholds = {key: float(value) for key, value in thresholds.items()}
            invalid_negative = [
                key for key, value in numeric_thresholds.items()
                if float(base.get("thresholds", {}).get(key, 0)) >= 0 and value < 0
            ]
            if invalid_negative:
                errors.append(f"非负型阈值不能为负数：{','.join(invalid_negative)}")
        except (TypeError, ValueError):
            errors.append("阈值必须是数值")

    indicator_errors, indicator_warnings = validate_indicator_selection(candidate.get("indicator_selection"))
    errors.extend(indicator_errors)
    warnings.extend(indicator_warnings)
    policy_errors, policy_warnings = validate_risk_screening_policy(candidate.get("risk_screening_policy"))
    errors.extend(policy_errors)
    warnings.extend(policy_warnings)
    errors.extend(validate_scorecard_binding(candidate.get("scorecard_binding")))

    rules = candidate.get("strong_rules")
    if not isinstance(rules, list):
        errors.append("强规则配置必须是列表")
    else:
        rule_ids = [str(rule.get("id", "")) for rule in rules if isinstance(rule, dict)]
        if len(rule_ids) != len(rules) or any(not rule_id for rule_id in rule_ids):
            errors.append("每条强规则必须包含唯一规则编号")
        elif len(set(rule_ids)) != len(rule_ids):
            errors.append("强规则编号不能重复")
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            if rule.get("condition_relation", "all") not in {"all", "any"}:
                errors.append(f"规则 {rule.get('id', '未知')} 的条件关系无效")
            conditions = rule.get("conditions")
            if not isinstance(conditions, list) or not conditions:
                errors.append(f"规则 {rule.get('id', '未知')} 至少需要一个条件")
                continue
            for condition in conditions:
                if condition.get("operator") not in SUPPORTED_OPERATORS or not condition.get("field"):
                    errors.append(f"规则 {rule.get('id', '未知')} 存在无效字段或运算符")

    mappings = candidate.get("strategy_mapping")
    if not isinstance(mappings, list) or not mappings:
        errors.append("策略映射不能为空")
    else:
        try:
            ordered = sorted(mappings, key=lambda item: float(item["score_min"]))
            base_ordered = sorted(base.get("strategy_mapping", []), key=lambda item: float(item["score_min"]))
            expected_min = float(base_ordered[0]["score_min"])
            expected_max = float(base_ordered[-1]["score_max"])
            if float(ordered[0]["score_min"]) != expected_min or float(ordered[-1]["score_max"]) != expected_max:
                errors.append(f"策略映射必须覆盖当前模型的 {expected_min:g} 至 {expected_max:g} 分")
            for previous, current in zip(ordered, ordered[1:]):
                if float(current["score_min"]) - float(previous["score_max"]) > 0.02 or float(current["score_min"]) <= float(previous["score_max"]):
                    errors.append("策略映射区间存在重叠或断档")
                    break
        except (KeyError, TypeError, ValueError):
            errors.append("策略映射分数区间无效")

    details: list[dict] = []
    skipped_count = 0
    if not errors:
        for counterparty in counterparties:
            try:
                before = rate_counterparty(counterparty, base)
            except (KeyError, TypeError, ValueError):
                skipped_count += 1
                continue
            if not before.get("ok"):
                skipped_count += 1
                continue
            try:
                after = rate_counterparty(counterparty, candidate)
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(f"样本 {counterparty.get('name', counterparty.get('id'))} 计算失败：{exc}")
                break
            if not after.get("ok"):
                errors.append(after.get("error") or "候选模型样本重算失败")
                break
            risk_before = evaluate_indicator_pool(counterparty, base)
            risk_after = evaluate_indicator_pool(counterparty, candidate)
            details.append(
                {
                    "counterparty_id": counterparty["id"],
                    "counterparty_name": counterparty["name"],
                    "before_score": before["total_score"],
                    "after_score": after["total_score"],
                    "score_delta": round(after["total_score"] - before["total_score"], 2),
                    "before_rating": before["rating"],
                    "after_rating": after["rating"],
                    "before_strategy": before["access_strategy"],
                    "after_strategy": after["access_strategy"],
                    "limit_delta": after["suggested_limit"] - before["suggested_limit"],
                    "term_delta": after["suggested_payment_term_days"] - before["suggested_payment_term_days"],
                    "before_risk_screening_score": risk_before["normalized_score"],
                    "after_risk_screening_score": risk_after["normalized_score"],
                    "risk_screening_score_delta": round(risk_after["normalized_score"] - risk_before["normalized_score"], 1),
                    "before_risk_policy_hits": [item["id"] for item in before.get("risk_screening_policy", {}).get("hits", [])],
                    "after_risk_policy_hits": [item["id"] for item in after.get("risk_screening_policy", {}).get("hits", [])],
                }
            )

    impacted = [item for item in details if item["score_delta"] or item["before_rating"] != item["after_rating"] or item["before_strategy"] != item["after_strategy"] or item["limit_delta"] or item["term_delta"]]
    rating_changes = sum(item["before_rating"] != item["after_rating"] for item in details)
    strategy_changes = sum(item["before_strategy"] != item["after_strategy"] for item in details)
    risk_screening_impacted = [item for item in details if item["risk_screening_score_delta"]]
    indicator_selection_changed = get_model_indicator_selection(base) != get_model_indicator_selection(candidate)
    risk_screening_policy_changed = get_risk_screening_policy(base) != get_risk_screening_policy(candidate)
    scorecard_binding_changed = base.get("scorecard_binding") != candidate.get("scorecard_binding")
    if details and not impacted and not risk_screening_impacted and not indicator_selection_changed:
        warnings.append("本次配置在当前样本组合上未产生结果变化")
    elif details and not impacted and indicator_selection_changed:
        warnings.append("主评级结果未变化；企业风险指标组合已变更，请结合独立筛查分与完整度复核")
    if skipped_count:
        warnings.append(f"{skipped_count} 个不适用当前模型的样本已排除")
    model_risk = build_model_validation_report(candidate, counterparties, template_key, monitoring_dataset) if not errors else None
    if model_risk and not model_risk["release_gate"]["passed"]:
        warnings.append(model_risk["release_gate"]["summary"])
    validation = {"valid": not errors, "errors": errors, "warnings": warnings, "config_hash": content_hash(candidate), "model_risk": model_risk}
    impact = {
        "sample_count": len(details),
        "skipped_count": skipped_count,
        "impacted_count": len(impacted),
        "rating_changes": rating_changes,
        "strategy_changes": strategy_changes,
        "max_abs_score_delta": max((abs(item["score_delta"]) for item in details), default=0),
        "indicator_selection_changed": indicator_selection_changed,
        "risk_screening_policy_changed": risk_screening_policy_changed,
        "scorecard_binding_changed": scorecard_binding_changed,
        "risk_screening_impacted_count": len(risk_screening_impacted),
        "max_abs_risk_screening_delta": max((abs(item["risk_screening_score_delta"]) for item in details), default=0),
        "average_limit_delta": round(sum(item["limit_delta"] for item in details) / len(details), 2) if details else 0,
        "details": details,
    }
    return validation, impact
