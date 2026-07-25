from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from rating.scorecard import rate_counterparty
from rating.template_resolver import resolve_template
from rating.model_impact import build_score_calculation_trace, get_editable_indicators, simulate_indicator_change


BASE_DIR = Path(__file__).resolve().parents[1]


def _fixtures() -> tuple[dict, dict]:
    templates = json.loads((BASE_DIR / "data" / "model_templates.json").read_text(encoding="utf-8"))["templates"]
    counterparties = json.loads((BASE_DIR / "data" / "counterparties.json").read_text(encoding="utf-8"))
    counterparty = next(item for item in counterparties if item["id"] == "cp_inalfa_guangzhou_001")
    return counterparty, resolve_template("corporate_credit_v2", templates)


def test_raw_profile_preserves_source_values_and_missing_boundaries() -> None:
    raw = json.loads((BASE_DIR / "data" / "raw_enterprise_profiles" / "inalfa_guangzhou.json").read_text(encoding="utf-8"))

    assert raw["entity"]["unified_social_credit_code"] == "91440101MA5AW31D00"
    assert raw["financial_statements"]["periods"][2]["revenue"] == 14636
    assert raw["financial_statements"]["derived_features"]["weighted_revenue_wan_cny"] == 20465.9
    assert raw["external_benchmark"]["report_score"] == 49.58
    assert raw["internal_transaction_data"]["orders"] is None


def test_material_enhanced_model_uses_matrix_rules_and_completeness() -> None:
    counterparty, config = _fixtures()

    result = rate_counterparty(counterparty, config)

    assert result["ok"] is True
    assert result["business_risk_band"] == 5
    assert result["financial_risk_band"] == 4
    assert result["dimension_scores"]["business_financial_anchor"] == 58
    assert result["base_score"] == 64.94
    assert result["risk_adjustment_score"] == -6
    assert result["total_score"] == 58.9
    assert result["rating"] == "B"
    assert result["access_strategy"] == "人工复核"
    assert result["submodel_completeness"]["transaction_behavior"] == 0
    assert result["data_completeness"] == 0.695
    assert {hit["rule_id"] for hit in result["strong_rule_hits"]} == {"CR-101", "CR-102", "CR-103", "CR-201"}


def test_local_growth_improvement_propagates_to_band_score_and_rules() -> None:
    counterparty, config = _fixtures()
    improved = deepcopy(counterparty)
    improved["corporate_profile"]["operations"]["sales_growth_pct"] = 8
    improved["corporate_profile"]["operations"]["profit_growth_pct"] = 6
    improved["corporate_profile"]["financial"]["net_profit_margin_change_pct"] = 5

    before = rate_counterparty(counterparty, config)
    after = rate_counterparty(improved, config)

    assert after["submodel_scores"]["business_risk"] > before["submodel_scores"]["business_risk"]
    assert after["total_score"] > before["total_score"]
    assert not {"CR-101", "CR-102", "CR-103"} & {hit["rule_id"] for hit in after["strong_rule_hits"]}


def test_dishonesty_rule_overrides_score_and_credit_strategy() -> None:
    counterparty, config = _fixtures()
    risky = deepcopy(counterparty)
    risky["external"]["dishonesty_count"] = 1
    risky["requested_limit"] = 2_000_000

    result = rate_counterparty(risky, config)

    assert result["rating"] == "D"
    assert result["access_strategy"] == "禁入"
    assert result["suggested_limit"] == 0
    assert result["suggested_payment_term_days"] == 0
    assert "CR-002" in {hit["rule_id"] for hit in result["strong_rule_hits"]}


def test_material_model_handles_non_material_sample_as_incomplete_not_exception() -> None:
    _, config = _fixtures()
    other = json.loads((BASE_DIR / "data" / "counterparties.json").read_text(encoding="utf-8"))[0]

    result = rate_counterparty(other, config)

    assert result["ok"] is True
    assert result["review_required"] is True
    assert result["data_completeness"] < 0.75


def test_trace_exposes_matrix_indicator_formula_and_data_quality() -> None:
    counterparty, config = _fixtures()

    trace = build_score_calculation_trace(counterparty, config)

    assert trace["ok"] is True
    assert trace["matrix_inputs"][2] == {"子模型": "矩阵查询", "得分": 58.0, "档位": "B5 × F4"}
    assert trace["data_quality"]["整体完整度"] == "69.5%"
    assert "矩阵锚点" in trace["formula"]
    assert len(trace["indicator_deductions"]) == 37
    assert any(item["数据状态"] == "待补充" for item in trace["indicator_deductions"])


def test_corporate_what_if_list_and_impact_use_whole_percentage_scale() -> None:
    counterparty, config = _fixtures()
    indicators = get_editable_indicators(config)
    growth = next(item for item in indicators if item["path"] == "corporate_profile.operations.sales_growth_pct")

    impact = simulate_indicator_change(counterparty, config, growth["path"], 8)

    assert growth["value_scale"] == "whole"
    assert impact["old_value"] == -33.34
    assert impact["new_value"] == 8
    assert impact["after"]["total_score"] > impact["before"]["total_score"]
    assert impact["impact"]["业务风险档位变化"].startswith("5 →")


def test_credit_limit_uses_minimum_capacity_and_rule_constraints() -> None:
    counterparty, config = _fixtures()
    candidate = deepcopy(counterparty)
    candidate["requested_limit"] = 10_000_000
    candidate["corporate_profile"]["operations"]["sales_growth_pct"] = 8
    candidate["corporate_profile"]["operations"]["profit_growth_pct"] = 6
    candidate["corporate_profile"]["financial"]["net_profit_margin_change_pct"] = 5

    result = rate_counterparty(candidate, config)

    assert result["raw_rating"] == "BBB"
    assert result["limit_calculation"]["候选上限"]["申请额度上限"] == 10_000_000
    assert result["limit_calculation"]["候选上限"]["等级系数上限"] == 5_000_000
    assert result["limit_calculation"]["约束项"] == "等级系数上限"
    assert result["limit_calculation"]["规则调整前额度"] == 5_000_000
    assert result["limit_calculation"]["规则调整后额度"] == 2_000_000
    assert result["suggested_limit"] == 2_000_000
    assert result["suggested_payment_term_days"] == 0
