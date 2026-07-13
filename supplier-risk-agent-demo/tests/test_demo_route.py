from __future__ import annotations

import json
import unittest
from pathlib import Path

from app_credit_rating import resolve_template
from rating.demo_route import build_demo_route, build_demo_route_markdown


class DemoRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        base = Path(__file__).resolve().parents[1]
        self.templates = json.loads((base / "data" / "model_templates.json").read_text(encoding="utf-8"))["templates"]

    def test_builds_face_to_face_demo_route_in_expected_order(self) -> None:
        route = build_demo_route("pharma", resolve_template("pharma", self.templates))
        page_keys = [step["page_key"] for step in route["steps"]]

        self.assertEqual(
            page_keys,
            [
                "product_samples",
                "industry_template",
                "demo_flow",
                "demo_script",
                "customer_qa",
                "sales_assets",
                "pilot_workspace",
            ],
        )
        self.assertEqual(route["industry_label"], "医药流通")
        self.assertIn("医药流通", route["opening"])
        self.assertEqual(route["steps"][0]["step_no"], "01")
        self.assertEqual(route["steps"][-1]["page_label"], "试点工作台")

    def test_each_step_has_sales_ready_guidance(self) -> None:
        route = build_demo_route("manufacturing", resolve_template("manufacturing", self.templates))

        for step in route["steps"]:
            self.assertTrue(step["title"])
            self.assertTrue(step["target_area"])
            self.assertTrue(step["demo_action"])
            self.assertTrue(step["talk_track"])
            self.assertTrue(step["customer_signal"])
            self.assertTrue(step["handoff"])

    def test_builds_downloadable_demo_route_markdown(self) -> None:
        route = build_demo_route("logistics", resolve_template("logistics", self.templates))

        markdown = build_demo_route_markdown(route)

        self.assertIn("# 面客演示路线手卡", markdown)
        self.assertIn("物流供应链", markdown)
        self.assertIn("模型版本", markdown)
        self.assertIn("## 01. 样本场景", markdown)
        self.assertIn("## 07. 试点工作台", markdown)
        self.assertIn("讲解主线", markdown)
        self.assertIn("下一步承接", markdown)
        self.assertNotIn("TODO", markdown)


if __name__ == "__main__":
    unittest.main()
