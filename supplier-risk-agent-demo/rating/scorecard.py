from __future__ import annotations

from copy import deepcopy

from sqlalchemy.exc import SQLAlchemyError

from rating.explanations import make_deduction, split_explanations
from rating.models import TAX_CREDIT_SCORES, VALID_REGISTRATION_STATUSES
from rating.strategies import apply_strategy_mapping, get_mapping_for_score


def validate_weights(weights: dict) -> tuple[bool, str]:
    total = sum(float(value) for value in weights.values())
    if abs(total - 1.0) > 0.0001:
        return False, f"权重合计必须等于 100%，当前为 {total:.2%}"
    return True, ""


def calculate_dimension_scores(counterparty: dict, config: dict) -> dict:
    thresholds = config["thresholds"]
    explanations: list[dict] = []

    external_score = _score_external(counterparty, thresholds, explanations)
    internal_score = _score_internal(counterparty, thresholds, explanations)
    financial_score = _score_financial(counterparty, thresholds, explanations)
    relationship_score = _score_relationship(counterparty, explanations)

    return {
        "scores": {
            "external_risk": external_score,
            "internal_performance": internal_score,
            "financial_credit": financial_score,
            "relationship_stability": relationship_score,
        },
        "explanations": explanations,
    }


def calculate_total_score(dimension_scores: dict, weights: dict) -> float:
    total = 0.0
    for dimension, score in dimension_scores.items():
        total += score * float(weights[dimension])
    return round(max(min(total, 100), 0), 1)


def map_rating(total_score: float, strategy_mapping: list[dict]) -> str:
    return get_mapping_for_score(total_score, strategy_mapping)["rating"]


def rate_counterparty(counterparty: dict, config: dict) -> dict:
    pipeline_code = str(config.get("decision_pipeline_code") or "").strip()
    if pipeline_code:
        from rating.decision_pipeline import run_decision_pipeline

        pipeline_context = {"counterparty": counterparty, "config": config}
        try:
            pipeline_result = run_decision_pipeline(
                pipeline_code, pipeline_context
            )
        except SQLAlchemyError:
            pipeline_result = None
        if pipeline_result is not None:
            return _decorate_pipeline_result(pipeline_result, pipeline_context)

    if config.get("scorecard_type") == "corporate_credit_v2":
        from rating.corporate_credit_scorecard import rate_corporate_credit

        result = rate_corporate_credit(counterparty, config)

        from rating.risk_screening_policy import apply_risk_screening_policy

        return apply_risk_screening_policy(counterparty, config, result)

    if config.get("scorecard_type") == "tech_enterprise_basic":
        from rating.tech_scorecard import rate_tech_enterprise

        result = rate_tech_enterprise(counterparty, config)

        from rating.risk_screening_policy import apply_risk_screening_policy

        return apply_risk_screening_policy(counterparty, config, result)

    is_valid, error = validate_weights(config["weights"])
    if not is_valid:
        return {"ok": False, "error": error, "counterparty_id": counterparty["id"]}

    dimension_result = calculate_dimension_scores(counterparty, config)
    dimension_scores = dimension_result["scores"]
    total_score = calculate_total_score(dimension_scores, config["weights"])
    rating = map_rating(total_score, config["strategy_mapping"])

    from rating.rules import apply_rule_actions, evaluate_strong_rules

    base_strategy = apply_strategy_mapping(counterparty, rating, config)
    strong_rule_hits = evaluate_strong_rules(counterparty, config)
    final_strategy = apply_rule_actions(base_strategy, strong_rule_hits, counterparty)
    explanation_summary = split_explanations(dimension_result["explanations"])

    result = {
        "ok": True,
        "counterparty_id": counterparty["id"],
        "counterparty_name": counterparty["name"],
        "counterparty_type": counterparty["counterparty_type"],
        "model_version": config["version"],
        "total_score": total_score,
        "rating": final_strategy["rating"],
        "raw_rating": rating,
        "risk_segment": final_strategy["risk_segment"],
        "access_strategy": final_strategy["access_strategy"],
        "suggested_limit": final_strategy["suggested_limit"],
        "suggested_payment_term_days": final_strategy["payment_term_days"],
        "monitoring_frequency": final_strategy["monitoring_frequency"],
        "dimension_scores": dimension_scores,
        "indicator_explanations": dimension_result["explanations"],
        "strong_rule_hits": strong_rule_hits,
        "review_required": final_strategy["review_required"] or bool(strong_rule_hits),
        "main_deductions": explanation_summary["main_deductions"],
        "main_positive_factors": explanation_summary["main_positive_factors"],
    }

    from rating.risk_screening_policy import apply_risk_screening_policy

    return apply_risk_screening_policy(counterparty, config, result)


def _decorate_pipeline_result(result: dict, context: dict) -> dict:
    decorated = deepcopy(result)
    trace = deepcopy(context.get("pipeline_trace") or {})
    decorated["decision_pipeline_trace"] = trace

    strong_hits = []
    risk_hits = []
    risk_before = None
    risk_after = None
    previous_result = None
    for stage in trace.get("stages", []):
        output = stage.get("output") or {}
        stage_result = output.get("result")
        if stage.get("stage_type") == "strong_rules":
            strong_hits.extend(
                _legacy_rule_hit(hit)
                for hit in output.get("triggered_rules", [])
            )
        elif stage.get("stage_type") == "risk_screening":
            risk_hits.extend(
                _risk_policy_hit(hit)
                for hit in output.get("triggered_rules", [])
            )
            risk_before = _strategy_snapshot(previous_result or {})
            risk_after = _strategy_snapshot(stage_result or {})
        if isinstance(stage_result, dict):
            previous_result = stage_result

    decorated["strong_rule_hits"] = strong_hits
    screening = deepcopy(context.get("indicator_screening"))
    if isinstance(screening, dict):
        decorated["enterprise_risk_screening"] = screening
        decorated["risk_screening_policy"] = {
            "enabled": True,
            "aggregation": "most_restrictive",
            "metrics": {
                key: screening.get(key)
                for key in (
                    "normalized_score",
                    "completeness",
                    "critical_indicator_count",
                    "missing_count",
                )
            },
            "hits": risk_hits,
            "before": risk_before or {},
            "after": risk_after or {},
            "changed": bool(risk_before != risk_after),
        }
    return decorated


def _legacy_rule_hit(hit: dict) -> dict:
    conditions = deepcopy(hit.get("conditions") or [])
    return {
        "hit": True,
        "rule_id": hit.get("code", ""),
        "rule_name": hit.get("name", ""),
        "relation": hit.get("condition_relation", "all"),
        "matched_conditions": [
            item for item in conditions if item.get("matched")
        ],
        "all_conditions": conditions,
        "action": _action_mapping(hit.get("actions") or []),
    }


def _risk_policy_hit(hit: dict) -> dict:
    conditions = hit.get("conditions") or []
    condition = conditions[0] if conditions else {}
    return {
        "id": hit.get("code", ""),
        "name": hit.get("name", ""),
        "expression": condition.get("expression", ""),
        "actual": condition.get("actual_value"),
        "action": _action_mapping(hit.get("actions") or []),
    }


def _action_mapping(actions: list[dict]) -> dict:
    return {
        str(action.get("type")): deepcopy(action.get("value"))
        for action in actions
        if action.get("type")
    }


def _strategy_snapshot(result: dict) -> dict:
    return {
        key: deepcopy(result.get(key))
        for key in (
            "rating",
            "risk_segment",
            "access_strategy",
            "suggested_limit",
            "suggested_payment_term_days",
            "monitoring_frequency",
            "review_required",
        )
    }


def rate_counterparties(counterparties: list[dict], config: dict) -> list[dict]:
    return [rate_counterparty(counterparty, config) for counterparty in counterparties]


def _score_external(counterparty: dict, thresholds: dict, explanations: list[dict]) -> float:
    external = counterparty["external"]
    score = 100.0

    if external["registration_status"] not in VALID_REGISTRATION_STATUSES:
        score -= _deduct(
            explanations,
            "external_risk",
            "主体经营状态",
            35,
            "主体状态异常",
            f"经营状态：{external['registration_status']}",
        )

    if external["dishonesty_count"] > thresholds["dishonesty_count"]:
        score -= _deduct(
            explanations,
            "external_risk",
            "失信记录",
            45,
            "存在失信被执行记录",
            f"失信记录：{external['dishonesty_count']} 条",
        )

    if external["major_litigation_amount"] > thresholds["major_litigation_amount"]:
        score -= _deduct(
            explanations,
            "external_risk",
            "重大诉讼金额",
            18,
            "重大诉讼金额超过阈值",
            f"重大诉讼金额：{external['major_litigation_amount']:,} 元",
        )
    elif external["major_litigation_amount"] > 0:
        score -= _deduct(
            explanations,
            "external_risk",
            "重大诉讼金额",
            min(external["major_litigation_amount"] / thresholds["major_litigation_amount"] * 8, 8),
            "存在未达强预警阈值的诉讼暴露",
            f"重大诉讼金额：{external['major_litigation_amount']:,} 元",
        )

    if external["operating_abnormal_count"] > thresholds["operating_abnormal_count"]:
        score -= _deduct(
            explanations,
            "external_risk",
            "经营异常",
            10,
            "存在经营异常记录",
            f"经营异常：{external['operating_abnormal_count']} 条",
        )

    if external["admin_penalty_count"] > 0:
        score -= _deduct(
            explanations,
            "external_risk",
            "行政处罚",
            min(external["admin_penalty_count"] * 4, 16),
            "存在行政处罚记录",
            f"行政处罚：{external['admin_penalty_count']} 条",
        )

    if external["equity_freeze_count"] > 0:
        score -= _deduct(
            explanations,
            "external_risk",
            "股权冻结",
            min(external["equity_freeze_count"] * 5, 15),
            "存在股权冻结记录",
            f"股权冻结：{external['equity_freeze_count']} 条",
        )

    tax_deduction = TAX_CREDIT_SCORES.get(external["tax_credit_level"], 5)
    if tax_deduction:
        score -= _deduct(
            explanations,
            "external_risk",
            "纳税信用等级",
            tax_deduction,
            "纳税信用等级较低",
            f"纳税信用等级：{external['tax_credit_level']}",
        )

    return _clamp(score)


def _score_internal(counterparty: dict, thresholds: dict, explanations: list[dict]) -> float:
    internal = counterparty["internal"]
    score = 100.0

    if internal["cooperation_years"] == 0:
        score -= _deduct(explanations, "internal_performance", "合作年限", 6, "暂无稳定合作记录", "合作年限：0 年")

    if internal["delivery_delay_count"] >= thresholds["delivery_delay_count"]:
        score -= _deduct(
            explanations,
            "internal_performance",
            "履约延期次数",
            14,
            "履约延期次数达到阈值",
            f"履约延期：{internal['delivery_delay_count']} 次",
        )

    if internal["contract_dispute_count"] >= thresholds["contract_dispute_count"]:
        score -= _deduct(
            explanations,
            "internal_performance",
            "合同争议次数",
            12,
            "合同争议次数达到阈值",
            f"合同争议：{internal['contract_dispute_count']} 次",
        )

    if internal["quality_issue_count"] > 1:
        score -= _deduct(
            explanations,
            "internal_performance",
            "质量异常次数",
            min(internal["quality_issue_count"] * 3, 12),
            "质量异常偏多",
            f"质量异常：{internal['quality_issue_count']} 次",
        )

    if internal["return_rate"] > 0.05:
        score -= _deduct(
            explanations,
            "internal_performance",
            "退货率",
            8,
            "退货率高于 5%",
            f"退货率：{internal['return_rate']:.0%}",
        )

    if internal["invoice_match_rate"] < thresholds["invoice_match_rate"]:
        score -= _deduct(
            explanations,
            "internal_performance",
            "发票匹配率",
            12,
            "发票匹配率低于阈值",
            f"发票匹配率：{internal['invoice_match_rate']:.0%}",
        )

    if internal["delivery_fulfillment_rate"] < 0.9:
        score -= _deduct(
            explanations,
            "internal_performance",
            "交付达成率",
            10,
            "交付达成率低于 90%",
            f"交付达成率：{internal['delivery_fulfillment_rate']:.0%}",
        )

    return _clamp(score)


def _score_financial(counterparty: dict, thresholds: dict, explanations: list[dict]) -> float:
    financial = counterparty["financial"]
    score = 100.0

    if financial["bad_debt_flag"]:
        score -= _deduct(explanations, "financial_credit", "历史坏账", 35, "存在历史坏账记录", "历史坏账：是")

    if financial["overdue_rate"] > thresholds["overdue_rate"]:
        score -= _deduct(
            explanations,
            "financial_credit",
            "逾期率",
            22,
            "逾期率超过阈值",
            f"逾期率：{financial['overdue_rate']:.0%}",
        )

    if financial["avg_collection_days"] > 60:
        score -= _deduct(
            explanations,
            "financial_credit",
            "平均回款周期",
            10,
            "平均回款周期超过 60 天",
            f"平均回款周期：{financial['avg_collection_days']} 天",
        )

    if financial["limit_utilization_rate"] > 0.85:
        score -= _deduct(
            explanations,
            "financial_credit",
            "额度使用率",
            8,
            "额度使用率偏高",
            f"额度使用率：{financial['limit_utilization_rate']:.0%}",
        )

    return _clamp(score)


def _score_relationship(counterparty: dict, explanations: list[dict]) -> float:
    external = counterparty["external"]
    score = 100.0

    if external["related_party_high_risk"]:
        score -= _deduct(
            explanations,
            "relationship_stability",
            "关联方风险",
            18,
            "存在关联方高风险信号",
            "关联方高风险：是",
        )

    if external["established_years"] < 3:
        score -= _deduct(
            explanations,
            "relationship_stability",
            "成立年限",
            8,
            "成立时间较短，经营稳定性仍需观察",
            f"成立年限：{external['established_years']} 年",
        )

    return _clamp(score)


def _deduct(explanations: list[dict], dimension: str, indicator: str, points: float, reason: str, evidence: str) -> float:
    points = round(float(points), 2)
    explanations.append(make_deduction(dimension, indicator, points, reason, evidence))
    return points


def _clamp(score: float) -> float:
    return round(max(min(score, 100), 0), 2)
