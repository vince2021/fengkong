from __future__ import annotations

import unittest

from rating.demo_audience import AUDIENCE_OPTIONS, build_audience_guidance


class DemoAudienceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.flow = {
            "scenario_title": "江门启航智能装备有限公司｜客户准入评级演示",
            "summary": {
                "最终评级": "D",
                "准入策略": "禁入",
                "风险分层": "禁入客商",
                "人工复核": "需要",
            },
            "steps": [
                {"step_name": "外部风险扫描", "demo_value": "把外部数据升级为可审计的风险证据。"},
                {"step_name": "评分卡计算", "demo_value": "配置变化会影响评级结果。"},
                {"step_name": "强规则判断", "demo_value": "回答哪些事情不能完全交给模型分数决定。"},
                {"step_name": "人工复核", "demo_value": "清晰展示人机边界。"},
            ],
        }

    def test_provides_supported_audience_options(self) -> None:
        labels = [item["label"] for item in AUDIENCE_OPTIONS]

        self.assertIn("管理层", labels)
        self.assertIn("风控/内控负责人", labels)
        self.assertIn("采购/供应商管理", labels)
        self.assertIn("销售/客户管理", labels)
        self.assertIn("IT/数据负责人", labels)

    def test_builds_risk_control_guidance_with_audit_and_rules_focus(self) -> None:
        guidance = build_audience_guidance("risk_control", self.flow)

        self.assertEqual(guidance["role_label"], "风控/内控负责人")
        self.assertTrue(any("强规则" in item for item in guidance["focus_points"]))
        self.assertTrue(any("审计" in item for item in guidance["success_criteria"]))
        self.assertTrue(any("人机边界" in row["answer"] for row in guidance["likely_questions"]))
        self.assertIn("模型配置中心", guidance["screen_route"])

    def test_builds_management_guidance_with_business_outcome_focus(self) -> None:
        guidance = build_audience_guidance("management", self.flow)

        self.assertEqual(guidance["role_label"], "管理层")
        self.assertIn("决策效率", " ".join(guidance["focus_points"]))
        self.assertIn("小范围试点", guidance["next_action"])
        self.assertIn("D / 禁入", guidance["opening_line"])

    def test_unknown_role_falls_back_to_risk_control(self) -> None:
        guidance = build_audience_guidance("unknown", self.flow)

        self.assertEqual(guidance["role_key"], "risk_control")


if __name__ == "__main__":
    unittest.main()
