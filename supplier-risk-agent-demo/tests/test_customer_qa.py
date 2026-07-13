from __future__ import annotations

import json
import unittest
from pathlib import Path

from app_credit_rating import resolve_template
from rating.customer_qa import build_customer_qa_bank, flatten_customer_questions


class CustomerQaTest(unittest.TestCase):
    def setUp(self) -> None:
        base = Path(__file__).resolve().parents[1]
        self.templates = json.loads((base / "data" / "model_templates.json").read_text(encoding="utf-8"))["templates"]

    def test_builds_customer_qa_categories_for_sales_demo(self) -> None:
        config = resolve_template("pharma", self.templates)

        qa_bank = build_customer_qa_bank("pharma", config)
        categories = [item["category"] for item in qa_bank["categories"]]
        questions = flatten_customer_questions(qa_bank)
        combined_text = "\n".join(item["answer"] for item in questions)

        self.assertEqual(categories, ["数据接入", "技术架构", "模型解释", "人机边界", "审计合规", "落地周期"])
        self.assertGreaterEqual(len(questions), 12)
        self.assertEqual(qa_bank["industry_label"], "医药流通")
        self.assertIn("MCP", combined_text)
        self.assertIn("RAG", combined_text)
        self.assertIn("人工复核", combined_text)
        self.assertIn("模型版本", combined_text)

    def test_answers_change_with_industry_template_context(self) -> None:
        construction = build_customer_qa_bank("construction", resolve_template("construction", self.templates))
        logistics = build_customer_qa_bank("logistics", resolve_template("logistics", self.templates))

        self.assertIn("工程建筑", construction["opening"])
        self.assertIn("项目", "\n".join(item["answer"] for item in flatten_customer_questions(construction)))
        self.assertIn("物流供应链", logistics["opening"])
        self.assertIn("履约", "\n".join(item["answer"] for item in flatten_customer_questions(logistics)))


if __name__ == "__main__":
    unittest.main()
