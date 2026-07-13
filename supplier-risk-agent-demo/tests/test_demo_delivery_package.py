from __future__ import annotations

import unittest

from rating.demo_delivery_package import build_delivery_package, build_delivery_package_markdown


class DemoDeliveryPackageTest(unittest.TestCase):
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
            "core_question": "模型规则是否可解释、强规则是否可治理、人工复核和审计留痕是否完整？",
            "next_action": "建议先共创一版准入规则清单和报告模板。",
        }
        self.script = {
            "versions": {
                "5 分钟高管版": [
                    {"section": "开场定位", "talk_track": "展示完整准入链路。", "screen_focus": "演示流程 Tab。"}
                ]
            },
            "objection_responses": [{"question": "AI 会不会替代审批人？", "answer": "不会，人机边界清晰。"}],
            "pre_demo_checklist": [{"item": "准备一个高风险样本和一个优质样本", "reason": "展示差异。"}],
            "closing": "下一步可以用真实字段做小范围试点。",
        }
        self.assets = {
            "asset_title": "江门启航智能装备有限公司｜风控/内控负责人获客资产包",
            "一页式方案摘要": [{"模块": "当前样本结论", "内容": "D / 禁入 / 禁入客商"}],
            "客户沟通纪要模板": [{"记录项": "客户角色与部门", "待记录内容": "风控/内控负责人"}],
            "试点方案清单": [{"阶段": "试点准备", "事项": "确认试点客商范围", "产出": "样本清单"}],
            "下一步行动计划": [{"事项": "确认试点样本范围", "负责人": "客户业务/风控负责人", "建议周期": "1-3 天"}],
        }
        self.pilot = {
            "workspace_title": "江门启航智能装备有限公司｜风控/内控负责人试点工作台",
            "试点目标": [{"目标": "验证业务流程", "说明": "跑通完整链路"}],
            "阶段路线图": [{"阶段": "规则共创", "负责人": "双方项目组", "周期": "3-5 天", "产出": "规则清单"}],
            "字段清单": [{"字段类型": "外部企业风险数据", "字段示例": "司法案件", "数据来源": "企查查 API/MCP", "优先级": "必须"}],
            "样本清单": [{"样本类型": "高风险/禁入样本", "建议数量": "5-10 家", "用途": "验证强规则"}],
            "验收指标": [{"指标": "评级解释可读性", "验收口径": "业务可理解", "目标": "通过业务评审"}],
            "风险与依赖": [{"风险": "内部数据缺失", "影响": "评分维度不完整", "应对": "先跑 MVP"}],
        }

    def test_builds_delivery_package_summary_and_sections(self) -> None:
        package = build_delivery_package(self.flow, self.guidance, self.script, self.assets, self.pilot)

        self.assertEqual(package["package_title"], "江门启航智能装备有限公司｜风控/内控负责人完整交付包")
        self.assertEqual(package["cover_summary"]["目标角色"], "风控/内控负责人")
        self.assertEqual(package["cover_summary"]["评级结论"], "D / 禁入 / 禁入客商")
        self.assertIn("演示脚本", package["sections"])
        self.assertIn("获客资产", package["sections"])
        self.assertIn("试点工作台", package["sections"])

    def test_markdown_contains_all_package_parts(self) -> None:
        package = build_delivery_package(self.flow, self.guidance, self.script, self.assets, self.pilot)
        markdown = build_delivery_package_markdown(package)

        self.assertIn("# 江门启航智能装备有限公司｜风控/内控负责人完整交付包", markdown)
        self.assertIn("## 封面摘要", markdown)
        self.assertIn("## 演示脚本", markdown)
        self.assertIn("## 获客资产", markdown)
        self.assertIn("## 试点工作台", markdown)
        self.assertIn("D / 禁入 / 禁入客商", markdown)


if __name__ == "__main__":
    unittest.main()
