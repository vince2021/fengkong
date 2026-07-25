from __future__ import annotations

from rating.rules import apply_rule_actions, evaluate_strong_rules, get_field_value
from rating.strategies import apply_strategy_mapping, get_mapping_for_score


NEUTRAL_MISSING_SCORE = 50.0


def rate_corporate_credit(counterparty: dict, config: dict) -> dict:
    model = config["indicator_model"]
    submodels: dict[str, dict] = {}
    indicator_rows: list[dict] = []
    for dimension_key, dimension in model["dimensions"].items():
        result = _score_dimension(counterparty, dimension_key, dimension)
        submodels[dimension_key] = result
        indicator_rows.extend(result["indicator_rows"])

    business_score = submodels["business_risk"]["score"]
    financial_score = submodels["financial_risk"]["score"]
    business_band = _risk_band(business_score, model["risk_band_cutoffs"])
    financial_band = _risk_band(financial_score, model["risk_band_cutoffs"])
    anchor_score = float(model["business_financial_matrix"][business_band - 1][financial_band - 1])

    weights = config["weights"]
    external_score = submodels["external_credit"]["score"]
    transaction_score = submodels["transaction_behavior"]["score"]
    base_score = (
        anchor_score * float(weights["business_financial_anchor"])
        + external_score * float(weights["external_credit"])
        + transaction_score * float(weights["transaction_behavior"])
    )

    rule_hits = evaluate_strong_rules(counterparty, config)
    risk_adjustment = sum(float(hit["action"].get("score_adjustment", 0)) for hit in rule_hits)
    lower, upper = model.get("risk_adjustment_range", [-20, 10])
    risk_adjustment = max(float(lower), min(float(upper), risk_adjustment))
    total_score = round(max(0.0, min(100.0, base_score + risk_adjustment)), 1)
    raw_rating = get_mapping_for_score(total_score, config["strategy_mapping"])["rating"]
    base_strategy = apply_strategy_mapping(counterparty, raw_rating, config)
    base_strategy, limit_calculation = _apply_corporate_limit_policy(counterparty, raw_rating, base_strategy, config)
    final_strategy = apply_rule_actions(base_strategy, rule_hits, counterparty)
    limit_calculation["规则调整后额度"] = final_strategy["suggested_limit"]

    completeness_weights = model["completeness_weights"]
    data_completeness = round(
        sum(submodels[key]["completeness"] * float(weight) for key, weight in completeness_weights.items()),
        4,
    )
    deductions = sorted(
        (row for row in indicator_rows if row["available"] and row["score"] < 80),
        key=lambda row: row["effective_loss"],
        reverse=True,
    )
    positives = sorted(
        (row for row in indicator_rows if row["available"] and row["score"] >= 80),
        key=lambda row: row["weighted_contribution"],
        reverse=True,
    )

    return {
        "ok": True,
        "scorecard_type": "corporate_credit_v2",
        "counterparty_id": counterparty["id"],
        "counterparty_name": counterparty["name"],
        "counterparty_type": counterparty["counterparty_type"],
        "model_version": config["version"],
        "total_score": total_score,
        "base_score": round(base_score, 2),
        "risk_adjustment_score": round(risk_adjustment, 2),
        "rating": final_strategy["rating"],
        "raw_rating": raw_rating,
        "risk_segment": final_strategy["risk_segment"],
        "access_strategy": final_strategy["access_strategy"],
        "suggested_limit": final_strategy["suggested_limit"],
        "suggested_payment_term_days": final_strategy["payment_term_days"],
        "limit_calculation": limit_calculation,
        "monitoring_frequency": final_strategy["monitoring_frequency"],
        "review_required": final_strategy["review_required"] or data_completeness < model["review_completeness_threshold"] or bool(rule_hits),
        "dimension_scores": {
            "business_financial_anchor": anchor_score,
            "external_credit": external_score,
            "transaction_behavior": transaction_score,
        },
        "submodel_scores": {key: value["score"] for key, value in submodels.items()},
        "submodel_completeness": {key: value["completeness"] for key, value in submodels.items()},
        "data_completeness": data_completeness,
        "business_risk_band": business_band,
        "financial_risk_band": financial_band,
        "indicator_explanations": [_as_explanation(row) for row in indicator_rows],
        "indicator_calculations": indicator_rows,
        "strong_rule_hits": rule_hits,
        "main_deductions": [_factor(row) for row in deductions[:5]],
        "main_positive_factors": [_factor(row) for row in positives[:5]],
        "calculation_formula": "最终分 = 业务财务矩阵锚点×65% + 外部信用×20% + 交易行为×15% + 风险规则调整",
    }


def _score_dimension(counterparty: dict, dimension_key: str, dimension: dict) -> dict:
    group_scores: list[tuple[float, float]] = []
    indicator_rows: list[dict] = []
    available_weight = 0.0
    for group in dimension["groups"]:
        group_score = 0.0
        group_available_weight = 0.0
        for indicator in group["indicators"]:
            value = get_field_value(counterparty, indicator["path"])
            if dimension_key == "transaction_behavior" and not get_field_value(counterparty, "data_quality.internal_transaction_complete"):
                value = None
            score = _score_indicator(value, indicator)
            available = score is not None
            applied_score = float(score if available else NEUTRAL_MISSING_SCORE)
            indicator_weight = float(indicator["weight"])
            group_score += applied_score * indicator_weight
            if available:
                group_available_weight += indicator_weight
            effective_weight = float(group["weight"]) * indicator_weight
            indicator_rows.append(
                {
                    "dimension": dimension_key,
                    "dimension_label": dimension["label"],
                    "group": group["id"],
                    "group_label": group["label"],
                    "indicator": indicator["label"],
                    "path": indicator["path"],
                    "actual_value": value,
                    "unit": indicator.get("unit", ""),
                    "available": available,
                    "score": round(applied_score, 2),
                    "indicator_weight": indicator_weight,
                    "group_weight": float(group["weight"]),
                    "effective_weight": round(effective_weight, 6),
                    "weighted_contribution": round(applied_score * effective_weight, 2),
                    "effective_loss": round((100 - applied_score) * effective_weight, 2),
                    "formula": f"{applied_score:g} × {indicator_weight:.0%} × {float(group['weight']):.0%}",
                    "missing_policy": "缺失时按中性 50 分参与计算，同时降低完整度并触发复核",
                    "source": indicator.get("source", "待配置"),
                }
            )
        group_scores.append((group_score, float(group["weight"])))
        available_weight += group_available_weight * float(group["weight"])
    return {
        "score": round(sum(score * weight for score, weight in group_scores), 2),
        "completeness": round(available_weight, 4),
        "indicator_rows": indicator_rows,
    }


def _apply_corporate_limit_policy(counterparty: dict, rating: str, base_strategy: dict, config: dict) -> tuple[dict, dict]:
    strategy = dict(base_strategy)
    policy = config["credit_policy"]
    requested_limit = max(float(counterparty.get("requested_limit") or 0), 0)
    revenue_yi = get_field_value(counterparty, "corporate_profile.business.revenue_yi")
    revenue_capacity = 0
    if revenue_yi is not None:
        revenue_capacity = int(max(float(revenue_yi), 0) * 100_000_000 * float(policy["revenue_limit_pct_by_rating"].get(rating, 0)))
    order_amount = max(float(get_field_value(counterparty, "internal.order_amount_12m") or 0), 0)
    order_capacity = int(order_amount * float(policy["order_amount_multiplier"])) if order_amount else 0

    candidates = {
        "申请额度上限": int(requested_limit),
        "等级系数上限": int(base_strategy["suggested_limit"]),
        "收入承载上限": revenue_capacity,
    }
    if get_field_value(counterparty, "data_quality.internal_transaction_complete") and order_capacity:
        candidates["近12月交易规模上限"] = order_capacity

    if requested_limit <= 0:
        suggested_limit = 0
        binding_constraint = "申请额度未提供"
    else:
        usable = {key: value for key, value in candidates.items() if value >= 0}
        binding_constraint, suggested_limit = min(usable.items(), key=lambda item: item[1])
    strategy["suggested_limit"] = int(suggested_limit)
    return strategy, {
        "公式": "建议额度 = min(申请额度上限, 等级系数上限, 收入承载上限, 可用时的交易规模上限, 强规则上限)",
        "候选上限": candidates,
        "约束项": binding_constraint,
        "规则调整前额度": int(suggested_limit),
    }


def _score_indicator(value, indicator: dict) -> float | None:
    if value is None:
        return None
    scoring = indicator["scoring"]
    kind = scoring["type"]
    if kind == "categorical":
        return float(scoring["scores"].get(str(value), scoring.get("default", NEUTRAL_MISSING_SCORE)))
    if kind == "boolean":
        return float(scoring["true_score"] if bool(value) else scoring["false_score"])
    numeric = float(value)
    if kind == "higher_better":
        for threshold, score in scoring["cutoffs"]:
            if numeric >= float(threshold):
                return float(score)
        return float(scoring["floor_score"])
    if kind == "lower_better":
        for threshold, score in scoring["cutoffs"]:
            if numeric <= float(threshold):
                return float(score)
        return float(scoring["floor_score"])
    raise ValueError(f"Unsupported indicator scoring type: {kind}")


def _risk_band(score: float, cutoffs: list[float]) -> int:
    for index, cutoff in enumerate(cutoffs, start=1):
        if score >= float(cutoff):
            return index
    return len(cutoffs) + 1


def _as_explanation(row: dict) -> dict:
    loss = row["effective_loss"] if row["available"] else 0
    value = "缺失" if row["actual_value"] is None else f"{row['actual_value']}{row['unit']}"
    return {
        "dimension": row["dimension"],
        "indicator": row["indicator"],
        "points": loss,
        "reason": "指标标准分低于满分" if row["available"] else "指标缺失，按中性值处理并降低完整度",
        "evidence": f"原始值：{value}；标准分：{row['score']:g}",
        "direction": "deduction" if loss else "positive",
    }


def _factor(row: dict) -> dict:
    return {
        "dimension": row["dimension_label"],
        "indicator": row["indicator"],
        "points": row["effective_loss"],
        "reason": f"标准分 {row['score']:g}",
        "evidence": f"原始值 {row['actual_value']}{row['unit']}",
    }
