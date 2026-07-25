from __future__ import annotations


RATING_RISK_ORDER = {"D": 0, "C": 1, "B": 2, "BB": 3, "BBB": 4, "A": 5, "AA": 6, "AAA": 7}
REVIEW_STRATEGIES = {"人工复核", "限制准入", "审慎准入", "禁入"}


def build_portfolio_result(result: dict, rating_run_id: str) -> dict:
    screening = result.get("enterprise_risk_screening", {})
    policy = result.get("risk_screening_policy", {})
    return {
        "counterparty_id": result["counterparty_id"],
        "counterparty_name": result["counterparty_name"],
        "counterparty_type": result["counterparty_type"],
        "rating_run_id": rating_run_id,
        "total_score": result["total_score"],
        "rating": result["rating"],
        "raw_rating": result.get("raw_rating", result["rating"]),
        "risk_segment": result["risk_segment"],
        "access_strategy": result["access_strategy"],
        "suggested_limit": result["suggested_limit"],
        "suggested_payment_term_days": result["suggested_payment_term_days"],
        "monitoring_frequency": result["monitoring_frequency"],
        "review_required": bool(result.get("review_required")),
        "strong_rule_hit_count": len(result.get("strong_rule_hits", [])),
        "risk_policy_hits": [item["id"] for item in policy.get("hits", [])],
        "risk_policy_changed": bool(policy.get("changed")),
        "risk_screening_score": screening.get("normalized_score", 0),
        "risk_screening_completeness": screening.get("completeness", 0),
    }


def build_portfolio_summary(results: list[dict], skipped: list[dict], candidate_count: int) -> dict:
    rating_distribution = _distribution(results, "rating")
    access_distribution = _distribution(results, "access_strategy")
    risk_segment_distribution = _distribution(results, "risk_segment")
    review_count = sum(item["review_required"] or item["access_strategy"] in REVIEW_STRATEGIES for item in results)
    denied_count = sum(item["access_strategy"] == "禁入" or item["rating"] == "D" for item in results)
    policy_affected_count = sum(item["risk_policy_changed"] for item in results)
    strong_rule_affected_count = sum(item["strong_rule_hit_count"] > 0 for item in results)
    ordered_results = sorted(
        results,
        key=lambda item: (
            item["access_strategy"] != "禁入",
            not item["review_required"],
            RATING_RISK_ORDER.get(item["rating"], 99),
            item["total_score"],
            item["counterparty_name"],
        ),
    )
    return {
        "candidate_count": candidate_count,
        "success_count": len(results),
        "skipped_count": len(skipped),
        "review_required_count": review_count,
        "denied_count": denied_count,
        "policy_affected_count": policy_affected_count,
        "strong_rule_affected_count": strong_rule_affected_count,
        "total_suggested_limit": round(sum(float(item["suggested_limit"]) for item in results), 2),
        "average_score": round(sum(float(item["total_score"]) for item in results) / len(results), 2) if results else 0,
        "average_risk_screening_score": round(sum(float(item["risk_screening_score"]) for item in results) / len(results), 2) if results else 0,
        "average_risk_screening_completeness": round(sum(float(item["risk_screening_completeness"]) for item in results) / len(results), 4) if results else 0,
        "rating_distribution": rating_distribution,
        "access_distribution": access_distribution,
        "risk_segment_distribution": risk_segment_distribution,
        "watchlist": ordered_results[:10],
    }


def _distribution(rows: list[dict], key: str) -> dict[str, int]:
    distribution: dict[str, int] = {}
    for item in rows:
        value = str(item.get(key) or "未分类")
        distribution[value] = distribution.get(value, 0) + 1
    return dict(sorted(distribution.items(), key=lambda item: (-item[1], item[0])))
