from __future__ import annotations

import json
import unittest
from pathlib import Path

from rating.sample_scenarios import build_sample_scenarios, count_scenarios_by_industry
from rating.scorecard import rate_counterparties


class SampleScenariosTest(unittest.TestCase):
    def setUp(self) -> None:
        base = Path(__file__).resolve().parents[1]
        self.templates = json.loads((base / "data" / "model_templates.json").read_text(encoding="utf-8"))["templates"]
        self.counterparties = json.loads((base / "data" / "counterparties.json").read_text(encoding="utf-8"))

    def test_counterparties_cover_more_industries_for_demo_storytelling(self) -> None:
        industries = {item["industry"] for item in self.counterparties}

        self.assertIn("pharma", industries)
        self.assertIn("manufacturing", industries)
        self.assertIn("construction", industries)
        self.assertIn("logistics", industries)
        self.assertIn("tech_enterprise", industries)
        self.assertIn("general", industries)
        self.assertGreaterEqual(len(self.counterparties), 13)

    def test_builds_sample_scenarios_with_risk_story_and_use_case(self) -> None:
        config = self.templates["general"]
        results = rate_counterparties(self.counterparties, config)

        scenarios = build_sample_scenarios(self.counterparties, results)
        counts = count_scenarios_by_industry(scenarios)

        self.assertTrue(any(item["行业"] == "医药流通" for item in scenarios))
        self.assertTrue(any(item["行业"] == "制造业" for item in scenarios))
        self.assertTrue(any(item["演示用途"] == "展示强规则禁入和人工复核" for item in scenarios))
        self.assertTrue(any(item["风险故事"] for item in scenarios))
        self.assertGreaterEqual(counts["通用"], 6)
        self.assertGreaterEqual(counts["科创企业"], 3)


if __name__ == "__main__":
    unittest.main()
