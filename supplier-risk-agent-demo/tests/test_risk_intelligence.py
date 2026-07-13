from __future__ import annotations

import json
import unittest
from pathlib import Path

from rating.risk_intelligence import (
    build_agent_timeline,
    build_counterparty_profile,
    build_portfolio_dashboard,
)
from rating.scorecard import rate_counterparties, rate_counterparty


class RiskIntelligenceTest(unittest.TestCase):
    def setUp(self) -> None:
        base = Path(__file__).resolve().parents[1]
        self.templates = json.loads((base / "data" / "model_templates.json").read_text(encoding="utf-8"))["templates"]
        self.counterparties = json.loads((base / "data" / "counterparties.json").read_text(encoding="utf-8"))

    def test_builds_portfolio_dashboard_for_management_view(self) -> None:
        config = self.templates["general"]
        general_counterparties = [item for item in self.counterparties if item["industry"] == "general"]
        results = rate_counterparties(general_counterparties, config)

        dashboard = build_portfolio_dashboard(general_counterparties, results)

        self.assertEqual(dashboard["total_counterparties"], 6)
        self.assertGreater(dashboard["requested_limit_total"], 0)
        self.assertGreater(dashboard["suggested_limit_total"], 0)
        self.assertGreater(dashboard["limit_reduction_amount"], 0)
        self.assertGreaterEqual(dashboard["review_required_count"], 1)
        self.assertGreaterEqual(dashboard["high_risk_count"], 1)
        self.assertGreaterEqual(dashboard["strong_rule_hit_count"], 1)
        self.assertIn("额度暴露", dashboard["management_actions"][0]["action"])
        self.assertTrue(dashboard["watchlist"])

    def test_builds_counterparty_profile_with_business_sections(self) -> None:
        config = self.templates["tech_enterprise_basic"]
        counterparty = next(item for item in self.counterparties if item["id"] == "cp_tech_high_001")
        result = rate_counterparty(counterparty, config)

        profile = build_counterparty_profile(counterparty, result)

        self.assertEqual(profile["basic"]["企业名称"], "深圳星河智造科技有限公司")
        self.assertIn("主体画像", profile)
        self.assertIn("外部风险", profile)
        self.assertIn("内部履约", profile)
        self.assertIn("财务质量", profile)
        self.assertIn("科创能力", profile)
        self.assertTrue(any("知识产权" in item for item in profile["core_strengths"]))
        self.assertTrue(profile["management_suggestions"])

    def test_builds_agent_timeline_with_human_boundary(self) -> None:
        config = self.templates["tech_enterprise_basic"]
        counterparty = next(item for item in self.counterparties if item["id"] == "cp_tech_mid_001")
        result = rate_counterparty(counterparty, config)

        timeline = build_agent_timeline(counterparty, result)

        self.assertEqual(len(timeline), 8)
        self.assertEqual(timeline[0]["step"], "资料接收")
        self.assertEqual(timeline[-1]["step"], "人工复核")
        self.assertTrue(any(item["owner"] == "AI Agent" for item in timeline))
        self.assertTrue(any(item["owner"] == "人工复核" for item in timeline))
        self.assertTrue(all(item["output"] for item in timeline))


if __name__ == "__main__":
    unittest.main()
