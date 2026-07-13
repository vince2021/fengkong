from __future__ import annotations

import json
import unittest
from pathlib import Path

from rating.industry_context import (
    preferred_industry_filter_label,
    preferred_industry_for_template,
    preferred_industry_label,
    sort_results_by_template_industry,
)


class IndustryContextTest(unittest.TestCase):
    def setUp(self) -> None:
        base = Path(__file__).resolve().parents[1]
        self.counterparties = json.loads((base / "data" / "counterparties.json").read_text(encoding="utf-8"))

    def test_maps_template_to_preferred_industry(self) -> None:
        self.assertEqual(preferred_industry_for_template("pharma"), "pharma")
        self.assertEqual(preferred_industry_for_template("tech_enterprise_basic"), "tech_enterprise")
        self.assertEqual(preferred_industry_for_template("unknown"), "general")
        self.assertEqual(preferred_industry_label("tech_enterprise_basic"), "科创企业")

    def test_sorts_rating_results_by_current_template_industry(self) -> None:
        results = [{"ok": True, "counterparty_id": item["id"]} for item in self.counterparties]

        manufacturing = sort_results_by_template_industry(results, self.counterparties, "manufacturing")
        logistics = sort_results_by_template_industry(results, self.counterparties, "logistics")
        tech = sort_results_by_template_industry(results, self.counterparties, "tech_enterprise_basic")

        self.assertEqual(manufacturing[0]["counterparty_id"], "cp_manufacturing_supplier_001")
        self.assertEqual(logistics[0]["counterparty_id"], "cp_logistics_reject_001")
        self.assertTrue(tech[0]["counterparty_id"].startswith("cp_tech_"))

    def test_prefers_industry_filter_label_when_available(self) -> None:
        self.assertEqual(preferred_industry_filter_label("pharma", ["通用", "医药流通"]), "医药流通")
        self.assertEqual(preferred_industry_filter_label("construction", ["通用", "制造业"]), "全部")


if __name__ == "__main__":
    unittest.main()
