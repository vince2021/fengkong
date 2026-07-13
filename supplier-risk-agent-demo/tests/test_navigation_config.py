from __future__ import annotations

import unittest

from rating.navigation_config import build_navigation_groups


class NavigationConfigTest(unittest.TestCase):
    def test_groups_pages_into_three_product_areas(self) -> None:
        groups = build_navigation_groups()

        self.assertEqual([group["name"] for group in groups], ["客户演示", "售前推进", "模型工作台"])
        self.assertEqual(
            [page["key"] for page in groups[0]["pages"]],
            ["demo_route", "product_samples", "industry_template", "demo_flow", "demo_script", "customer_qa"],
        )
        self.assertEqual([page["key"] for page in groups[1]["pages"]], ["sales_assets", "pilot_workspace", "delivery_package"])
        self.assertEqual([page["key"] for page in groups[2]["pages"]], ["dashboard", "counterparty_detail", "model_config", "rating_preview"])

    def test_each_group_has_business_positioning(self) -> None:
        groups = build_navigation_groups()

        for group in groups:
            self.assertIn("description", group)
            self.assertTrue(group["description"])
            self.assertTrue(all("label" in page and "key" in page for page in group["pages"]))


if __name__ == "__main__":
    unittest.main()
