from __future__ import annotations

import json
import unittest
from pathlib import Path

from app_credit_rating import COUNTERPARTIES_PATH, MODEL_TEMPLATES_PATH, resolve_template
from rating.pilot_field_mapping import build_pilot_field_mapping_package
from rating.pilot_task_board import build_pilot_task_board
from rating.pilot_value_review import build_pilot_value_review, build_pilot_value_review_markdown
from rating.scorecard import rate_counterparties


class PilotValueReviewTest(unittest.TestCase):
    def setUp(self) -> None:
        templates = json.loads(Path(MODEL_TEMPLATES_PATH).read_text(encoding="utf-8"))["templates"]
        counterparties = json.loads(Path(COUNTERPARTIES_PATH).read_text(encoding="utf-8"))
        self.model_config = resolve_template("pharma", templates)
        self.results = [item for item in rate_counterparties(counterparties, self.model_config) if item.get("ok")]
        mapping_package = build_pilot_field_mapping_package("pharma", self.model_config)
        self.task_board = build_pilot_task_board(mapping_package)
        self.mapping_package = mapping_package

    def test_builds_management_value_review(self) -> None:
        review = build_pilot_value_review(self.mapping_package, self.task_board, self.results)

        self.assertEqual(review["title"], "医药流通试点复盘与价值评估")
        self.assertIn("summary", review)
        self.assertIn("value_metrics", review)
        self.assertIn("risk_findings", review)
        self.assertIn("field_gap_impact", review)
        self.assertIn("poc_recommendation", review)
        self.assertIn("样本数量", review["summary"])
        self.assertGreaterEqual(len(review["value_metrics"]), 4)
        self.assertGreaterEqual(len(review["risk_findings"]), 1)
        self.assertTrue(any("风险" in row["业务解释"] for row in review["value_metrics"]))

    def test_links_field_gaps_to_poc_decision(self) -> None:
        review = build_pilot_value_review(self.mapping_package, self.task_board, self.results)

        self.assertGreaterEqual(len(review["field_gap_impact"]), 6)
        self.assertTrue(all("上线影响" in row and row["建议处理"] for row in review["field_gap_impact"]))
        self.assertTrue(any(row["字段名"] == "登记状态" and row["当前状态"] == "待映射" for row in review["field_gap_impact"]))
        self.assertEqual(review["summary"]["字段缺口"], f"{len(self.task_board['risk_tasks'])} 项")
        self.assertTrue(any(row["评估项"] == "建议结论" for row in review["poc_recommendation"]))
        self.assertTrue(any("POC" in row["结论"] for row in review["poc_recommendation"]))

    def test_markdown_is_customer_ready(self) -> None:
        review = build_pilot_value_review(self.mapping_package, self.task_board, self.results)
        markdown = build_pilot_value_review_markdown(review)

        self.assertIn("# 医药流通试点复盘与价值评估", markdown)
        self.assertIn("## 价值指标", markdown)
        self.assertIn("## 风险识别结果", markdown)
        self.assertIn("## 字段缺口影响", markdown)
        self.assertIn("## POC 建议", markdown)
        self.assertNotIn("TODO", markdown)


if __name__ == "__main__":
    unittest.main()
