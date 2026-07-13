from __future__ import annotations

import json
import unittest
from pathlib import Path

from rating.scorecard import rate_counterparty
from reports.report import build_credit_rating_report


class CreditRatingReportTest(unittest.TestCase):
    def test_builds_tech_credit_rating_report_with_key_sections(self) -> None:
        base = Path(__file__).resolve().parents[1]
        templates = json.loads((base / "data" / "model_templates.json").read_text(encoding="utf-8"))["templates"]
        counterparties = json.loads((base / "data" / "counterparties.json").read_text(encoding="utf-8"))
        config = templates["tech_enterprise_basic"]
        counterparty = next(item for item in counterparties if item["id"] == "cp_tech_high_001")
        result = rate_counterparty(counterparty, config)
        review_records = [
            {
                "时间": "2026-07-11 22:55:00",
                "客商": result["counterparty_name"],
                "模型评级": result["rating"],
                "模型策略": result["access_strategy"],
                "模型额度": "30,000,000 元",
                "复核动作": "调整建议额度",
                "复核后策略": "准入",
                "复核后额度": "25,000,000 元",
                "复核原因": "考虑订单集中度，额度略下调。",
            }
        ]

        report = build_credit_rating_report(counterparty, result, config, review_records)

        self.assertIn("# 客商信用评级审核报告", report)
        self.assertIn("深圳星河智造科技有限公司", report)
        self.assertIn("## 一、模型评级结论", report)
        self.assertIn("- 总分：190", report)
        self.assertIn("## 二、评分卡逐项解释", report)
        self.assertIn("高层次人才", report)
        self.assertIn("## 三、强规则命中", report)
        self.assertIn("## 四、额度审批数据依据", report)
        self.assertIn("核心研发人员占比", report)
        self.assertIn("## 五、人工复核与审计留痕", report)
        self.assertIn("考虑订单集中度，额度略下调。", report)
        self.assertIn("模型版本：TECH-BASE-20260711-001", report)
        self.assertIn("## 六、企业风险画像", report)
        self.assertIn("### 核心优势", report)
        self.assertIn("### 核心风险", report)
        self.assertIn("## 七、Agent 执行链路", report)
        self.assertIn("评分卡计算", report)
        self.assertIn("## 八、后续监控建议", report)
        self.assertIn("按季度监控", report)


if __name__ == "__main__":
    unittest.main()
