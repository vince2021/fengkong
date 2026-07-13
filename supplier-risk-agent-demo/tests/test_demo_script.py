from __future__ import annotations

import unittest

from rating.demo_script import build_demo_script


class DemoScriptTest(unittest.TestCase):
    def test_builds_executive_and_business_demo_versions(self) -> None:
        flow = {
            "scenario_title": "深圳星海科技有限公司｜供应商准入评级演示",
            "summary": {
                "最终评级": "AA",
                "准入策略": "自动准入",
                "风险分层": "优质客商",
                "人工复核": "无需",
            },
            "steps": [
                {"step_name": "资料接收", "demo_value": "让客户看到 Agent 嵌入准入流程。"},
                {"step_name": "主体核验", "demo_value": "对应 KYB/供应商主体核验入口。"},
                {"step_name": "评分卡计算", "demo_value": "配置变化会影响评级结果。"},
                {"step_name": "报告输出", "demo_value": "落到客户能带走的交付物。"},
            ],
            "final_outputs": [
                {"交付物": "客商信用评级审核报告", "用途": "准入审批"},
            ],
        }

        script = build_demo_script(flow)

        self.assertIn("5 分钟高管版", script["versions"])
        self.assertIn("15 分钟业务版", script["versions"])
        self.assertGreaterEqual(len(script["versions"]["5 分钟高管版"]), 4)
        self.assertGreaterEqual(len(script["versions"]["15 分钟业务版"]), 6)
        self.assertTrue(any("人机边界" in item["answer"] for item in script["objection_responses"]))
        self.assertTrue(any(item["item"] == "准备一个高风险样本和一个优质样本" for item in script["pre_demo_checklist"]))

    def test_script_uses_flow_result_in_opening_and_close(self) -> None:
        flow = {
            "scenario_title": "江门启航智能装备有限公司｜客户准入评级演示",
            "summary": {
                "最终评级": "D",
                "准入策略": "禁入",
                "风险分层": "禁入客商",
                "人工复核": "需要",
            },
            "steps": [
                {"step_name": "强规则判断", "demo_value": "说明哪些事情不能完全交给模型分数决定。"},
                {"step_name": "人工复核", "demo_value": "审批责任仍由人承担。"},
                {"step_name": "报告输出", "demo_value": "生成评级审核报告和审计留痕。"},
            ],
            "final_outputs": [
                {"交付物": "风险证据链", "用途": "解释评级结果"},
            ],
        }

        script = build_demo_script(flow)

        opening = script["versions"]["5 分钟高管版"][0]["talk_track"]
        close = script["closing"]
        self.assertIn("江门启航智能装备有限公司", opening)
        self.assertIn("D", opening)
        self.assertIn("禁入", close)
        self.assertIn("下一步", close)


if __name__ == "__main__":
    unittest.main()
