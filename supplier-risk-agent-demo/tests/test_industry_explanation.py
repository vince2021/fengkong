from __future__ import annotations

import json
import unittest
from pathlib import Path

from app_credit_rating import resolve_template
from rating.industry_explanation import build_industry_explanation


class IndustryExplanationTest(unittest.TestCase):
    def setUp(self) -> None:
        base = Path(__file__).resolve().parents[1]
        self.templates = json.loads((base / "data" / "model_templates.json").read_text(encoding="utf-8"))["templates"]

    def test_builds_pharma_explanation_with_weight_and_human_boundary(self) -> None:
        config = resolve_template("pharma", self.templates)

        explanation = build_industry_explanation("pharma", config)

        self.assertEqual(explanation["industry_label"], "医药流通")
        self.assertIn("药品", explanation["positioning"])
        self.assertEqual(len(explanation["weight_rationale"]), 4)
        self.assertTrue(any(item["权重"] == "45%" for item in explanation["weight_rationale"]))
        self.assertTrue(any("人工" in item["人机边界"] for item in explanation["human_boundaries"]))

    def test_builds_explanation_for_all_supported_templates(self) -> None:
        for template_key in ["general", "pharma", "manufacturing", "construction", "logistics", "tech_enterprise_basic"]:
            with self.subTest(template_key=template_key):
                config = resolve_template(template_key, self.templates)
                explanation = build_industry_explanation(template_key, config)

                self.assertTrue(explanation["industry_label"])
                self.assertGreaterEqual(len(explanation["risk_assumptions"]), 3)
                self.assertGreaterEqual(len(explanation["strong_rule_rationale"]), 4)
                self.assertGreaterEqual(len(explanation["talk_track"]), 4)


if __name__ == "__main__":
    unittest.main()
