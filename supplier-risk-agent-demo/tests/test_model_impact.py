from __future__ import annotations

import json
import unittest
from pathlib import Path

from app_credit_rating import COUNTERPARTIES_PATH, MODEL_TEMPLATES_PATH, resolve_template
from rating.model_impact import build_score_calculation_trace, simulate_indicator_change
from rating.model_impact import get_editable_indicators


class ModelImpactTest(unittest.TestCase):
    def setUp(self) -> None:
        templates = json.loads(Path(MODEL_TEMPLATES_PATH).read_text(encoding="utf-8"))["templates"]
        self.config = resolve_template("general", templates)
        self.counterparty = json.loads(Path(COUNTERPARTIES_PATH).read_text(encoding="utf-8"))[0]

    def test_exposes_dimension_formula_and_indicator_deductions(self) -> None:
        trace = build_score_calculation_trace(self.counterparty, self.config)
        self.assertTrue(trace["ok"])
        self.assertEqual(len(trace["dimension_contributions"]), 4)
        self.assertTrue(all("加权贡献" in row and "计算公式" in row for row in trace["dimension_contributions"]))
        self.assertIn("总分", trace["formula"])

    def test_local_indicator_change_recalculates_final_credit_result(self) -> None:
        impact = simulate_indicator_change(self.counterparty, self.config, "financial.overdue_rate", 0.5)
        self.assertEqual(impact["new_value"], 0.5)
        self.assertLessEqual(impact["impact"]["总分变化"], 0)
        self.assertIn("→", impact["impact"]["评级变化"])
        self.assertIn("额度变化", impact["impact"])

    def test_invalid_weights_return_explainable_error_instead_of_missing_fields(self) -> None:
        self.config["weights"]["external_risk"] = 0.9
        trace = build_score_calculation_trace(self.counterparty, self.config)
        impact = simulate_indicator_change(self.counterparty, self.config, "financial.overdue_rate", 0.5)

        self.assertFalse(trace["ok"])
        self.assertIn("formula", trace)
        self.assertEqual(trace["dimension_contributions"], [])
        self.assertFalse(impact["ok"])
        self.assertIn("error", impact)

    def test_selected_pool_indicator_recalculates_independent_risk_screening(self) -> None:
        paths = {item["path"] for item in get_editable_indicators(self.config)}
        self.assertIn("external.shareholder_change_count_1y", paths)

        impact = simulate_indicator_change(self.counterparty, self.config, "external.shareholder_change_count_1y", 3)

        self.assertTrue(impact["ok"])
        self.assertLess(impact["impact"]["企业风险筛查分变化"], 0)
        self.assertGreater(impact["impact"]["企业风险完整度变化"], 0)
        self.assertEqual(impact["impact"]["总分变化"], 0)
        self.assertIn("→", impact["impact"]["企业风险贷策命中变化"])
        self.assertTrue(impact["after"]["risk_screening_policy"]["hits"])


if __name__ == "__main__":
    unittest.main()
