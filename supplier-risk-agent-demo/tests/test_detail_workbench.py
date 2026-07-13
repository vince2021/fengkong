from __future__ import annotations

import json
import unittest
from pathlib import Path

from rating.detail_workbench import build_detail_workbench
from rating.risk_intelligence import build_agent_timeline, build_counterparty_profile
from rating.scorecard import rate_counterparty


class DetailWorkbenchTest(unittest.TestCase):
    def setUp(self) -> None:
        base = Path(__file__).resolve().parents[1]
        self.templates = json.loads((base / "data" / "model_templates.json").read_text(encoding="utf-8"))["templates"]
        self.counterparties = json.loads((base / "data" / "counterparties.json").read_text(encoding="utf-8"))

    def test_builds_professional_detail_workbench(self) -> None:
        config = self.templates["tech_enterprise_basic"]
        counterparty = next(item for item in self.counterparties if item["id"] == "cp_tech_low_001")
        result = rate_counterparty(counterparty, config)
        profile = build_counterparty_profile(counterparty, result)
        timeline = build_agent_timeline(counterparty, result)

        workbench = build_detail_workbench(counterparty, result, profile, timeline)

        self.assertIn("dossier", workbench)
        self.assertIn("evidence_groups", workbench)
        self.assertIn("approval_panel", workbench)
        self.assertIn("audit_timeline", workbench)
        self.assertEqual(workbench["dossier"]["企业名称"], "江门启航智能装备有限公司")
        self.assertTrue(any(group["title"] == "外部风险证据" for group in workbench["evidence_groups"]))
        self.assertTrue(any(group["title"] == "科创评价证据" for group in workbench["evidence_groups"]))
        self.assertIn("建议动作", workbench["approval_panel"])
        self.assertTrue(workbench["approval_panel"]["需人工复核"])
        self.assertGreaterEqual(len(workbench["audit_timeline"]), 5)
        self.assertEqual(workbench["audit_timeline"][0]["节点"], "资料接收")


if __name__ == "__main__":
    unittest.main()
