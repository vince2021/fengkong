from __future__ import annotations

import unittest

from rating.demo_pilot import build_pilot_workspace, build_pilot_markdown


class DemoPilotTest(unittest.TestCase):
    def setUp(self) -> None:
        self.flow = {
            "scenario_title": "江门启航智能装备有限公司｜客户准入评级演示",
            "summary": {
                "最终评级": "D",
                "准入策略": "禁入",
                "风险分层": "禁入客商",
                "人工复核": "需要",
            },
        }
        self.guidance = {
            "role_label": "风控/内控负责人",
            "focus_points": ["强规则治理", "评分解释", "人工复核", "审计留痕"],
            "success_criteria": ["规则可配置", "证据可解释", "审计链路可追溯"],
            "next_action": "建议先共创一版准入规则清单和报告模板，再用历史案例做回放验证。",
        }

    def test_builds_pilot_workspace_sections(self) -> None:
        workspace = build_pilot_workspace(self.flow, self.guidance)

        self.assertEqual(workspace["workspace_title"], "江门启航智能装备有限公司｜风控/内控负责人试点工作台")
        self.assertIn("试点目标", workspace)
        self.assertIn("阶段路线图", workspace)
        self.assertIn("字段清单", workspace)
        self.assertIn("样本清单", workspace)
        self.assertIn("验收指标", workspace)
        self.assertIn("风险与依赖", workspace)
        self.assertTrue(any(item["阶段"] == "规则共创" for item in workspace["阶段路线图"]))
        self.assertTrue(any(item["字段类型"] == "外部企业风险数据" for item in workspace["字段清单"]))
        self.assertTrue(any(item["指标"] == "评级解释可读性" for item in workspace["验收指标"]))

    def test_markdown_contains_pilot_plan_and_current_result(self) -> None:
        workspace = build_pilot_workspace(self.flow, self.guidance)
        markdown = build_pilot_markdown(workspace)

        self.assertIn("# 江门启航智能装备有限公司｜风控/内控负责人试点工作台", markdown)
        self.assertIn("## 阶段路线图", markdown)
        self.assertIn("## 字段清单", markdown)
        self.assertIn("D / 禁入 / 禁入客商", markdown)


if __name__ == "__main__":
    unittest.main()
