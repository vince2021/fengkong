from __future__ import annotations

from rating.sample_scenarios import INDUSTRY_LABELS


TEMPLATE_INDUSTRY_MAP = {
    "general": "general",
    "pharma": "pharma",
    "manufacturing": "manufacturing",
    "construction": "construction",
    "logistics": "logistics",
    "tech_enterprise_basic": "tech_enterprise",
}


def preferred_industry_for_template(template_key: str) -> str:
    return TEMPLATE_INDUSTRY_MAP.get(template_key, "general")


def preferred_industry_label(template_key: str) -> str:
    industry = preferred_industry_for_template(template_key)
    return INDUSTRY_LABELS.get(industry, industry)


def preferred_industry_filter_label(template_key: str, available_labels) -> str:
    label = preferred_industry_label(template_key)
    return label if label in set(available_labels) else "全部"


def sort_counterparties_by_template_industry(counterparties: list[dict], template_key: str) -> list[dict]:
    preferred = preferred_industry_for_template(template_key)
    return [
        counterparty
        for _, counterparty in sorted(
            enumerate(counterparties),
            key=lambda item: (
                0 if item[1].get("industry") == preferred else 1,
                item[0],
            ),
        )
    ]


def sort_results_by_template_industry(results: list[dict], counterparties: list[dict], template_key: str) -> list[dict]:
    ordered_counterparties = sort_counterparties_by_template_industry(counterparties, template_key)
    rank_by_id = {item["id"]: index for index, item in enumerate(ordered_counterparties)}
    original_rank = {item["counterparty_id"]: index for index, item in enumerate(results)}
    return sorted(
        results,
        key=lambda item: (
            rank_by_id.get(item["counterparty_id"], len(rank_by_id)),
            original_rank[item["counterparty_id"]],
        ),
    )
