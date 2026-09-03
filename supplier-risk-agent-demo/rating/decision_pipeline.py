"""Versioned decision pipeline execution for the Rule Center."""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select

import backend.database as database
from backend.db_models import (
    DecisionPipelineDefinition,
    RuleDefinition,
    RuleSetDefinition,
)
from rating.rule_evaluator import apply_rule_actions, evaluate_rule_set


_SUPPORTED_STAGE_TYPES = {
    "scoring",
    "strong_rules",
    "risk_screening",
    "strategy_mapping",
    "admission",
}
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
_ACCESS_SEVERITY = {
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
_MONITORING_SEVERITY = {
    "年度": 0,
    "半年度": 1,
    "半年": 1,
    "季度": 2,
    "月度": 3,
    "周度": 4,
    "实时监控": 5,
}


def load_active_pipeline(code: str) -> DecisionPipelineDefinition | None:
    """Load one published active decision pipeline by code."""
    statement = (
        select(DecisionPipelineDefinition)
        .where(
            DecisionPipelineDefinition.code == code,
            DecisionPipelineDefinition.is_active.is_(True),
            DecisionPipelineDefinition.status == "published",
        )
        .order_by(DecisionPipelineDefinition.version.desc())
        .limit(1)
    )
    with database.SessionLocal() as session:
        return session.scalars(statement).first()


def load_active_rule_set(code: str) -> RuleSetDefinition | None:
    """Load one published active rule set by code."""
    statement = (
        select(RuleSetDefinition)
        .where(
            RuleSetDefinition.code == code,
            RuleSetDefinition.is_active.is_(True),
            RuleSetDefinition.status == "published",
        )
        .order_by(RuleSetDefinition.version.desc())
        .limit(1)
    )
    with database.SessionLocal() as session:
        return session.scalars(statement).first()


def load_rule_set_rules(rule_codes: list[str]) -> list[RuleDefinition]:
    """Load published active rules and preserve the rule set reference order."""
    if not rule_codes:
        return []
    statement = select(RuleDefinition).where(
        RuleDefinition.code.in_(rule_codes),
        RuleDefinition.is_active.is_(True),
        RuleDefinition.status == "published",
    )
    with database.SessionLocal() as session:
        rules = list(session.scalars(statement).all())
    by_code = {rule.code: rule for rule in rules}
    return [by_code[code] for code in rule_codes if code in by_code]


def run_decision_pipeline(pipeline_code: str, context: dict) -> dict | None:
    """Execute an active pipeline atomically, returning None for v1 fallback."""
    pipeline = load_active_pipeline(pipeline_code)
    if pipeline is None:
        return None

    return _execute_pipeline(
        pipeline,
        context,
        load_active_rule_set,
        load_rule_set_rules,
    )


def run_decision_pipeline_sandbox(
    pipeline_definition: dict,
    rule_set_definitions: dict[str, dict],
    rule_definitions: dict[str, dict],
    context: dict,
) -> dict | None:
    """Execute explicit candidate definitions without reading or writing runtime assets."""
    pipeline = SimpleNamespace(
        code=pipeline_definition.get("code", "candidate"),
        version=pipeline_definition.get("version", "candidate"),
        stages_json=deepcopy(pipeline_definition.get("stages_json", [])),
    )

    def rule_set_loader(code: str):
        item = rule_set_definitions.get(code)
        if item is None:
            return None
        return SimpleNamespace(
            code=item.get("code", code),
            version=item.get("version", "candidate"),
            rule_codes=deepcopy(item.get("rule_codes", [])),
            evaluation_strategy=item.get("evaluation_strategy", "most_restrictive"),
        )

    def rule_loader(codes: list[str]):
        return [
            SimpleNamespace(
                code=item.get("code", code),
                name=item.get("name", code),
                enabled=item.get("enabled", True),
                conditions_json=deepcopy(item.get("conditions_json", [])),
                condition_relation=item.get("condition_relation", "all"),
                actions_json=deepcopy(item.get("actions_json", [])),
                priority=item.get("priority", 999),
                version=item.get("version", "candidate"),
            )
            for code in codes
            if (item := rule_definitions.get(code)) is not None
        ]

    return _execute_pipeline(pipeline, context, rule_set_loader, rule_loader)


def _execute_pipeline(pipeline, context: dict, rule_set_loader, rule_loader) -> dict | None:

    stages = pipeline.stages_json or []
    if (
        not isinstance(stages, list)
        or not stages
        or not isinstance(stages[0], dict)
        or stages[0].get("stage_type") != "scoring"
    ):
        return None

    runtime = deepcopy(context)
    trace = {
        "pipeline_code": pipeline.code,
        "pipeline_version": pipeline.version,
        "stages": [],
    }

    for index, stage in enumerate(stages):
        if not isinstance(stage, dict):
            return None
        stage_type = str(stage.get("stage_type", ""))
        if stage_type not in _SUPPORTED_STAGE_TYPES:
            return None
        if index and not isinstance(runtime.get("current_result"), dict):
            return None

        stage_result = _run_stage(
            stage_type, stage, runtime, rule_set_loader, rule_loader
        )
        if stage_result is None:
            return None

        runtime[f"stage_{stage_type}"] = deepcopy(stage_result)
        trace["stages"].append(
            {
                "index": index,
                "stage_type": stage_type,
                "rule_set_code": stage.get("rule_set_code"),
                "output": deepcopy(stage_result),
            }
        )

        current = runtime.get("current_result", {})
        if stage_type == "scoring" and not current.get("ok", False):
            break

    final_result = deepcopy(runtime.get("current_result", {}))
    runtime["final_result"] = final_result
    runtime["pipeline_trace"] = trace
    context.clear()
    context.update(runtime)
    return final_result


def _run_stage(
    stage_type: str, stage: dict, context: dict, rule_set_loader, rule_loader
) -> dict | None:
    if stage_type == "scoring":
        result = _run_scoring_stage(context)
        context["current_result"] = result
        return {"result": deepcopy(result)}

    if stage_type == "strong_rules":
        return _run_rule_stage(stage, context, rule_set_loader, rule_loader)

    if stage_type == "risk_screening":
        from rating.indicator_evaluator import evaluate_indicator_pool_v2

        screening = evaluate_indicator_pool_v2(
            context.get("counterparty", {}), context.get("config", {})
        )
        if screening is None:
            return None
        screening["critical_indicator_count"] = sum(
            detail.get("data_status") == "已取得"
            and float(detail.get("score", 0)) <= 1
            for detail in screening.get("details", [])
        )
        context["indicator_screening"] = screening
        rule_result = _run_rule_stage(
            stage, context, rule_set_loader, rule_loader
        )
        if rule_result is None:
            return None
        return {"screening": deepcopy(screening), **rule_result}

    if stage_type == "strategy_mapping":
        result = _run_strategy_mapping_stage(context)
        if stage.get("rule_set_code"):
            rule_result = _run_rule_stage(
                stage, context, rule_set_loader, rule_loader
            )
            if rule_result is None:
                return None
            return {"mapping_result": deepcopy(result), **rule_result}
        return {"result": deepcopy(result)}

    if stage_type == "admission":
        rule_result = None
        if stage.get("rule_set_code"):
            rule_result = _run_rule_stage(
                stage, context, rule_set_loader, rule_loader
            )
            if rule_result is None:
                return None
        result = _run_admission_stage(context)
        payload = {"result": deepcopy(result)}
        if rule_result is not None:
            payload.update(rule_result)
            payload["result"] = deepcopy(result)
        return payload

    return None


def _run_rule_stage(stage: dict, context: dict, rule_set_loader, rule_loader) -> dict | None:
    rule_set_code = stage.get("rule_set_code")
    if not rule_set_code:
        return None
    rule_set = rule_set_loader(str(rule_set_code))
    if rule_set is None:
        return None

    expected_codes = list(rule_set.rule_codes or [])
    rules = rule_loader(expected_codes)
    if len(rules) != len(expected_codes) or {
        rule.code for rule in rules
    } != set(expected_codes):
        return None

    triggered = evaluate_rule_set(rule_set, rules, _build_rule_context(context))
    adjusted = apply_rule_actions(triggered, context)
    context["current_result"] = adjusted
    return {
        "rule_set": {
            "code": rule_set.code,
            "version": rule_set.version,
            "evaluation_strategy": rule_set.evaluation_strategy,
        },
        "triggered_rules": [_serialize_rule_hit(item) for item in triggered],
        "result": deepcopy(adjusted),
    }


def _build_rule_context(context: dict) -> dict:
    rule_context = deepcopy(context.get("counterparty", {}))
    rule_context["config"] = deepcopy(context.get("config", {}))
    rule_context["current_result"] = deepcopy(context.get("current_result", {}))
    if "indicator_screening" in context:
        rule_context["indicator_screening"] = deepcopy(
            context["indicator_screening"]
        )
    return rule_context


def _serialize_rule_hit(item: dict) -> dict:
    rule = item["rule"]
    return {
        "code": rule.code,
        "name": rule.name,
        "priority": rule.priority,
        "condition_relation": rule.condition_relation,
        "actions": deepcopy(rule.actions_json or []),
        "conditions": deepcopy(item.get("details", [])),
    }


def _run_scoring_stage(context: dict) -> dict:
    counterparty = context.get("counterparty", {})
    config = deepcopy(context.get("config", {}))
    config["strong_rules"] = []

    try:
        if config.get("scorecard_binding"):
            from rating.governed_scorecard import rate_governed_scorecard

            return rate_governed_scorecard(counterparty, config)
        scorecard_type = config.get("scorecard_type", "")
        if scorecard_type == "corporate_credit_v2":
            from rating.corporate_credit_scorecard import rate_corporate_credit

            return rate_corporate_credit(counterparty, config)
        if scorecard_type == "tech_enterprise_basic":
            from rating.tech_scorecard import rate_tech_enterprise

            return rate_tech_enterprise(counterparty, config)
        return _run_generic_scoring(counterparty, config)
    except (ArithmeticError, KeyError, TypeError, ValueError) as exc:
        return {
            "ok": False,
            "error": str(exc),
            "counterparty_id": counterparty.get("id"),
        }


def _run_generic_scoring(counterparty: dict, config: dict) -> dict:
    from rating.explanations import split_explanations
    from rating.scorecard import (
        calculate_dimension_scores,
        calculate_total_score,
        map_rating,
        validate_weights,
    )
    from rating.strategies import apply_strategy_mapping

    is_valid, error = validate_weights(config["weights"])
    if not is_valid:
        return {
            "ok": False,
            "error": error,
            "counterparty_id": counterparty.get("id"),
        }

    dimension_result = calculate_dimension_scores(counterparty, config)
    dimension_scores = dimension_result["scores"]
    total_score = calculate_total_score(dimension_scores, config["weights"])
    rating = map_rating(total_score, config["strategy_mapping"])
    strategy = apply_strategy_mapping(counterparty, rating, config)
    explanations = split_explanations(dimension_result["explanations"])
    return {
        "ok": True,
        "counterparty_id": counterparty["id"],
        "counterparty_name": counterparty["name"],
        "counterparty_type": counterparty["counterparty_type"],
        "model_version": config["version"],
        "total_score": total_score,
        "rating": strategy["rating"],
        "raw_rating": rating,
        "risk_segment": strategy["risk_segment"],
        "access_strategy": strategy["access_strategy"],
        "suggested_limit": strategy["suggested_limit"],
        "suggested_payment_term_days": strategy["payment_term_days"],
        "monitoring_frequency": strategy["monitoring_frequency"],
        "dimension_scores": dimension_scores,
        "indicator_explanations": dimension_result["explanations"],
        "strong_rule_hits": [],
        "review_required": bool(strategy["review_required"]),
        "main_deductions": explanations["main_deductions"],
        "main_positive_factors": explanations["main_positive_factors"],
    }


def _run_strategy_mapping_stage(context: dict) -> dict:
    from rating.strategies import apply_strategy_mapping, get_mapping_for_score

    current = deepcopy(context.get("current_result", {}))
    config = context.get("config", {})
    counterparty = context.get("counterparty", {})
    mappings = config.get("strategy_mapping")
    if not current.get("ok") or not isinstance(mappings, list) or not mappings:
        context["current_result"] = current
        return current

    score = current.get("total_score")
    mapped_rating = current.get("rating")
    if isinstance(score, (int, float)):
        mapped_rating = get_mapping_for_score(float(score), mappings)["rating"]
    rating = _more_restrictive(
        current.get("rating"), mapped_rating, _RATING_SEVERITY
    )
    strategy = apply_strategy_mapping(counterparty, rating, config)

    current["rating"] = rating
    current["risk_segment"] = _more_restrictive(
        current.get("risk_segment"),
        strategy.get("risk_segment"),
        _RISK_SEGMENT_SEVERITY,
    )
    current["access_strategy"] = _more_restrictive(
        current.get("access_strategy"),
        strategy.get("access_strategy"),
        _ACCESS_SEVERITY,
    )
    current["monitoring_frequency"] = _more_restrictive(
        current.get("monitoring_frequency"),
        strategy.get("monitoring_frequency"),
        _MONITORING_SEVERITY,
    )
    current["suggested_limit"] = _minimum_number(
        current.get("suggested_limit"), strategy.get("suggested_limit")
    )
    current["suggested_payment_term_days"] = _minimum_number(
        current.get("suggested_payment_term_days"),
        strategy.get("payment_term_days"),
    )
    current["review_required"] = bool(current.get("review_required")) or bool(
        strategy.get("review_required")
    )
    context["current_result"] = current
    return current


def _run_admission_stage(context: dict) -> dict:
    current = deepcopy(context.get("current_result", {}))
    access = str(current.get("access_strategy", "标准准入"))
    if access in {"禁入", "不建议准入"}:
        current["final_admission"] = "reject"
    elif access in {"人工复核", "限制准入", "审慎准入"}:
        current["final_admission"] = "manual_review"
        current["review_required"] = True
    else:
        current["final_admission"] = "approve"
    context["current_result"] = current
    return current


def _more_restrictive(current: Any, incoming: Any, severity: dict[str, int]) -> str:
    current_text = str(current or "")
    incoming_text = str(incoming or "")
    if incoming_text not in severity:
        return current_text
    if severity[incoming_text] > severity.get(current_text, -1):
        return incoming_text
    return current_text


def _minimum_number(current: Any, incoming: Any) -> int | float:
    values = [value for value in (current, incoming) if isinstance(value, (int, float))]
    if not values:
        return 0
    return min(values)
