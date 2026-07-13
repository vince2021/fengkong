from __future__ import annotations


def get_mapping_for_score(total_score: float, strategy_mapping: list[dict]) -> dict:
    for mapping in strategy_mapping:
        if mapping["score_min"] <= total_score <= mapping["score_max"]:
            return dict(mapping)

    return dict(sorted(strategy_mapping, key=lambda item: item["score_min"])[0])


def get_mapping_by_rating(rating: str, strategy_mapping: list[dict]) -> dict:
    for mapping in strategy_mapping:
        if mapping["rating"] == rating:
            return dict(mapping)
    return get_mapping_for_score(0, strategy_mapping)


def apply_strategy_mapping(counterparty: dict, rating: str, config: dict) -> dict:
    mapping = get_mapping_by_rating(rating, config["strategy_mapping"])
    requested_limit = counterparty.get("requested_limit", 0)
    suggested_limit = int(requested_limit * mapping["limit_multiplier"])

    return {
        "rating": mapping["rating"],
        "risk_segment": mapping["risk_segment"],
        "access_strategy": mapping["access_strategy"],
        "suggested_limit": suggested_limit,
        "payment_term_days": mapping["payment_term_days"],
        "monitoring_frequency": mapping["monitoring_frequency"],
        "review_required": mapping["access_strategy"] in {"人工复核", "限制准入", "审慎准入", "禁入"},
        "base_limit_multiplier": mapping["limit_multiplier"],
    }

