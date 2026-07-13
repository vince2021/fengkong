from __future__ import annotations

import json
import unittest
from pathlib import Path

from app_credit_rating import resolve_template
from rating.demo_readiness import build_demo_readiness_checklist, build_demo_readiness_markdown
from rating.demo_route import build_demo_route


class DemoReadinessTest(unittest.TestCase):
    def setUp(self) -> None:
        base = Path(__file__).resolve().parents[1]
        self.templates = json.loads((base / "data" / "model_templates.json").read_text(encoding="utf-8"))["templates"]

    def test_builds_readiness_checklist_for_face_to_face_demo(self) -> None:
        route = build_demo_route("construction", resolve_template("construction", self.templates))

        readiness = build_demo_readiness_checklist(route)

        self.assertEqual(readiness["industry_label"], "工程建筑")
        self.assertEqual([section["section"] for section in readiness["sections"]], ["会前准备", "数据与样本", "现场控场", "试点转化"])
        self.assertGreaterEqual(sum(len(section["items"]) for section in readiness["sections"]), 12)
        self.assertTrue(any("样本" in item["检查项"] for section in readiness["sections"] for item in section["items"]))
        self.assertTrue(any("兜底" in item["风险兜底"] for section in readiness["sections"] for item in section["items"]))

    def test_builds_downloadable_readiness_markdown(self) -> None:
        route = build_demo_route("tech_enterprise_basic", resolve_template("tech_enterprise_basic", self.templates))
        readiness = build_demo_readiness_checklist(route)

        markdown = build_demo_readiness_markdown(readiness)

        self.assertIn("# 面客演示准备检查清单", markdown)
        self.assertIn("科创企业", markdown)
        self.assertIn("## 会前准备", markdown)
        self.assertIn("## 试点转化", markdown)
        self.assertIn("检查项", markdown)
        self.assertNotIn("TODO", markdown)


if __name__ == "__main__":
    unittest.main()
