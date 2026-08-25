"""Load governed indicator definitions and order them for evaluation."""
from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from typing import Any

from sqlalchemy import select

import backend.database as database
from backend.db_models import IndicatorDefinition
from rating.expression_engine import (
    ExpressionSecurityError,
    ExpressionSyntaxError,
    evaluate_expression,
)
from rating.rules import get_field_value


class IndicatorDependencyError(ValueError):
    """Base error for an invalid indicator dependency graph."""


class CircularDependencyError(IndicatorDependencyError):
    """Indicator dependencies contain a cycle."""


class MissingDependencyError(IndicatorDependencyError):
    """An indicator references a definition that is not available."""


_LAYER_ORDER = {"atomic": 0, "derived": 1, "composite": 2}


def load_active_indicators(
    category: str | None = None,
) -> list[IndicatorDefinition]:
    """Load published active indicators, optionally within one category."""
    statement = select(IndicatorDefinition).where(
        IndicatorDefinition.is_active.is_(True),
        IndicatorDefinition.status == "published",
    )
    if category:
        statement = statement.where(IndicatorDefinition.category == category)
    statement = statement.order_by(
        IndicatorDefinition.category,
        IndicatorDefinition.code,
        IndicatorDefinition.version,
    )

    with database.SessionLocal() as session:
        return list(session.scalars(statement).all())


def topological_sort(
    indicators: Sequence[IndicatorDefinition],
) -> list[IndicatorDefinition]:
    """Return a deterministic dependency order and reject invalid graphs."""
    by_code = {indicator.code: indicator for indicator in indicators}
    if len(by_code) != len(indicators):
        raise IndicatorDependencyError("指标列表包含重复编码")

    visited: set[str] = set()
    visiting: list[str] = []
    result: list[IndicatorDefinition] = []

    def visit(code: str) -> None:
        if code in visited:
            return
        if code in visiting:
            cycle_start = visiting.index(code)
            cycle = visiting[cycle_start:] + [code]
            raise CircularDependencyError(f"指标依赖成环: {' -> '.join(cycle)}")

        indicator = by_code[code]
        visiting.append(code)
        for dependency in indicator.dependencies or []:
            if dependency not in by_code:
                raise MissingDependencyError(
                    f"指标 {code} 缺少依赖定义: {dependency}"
                )
            visit(dependency)
        visiting.pop()
        visited.add(code)
        result.append(indicator)

    ordered_roots = sorted(
        indicators,
        key=lambda indicator: (
            _LAYER_ORDER.get(indicator.layer, len(_LAYER_ORDER)),
            indicator.code,
        ),
    )
    for indicator in ordered_roots:
        visit(indicator.code)
    return result


def _matches_numeric_band(
    actual: float | bool, operator: str, expected: float | bool
) -> bool:
    operations = {
        "==": lambda: actual == expected,
        "!=": lambda: actual != expected,
        "<": lambda: actual < expected,
        "<=": lambda: actual <= expected,
        ">": lambda: actual > expected,
        ">=": lambda: actual >= expected,
    }
    try:
        return operations[operator]()
    except KeyError as exc:
        raise ValueError(f"不支持的分箱运算符: {operator}") from exc


def _apply_scoring(
    value: Any,
    scoring_json: dict,
    max_score: float,
    missing_score: float,
) -> tuple[float, str, str]:
    """Apply a governed scoring configuration using the v1 detail format."""
    if value is None:
        return missing_score, "待补充", "待补充"

    score_type = scoring_json.get("type")
    bands = scoring_json.get("bands")
    if not isinstance(bands, list) or not bands:
        raise ValueError("评分配置缺少有效分箱")

    if score_type == "composite_boolean" and isinstance(value, (list, tuple)):
        flags = [bool(item) for item in value]
        composite_operations = {
            "both_true": all(flags),
            "any_true": any(flags),
            "none_true": not any(flags),
        }
        for band in bands:
            operator = str(band["operator"])
            if operator not in composite_operations:
                raise ValueError(f"不支持的复合布尔运算符: {operator}")
            if composite_operations[operator]:
                return (
                    float(band["score"]),
                    "已取得",
                    f"复合命中 {sum(flags)}/{len(flags)}",
                )
    elif score_type in {"boolean_hit", "composite_boolean"}:
        actual = bool(value)
        for band in bands:
            if _matches_numeric_band(
                actual,
                str(band["operator"]),
                bool(band["value"]),
            ):
                return (
                    float(band["score"]),
                    "已取得",
                    "已触发" if actual else "未触发",
                )
    elif score_type == "numeric_bands":
        if isinstance(value, bool):
            raise ValueError("数值分箱不接受布尔值")
        actual = float(value)
        for band in bands:
            if _matches_numeric_band(
                actual,
                str(band["operator"]),
                float(band["value"]),
            ):
                return float(band["score"]), "已取得", f"{actual:g}"
    else:
        raise ValueError(f"不支持的评分类型: {score_type}")

    # No matching band means the governed configuration is incomplete. It is
    # safer to degrade than to silently invent a score from max_score.
    raise ValueError(f"指标值未命中任何分箱: {value!r}; max_score={max_score:g}")


def evaluate_indicator(
    indicator: IndicatorDefinition,
    counterparty: dict,
) -> dict:
    """Evaluate one indicator and safely degrade expected data/config errors."""
    scoring_json = indicator.scoring_json or {}
    missing_score = float(scoring_json.get("missing_score", 2))
    max_score = (
        float(indicator.max_score) if indicator.max_score is not None else 3.0
    )
    model_weight = (
        float(indicator.default_weight)
        if indicator.default_weight is not None
        else 1.0
    )
    value: Any = None

    try:
        input_fields = scoring_json.get("input_fields")
        if (
            scoring_json.get("type") == "composite_boolean"
            and isinstance(input_fields, list)
            and input_fields
        ):
            input_values = [
                get_field_value(counterparty, str(field_path))
                for field_path in input_fields
            ]
            value = None if any(item is None for item in input_values) else input_values
        elif indicator.layer == "atomic":
            if not indicator.field_path:
                raise ValueError("原子指标缺少字段路径")
            value = get_field_value(counterparty, indicator.field_path)
        elif indicator.layer in {"derived", "composite"}:
            if not indicator.expression:
                raise ValueError("派生或复合指标缺少表达式")
            value = evaluate_expression(indicator.expression, counterparty)
        else:
            raise ValueError(f"不支持的指标层级: {indicator.layer}")

        score, data_status, actual_display = _apply_scoring(
            value,
            scoring_json,
            max_score,
            missing_score,
        )
    except (
        ExpressionSecurityError,
        ExpressionSyntaxError,
        ArithmeticError,
        KeyError,
        TypeError,
        ValueError,
    ):
        value = None
        score = missing_score
        data_status = "待补充"
        actual_display = "待补充"

    return {
        "indicator_id": indicator.code,
        "name": indicator.name,
        "category": indicator.category,
        "field_path": indicator.field_path or "",
        "actual_value": value,
        "actual_display": actual_display,
        "score": score,
        "max_score": max_score,
        "model_weight": model_weight,
        "formula": scoring_json.get("formula", ""),
        "data_status": data_status,
        "data_source": indicator.seed_source or "",
    }


def evaluate_indicator_pool_v2(
    counterparty: dict,
    config: dict,
    category: str | None = None,
) -> dict | None:
    """Evaluate the active factory pool using the v1 aggregate contract."""
    indicators = load_active_indicators(category)
    if not indicators:
        return None

    configured_selection = config.get("indicator_selection")
    if isinstance(configured_selection, list) and configured_selection:
        selected_weights = {
            str(item.get("indicator_id")): float(item.get("weight", 1))
            for item in configured_selection
            if isinstance(item, dict) and item.get("enabled", True)
        }
        if selected_weights:
            by_code = {indicator.code: indicator for indicator in indicators}
            if any(code not in by_code for code in selected_weights):
                return None
            indicators = [by_code[code] for code in selected_weights]
            for indicator in indicators:
                indicator.default_weight = selected_weights[indicator.code]

    sorted_indicators = topological_sort(indicators)
    evaluation_context = deepcopy(counterparty)
    details: list[dict] = []
    for indicator in sorted_indicators:
        detail = evaluate_indicator(indicator, evaluation_context)
        details.append(detail)
        # Expressions reference governed indicator codes. Missing or degraded
        # dependencies are injected as None so their dependants also degrade.
        evaluation_context[indicator.code] = detail["actual_value"]

    total_weight = sum(float(detail["model_weight"]) for detail in details)
    weighted_score = (
        sum(
            float(detail["score"]) * float(detail["model_weight"])
            for detail in details
        )
        / total_weight
        if total_weight
        else 0.0
    )
    available_count = sum(
        detail["data_status"] == "已取得" for detail in details
    )
    selected_count = len(details)
    normalized_score = (
        round(max(min((weighted_score - 1) / 2 * 100, 100), 0), 1)
        if selected_count
        else 0.0
    )

    return {
        "pool_version": "indicator-factory-v2",
        "selected_count": selected_count,
        "available_count": available_count,
        "missing_count": selected_count - available_count,
        "completeness": (
            round(available_count / selected_count, 4) if selected_count else 0.0
        ),
        "weighted_score": round(weighted_score, 2),
        "normalized_score": normalized_score,
        "formula": (
            "指标工厂 v2 = Σ（单指标 1~3 分 × 相对权重）÷ Σ相对权重；"
            "缺失按 missing_score"
        ),
        "details": details,
    }
