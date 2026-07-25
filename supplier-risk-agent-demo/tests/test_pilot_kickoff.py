from __future__ import annotations

import unittest

from rating.pilot_kickoff import build_pilot_kickoff_markdown, build_pilot_kickoff_package


class PilotKickoffTest(unittest.TestCase):
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

    def test_builds_pilot_kickoff_package_sections(self) -> None:
        package = build_pilot_kickoff_package(self.flow, self.guidance)

        self.assertEqual(package["package_title"], "江门启航智能装备有限公司｜风控/内控负责人试点启动包")
        self.assertIn("启动会目标", package)
        self.assertIn("客户准备清单", package)
        self.assertIn("我方准备清单", package)
        self.assertIn("启动会议程", package)
        self.assertIn("验收口径", package)
        self.assertIn("下一步任务", package)
        self.assertTrue(any(item["准备事项"] == "首批试点样本" for item in package["客户准备清单"]))
        self.assertTrue(any(item["议题"] == "确认试点范围" for item in package["启动会议程"]))

    def test_markdown_contains_kickoff_actions_and_acceptance(self) -> None:
        package = build_pilot_kickoff_package(self.flow, self.guidance)
        markdown = build_pilot_kickoff_markdown(package)

        self.assertIn("# 江门启航智能装备有限公司｜风控/内控负责人试点启动包", markdown)
        self.assertIn("## 客户准备清单", markdown)
        self.assertIn("## 启动会议程", markdown)
        self.assertIn("## 验收口径", markdown)
        self.assertIn("规则可配置", markdown)
        self.assertIn("D / 禁入 / 禁入客商", markdown)


if __name__ == "__main__":
    unittest.main()
