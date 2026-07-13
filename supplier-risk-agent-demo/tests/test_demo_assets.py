from __future__ import annotations

import unittest

from rating.demo_assets import build_demo_assets, build_assets_markdown


class DemoAssetsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.flow = {
            "scenario_title": "江门启航智能装备有限公司｜客户准入评级演示",
            "summary": {
                "最终评级": "D",
                "准入策略": "禁入",
                "风险分层": "禁入客商",
                "人工复核": "需要",
            },
            "final_outputs": [
                {"交付物": "客商信用评级审核报告", "用途": "准入审批、审计归档、管理层汇报"},
                {"交付物": "风险证据链", "用途": "解释评级结果、支持人工复核"},
            ],
        }
        self.guidance = {
            "role_label": "风控/内控负责人",
            "core_question": "模型规则是否可解释、强规则是否可治理、人工复核和审计留痕是否完整？",
            "focus_points": ["强规则治理", "评分解释", "人工复核", "审计留痕"],
            "success_criteria": ["规则可配置", "证据可解释", "审计链路可追溯"],
            "next_action": "建议先共创一版准入规则清单和报告模板，再用历史案例做回放验证。",
        }

    def test_builds_sales_assets_from_flow_and_audience(self) -> None:
        assets = build_demo_assets(self.flow, self.guidance)

        self.assertEqual(assets["asset_title"], "江门启航智能装备有限公司｜风控/内控负责人获客资产包")
        self.assertIn("一页式方案摘要", assets)
        self.assertIn("客户沟通纪要模板", assets)
        self.assertIn("试点方案清单", assets)
        self.assertIn("下一步行动计划", assets)
        self.assertTrue(any(item["模块"] == "目标客户" for item in assets["一页式方案摘要"]))
        self.assertTrue(any("强规则治理" in item["内容"] for item in assets["一页式方案摘要"]))
        self.assertTrue(any(item["事项"] == "确认试点样本范围" for item in assets["下一步行动计划"]))

    def test_markdown_contains_all_assets_and_current_rating_result(self) -> None:
        assets = build_demo_assets(self.flow, self.guidance)
        markdown = build_assets_markdown(assets)

        self.assertIn("# 江门启航智能装备有限公司｜风控/内控负责人获客资产包", markdown)
        self.assertIn("## 一页式方案摘要", markdown)
        self.assertIn("## 客户沟通纪要模板", markdown)
        self.assertIn("## 试点方案清单", markdown)
        self.assertIn("D / 禁入 / 禁入客商", markdown)


if __name__ == "__main__":
    unittest.main()
