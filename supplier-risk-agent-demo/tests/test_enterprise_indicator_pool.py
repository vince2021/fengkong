from __future__ import annotations

import json
import unittest
from pathlib import Path

from rating.enterprise_indicator_pool import (
    evaluate_indicator_pool,
    get_indicator_pool,
    list_enterprise_risk_indicators,
    validate_indicator_selection,
)
from rating.model_impact import build_score_calculation_trace, get_editable_indicators


class EnterpriseIndicatorPoolTest(unittest.TestCase):
    def setUp(self) -> None:
        base = Path(__file__).resolve().parents[1]
        self.templates = json.loads((base / "data" / "model_templates.json").read_text(encoding="utf-8"))["templates"]
        counterparties = json.loads((base / "data" / "counterparties.json").read_text(encoding="utf-8"))
        self.counterparty = next(item for item in counterparties if item.get("tech_enterprise"))

    def test_pool_preserves_source_indicators_and_adds_credit_policy_dimensions(self) -> None:
        pool = get_indicator_pool()
        self.assertEqual(pool["summary"]["indicator_count"], 201)
        self.assertEqual(len(pool["indicators"]), 201)
        self.assertGreaterEqual(len(pool["summary"]["category_counts"]), 10)
        self.assertTrue(all(item["source_references"] for item in pool["indicators"]))
        self.assertEqual(pool["summary"]["category_counts"]["财务承债能力"], 5)
        self.assertEqual(pool["summary"]["category_counts"]["交易履约表现"], 6)
        self.assertEqual(pool["summary"]["category_counts"]["信用敞口与回款"], 5)

    def test_credit_policy_indicators_score_real_values_and_degrade_missing_to_neutral(self) -> None:
        indicators = {item["name"]: item for item in list_enterprise_risk_indicators()}
        config = {"indicator_selection": [
            {"indicator_id": indicators["资产负债率"]["id"], "weight": 1, "enabled": True},
            {"indicator_id": indicators["应收逾期率"]["id"], "weight": 1, "enabled": True},
            {"indicator_id": indicators["交付达成率"]["id"], "weight": 1, "enabled": True},
        ]}
        result = evaluate_indicator_pool({
            "corporate_profile": {"financial": {"debt_to_assets_pct": 82}},
            "financial": {"overdue_rate": 0.02},
        }, config)
        details = {item["name"]: item for item in result["details"]}
        self.assertEqual(details["资产负债率"]["score"], 2)
        self.assertEqual(details["应收逾期率"]["score"], 3)
        self.assertEqual(details["交付达成率"]["score"], 2)
        self.assertEqual(details["交付达成率"]["data_status"], "待补充")

    def test_requested_change_rules_are_explicit_and_calculable(self) -> None:
        indicators = {item["name"]: item for item in list_enterprise_risk_indicators()}
        shareholder = indicators["股东变更"]
        joint_change = indicators["近一年法人及主要人员联合变更"]
        config = {
            "indicator_selection": [
                {"indicator_id": shareholder["id"], "weight": 1, "enabled": True},
                {"indicator_id": joint_change["id"], "weight": 1, "enabled": True},
            ]
        }
        low_risk = {
            "external": {
                "shareholder_change_count_1y": 0,
                "legal_representative_change_count_1y": 0,
                "key_person_change_count_1y": 0,
            }
        }
        high_risk = {
            "external": {
                "shareholder_change_count_1y": 3,
                "legal_representative_change_count_1y": 1,
                "key_person_change_count_1y": 2,
            }
        }
        self.assertEqual([item["score"] for item in evaluate_indicator_pool(low_risk, config)["details"]], [3, 3])
        self.assertEqual([item["score"] for item in evaluate_indicator_pool(high_risk, config)["details"]], [1, 1])

    def test_major_dispute_uses_case_count_not_litigation_amount(self) -> None:
        indicator = next(item for item in list_enterprise_risk_indicators() if item["name"] == "重大纠纷")
        self.assertEqual(indicator["field_path"], "external.legal_cases_count")
        self.assertEqual(indicator["data_type"], "count")

    def test_selection_validation_rejects_unknown_duplicate_and_bad_weight(self) -> None:
        errors, warnings = validate_indicator_selection(
            [
                {"indicator_id": "unknown", "weight": 0, "enabled": True},
                {"indicator_id": "unknown", "weight": 1, "enabled": True},
            ]
        )
        self.assertTrue(any("不存在" in item for item in errors))
        self.assertTrue(any("重复" in item for item in errors))
        self.assertTrue(any("相对权重" in item for item in errors))
        self.assertTrue(any("少于 3" in item for item in warnings))

    def test_tech_model_has_native_indicators_and_calculation_trace(self) -> None:
        config = self.templates["tech_enterprise_basic"]
        indicators = get_editable_indicators(config)
        trace = build_score_calculation_trace(self.counterparty, config)
        self.assertGreaterEqual(len(indicators), 19)
        self.assertTrue(trace["ok"])
        self.assertGreater(len(trace["indicator_deductions"]), 0)
        self.assertIn("基础评分", trace["formula"])

    def test_tech_support_rules_apply_cfda_growth_exemption(self) -> None:
        from rating.scorecard import rate_counterparty

        counterparty = json.loads(json.dumps(self.counterparty))
        counterparty["tech_enterprise"]["revenue_growth_rate"] = 0.01
        counterparty["tech_enterprise"]["cfda_new_drug_rd_enterprise"] = True
        result = rate_counterparty(counterparty, self.templates["tech_enterprise_basic"])
        growth = next(item for item in result["support_data_items"] if "CFDA" in item["indicator"])
        self.assertTrue(growth["passed"])
        self.assertIn("豁免", growth["evidence"])


if __name__ == "__main__":
    unittest.main()
