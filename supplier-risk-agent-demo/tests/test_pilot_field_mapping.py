from __future__ import annotations

import json
import unittest
from pathlib import Path

from app_credit_rating import MODEL_TEMPLATES_PATH, resolve_template
from rating.pilot_field_mapping import build_pilot_field_mapping_markdown, build_pilot_field_mapping_package


class PilotFieldMappingTest(unittest.TestCase):
    def setUp(self) -> None:
        templates = json.loads(Path(MODEL_TEMPLATES_PATH).read_text(encoding="utf-8"))["templates"]
        self.model_config = resolve_template("pharma", templates)

    def test_builds_industry_aware_mapping_package(self) -> None:
        package = build_pilot_field_mapping_package("pharma", self.model_config)

        self.assertEqual(package["industry_label"], "医药流通")
        self.assertEqual(package["model_name"], "医药流通行业模板")
        self.assertEqual(package["model_version"], "MCR-20260711-001-PHARMA")
        self.assertIn("外部企业数据", package["sections"])
        self.assertIn("内部业务数据", package["sections"])
        self.assertIn("材料与知识库", package["sections"])
        self.assertIn("模型输出字段", package["sections"])
        self.assertIn("审计留痕字段", package["sections"])
        self.assertIn("缺口处理策略", package["sections"])
        self.assertIn("data_readiness_checklist", package)
        self.assertTrue(any("MCP" in row["数据来源"] for row in package["sections"]["外部企业数据"]))
        self.assertTrue(any("发票" in row["字段示例"] or "履约" in row["字段示例"] for row in package["sections"]["内部业务数据"]))
        self.assertTrue(all(row["缺失影响"] for rows in package["sections"].values() for row in rows))

    def test_builds_actionable_data_readiness_checklist(self) -> None:
        package = build_pilot_field_mapping_package("pharma", self.model_config)
        checklist = package["data_readiness_checklist"]

        self.assertGreaterEqual(len(checklist), 10)
        required_columns = {"字段名", "样例值", "是否必填", "客户负责人", "我方负责人", "缺失处理"}
        self.assertTrue(all(required_columns.issubset(row.keys()) for row in checklist))
        self.assertTrue(any(row["字段名"] == "统一社会信用代码" and row["是否必填"] == "是" for row in checklist))
        self.assertTrue(any(row["字段名"] == "发票匹配率" for row in checklist))
        self.assertTrue(any(row["字段名"] == "模型版本" and row["客户负责人"] == "无需客户准备" for row in checklist))

    def test_data_readiness_checklist_uses_current_template_context(self) -> None:
        templates = json.loads(Path(MODEL_TEMPLATES_PATH).read_text(encoding="utf-8"))["templates"]
        manufacturing_config = resolve_template("manufacturing", templates)
        package = build_pilot_field_mapping_package("manufacturing", manufacturing_config)
        checklist = package["data_readiness_checklist"]

        self.assertTrue(any(row["字段名"] == "模型版本" and row["样例值"] == "MCR-20260711-001-MANUFACTURING" for row in checklist))
        self.assertFalse(any("PHARMA" in row["样例值"] for row in checklist))
        self.assertTrue(any(row["字段名"] == "制造业资质证照" and row["样例值"] == "质量管理体系认证" for row in checklist))
        self.assertFalse(any(row["样例值"] == "药品经营许可证" for row in checklist))

    def test_markdown_is_customer_ready(self) -> None:
        package = build_pilot_field_mapping_package("pharma", self.model_config)
        markdown = build_pilot_field_mapping_markdown(package)

        self.assertIn("# 医药流通试点字段映射包", markdown)
        self.assertIn("## 外部企业数据", markdown)
        self.assertIn("## 缺口处理策略", markdown)
        self.assertIn("## 试点数据准备清单", markdown)
        self.assertIn("客户负责人", markdown)
        self.assertIn("模型版本", markdown)
        self.assertNotIn("TODO", markdown)


if __name__ == "__main__":
    unittest.main()
