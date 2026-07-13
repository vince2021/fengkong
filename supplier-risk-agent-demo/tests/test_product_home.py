from __future__ import annotations

import unittest

from rating.navigation_config import build_navigation_groups
from rating.product_home import build_product_home


class ProductHomeTest(unittest.TestCase):
    def test_builds_home_overview_from_navigation_groups(self) -> None:
        home = build_product_home(build_navigation_groups())

        self.assertEqual(home["title"], "客商信用评级与风险分层 Agent")
        self.assertIn("大型企业", home["subtitle"])
        self.assertEqual([area["name"] for area in home["areas"]], ["客户演示", "售前推进", "模型工作台"])
        self.assertTrue(any(step["target_area"] == "客户演示" for step in home["recommended_path"]))
        self.assertTrue(any(item["name"] == "完整交付包" for item in home["deliverables"]))

    def test_each_area_explains_when_to_use_it(self) -> None:
        home = build_product_home(build_navigation_groups())

        for area in home["areas"]:
            self.assertIn("when_to_use", area)
            self.assertTrue(area["when_to_use"])
            self.assertIn("pages", area)
            self.assertTrue(area["pages"])


if __name__ == "__main__":
    unittest.main()
