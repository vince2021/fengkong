from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from rating.demo_flow import build_demo_flow
from rating.detail_workbench import build_detail_workbench
from rating.risk_intelligence import build_agent_timeline, build_counterparty_profile
from rating.risk_screening_policy import DEFAULT_RISK_SCREENING_POLICY
from rating.scorecard import rate_counterparty


class DemoFlowTest(unittest.TestCase):
    def setUp(self) -> None:
        base = Path(__file__).resolve().parents[1]
        self.templates = json.loads((base / "data" / "model_templates.json").read_text(encoding="utf-8"))["templates"]
        self.counterparties = json.loads((base / "data" / "counterparties.json").read_text(encoding="utf-8"))

    def test_builds_step_by_step_demo_flow_for_risky_counterparty(self) -> None:
        config = self.templates["tech_enterprise_basic"]
        counterparty = next(item for item in self.counterparties if item["id"] == "cp_tech_low_001")
        result = rate_counterparty(counterparty, config)
        profile = build_counterparty_profile(counterparty, result)
        timeline = build_agent_timeline(counterparty, result)
        workbench = build_detail_workbench(counterparty, result, profile, timeline)

        flow = build_demo_flow(counterparty, result, workbench, config)

        self.assertEqual(flow["scenario_title"], "江门启航智能装备有限公司｜客户准入评级演示")
        self.assertGreaterEqual(len(flow["steps"]), 7)
        self.assertTrue(any(step["step_name"] == "强规则判断" for step in flow["steps"]))
        self.assertTrue(any(step["tone"] == "danger" for step in flow["steps"]))
        self.assertIn("人机边界", flow["talk_tracks"][0])
        self.assertEqual(flow["summary"]["模型版本"], config["version"])
        self.assertEqual(flow["summary"]["最终评级"], result["rating"])
        self.assertEqual(flow["final_outputs"][0]["交付物"], "客商信用评级审核报告")

    def test_review_step_reflects_when_manual_review_is_not_required(self) -> None:
        config = deepcopy(self.templates["tech_enterprise_basic"])
        config["risk_screening_policy"] = deepcopy(DEFAULT_RISK_SCREENING_POLICY)
        config["risk_screening_policy"]["enabled"] = False
        counterparty = next(item for item in self.counterparties if item["id"] == "cp_tech_high_001")
        result = rate_counterparty(counterparty, config)
        profile = build_counterparty_profile(counterparty, result)
        timeline = build_agent_timeline(counterparty, result)
        workbench = build_detail_workbench(counterparty, result, profile, timeline)

        flow = build_demo_flow(counterparty, result, workbench, config)
        review_step = next(step for step in flow["steps"] if step["step_name"] == "人工复核")

        self.assertEqual(review_step["tone"], "success")
        self.assertIn("可按模型建议", review_step["human_decision"])


if __name__ == "__main__":
    unittest.main()
