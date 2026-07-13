from __future__ import annotations

from rating.models import DIMENSIONS


def make_deduction(dimension: str, indicator: str, points: float, reason: str, evidence: str) -> dict:
    return {
        "dimension": dimension,
        "dimension_label": DIMENSIONS.get(dimension, dimension),
        "indicator": indicator,
        "points": round(points, 2),
        "reason": reason,
        "evidence": evidence,
    }


def split_explanations(explanations: list[dict]) -> dict:
    sorted_items = sorted(explanations, key=lambda item: item["points"], reverse=True)
    return {
        "main_deductions": sorted_items[:5],
        "main_positive_factors": _positive_factors(explanations),
    }


def _positive_factors(explanations: list[dict]) -> list[str]:
    dimensions_with_deductions = {item["dimension"] for item in explanations}
    positives = []

    for dimension, label in DIMENSIONS.items():
        if dimension not in dimensions_with_deductions:
            positives.append(f"{label}未发现明显扣分项")

    return positives[:4]

