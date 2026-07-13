from __future__ import annotations

import json
import unittest
from pathlib import Path

from rating.model_configurator import (
    build_indicator_library,
    build_model_overview,
    build_rule_matrix,
    build_strategy_matrix,
)


class ModelConfiguratorTest(unittest.TestCase):
    def setUp(self) -> None:
        base = Path(__file__).resolve().parents[1]
        self.templates = json.loads((base / "data" / "model_templates.json").read_text(encoding="utf-8"))["templates"]

    def test_builds_tech_model_governance_views(self) -> None:
        config = self.templates["tech_enterprise_basic"]

        overview = build_model_overview(config)
        indicators = build_indicator_library(config)
        rules = build_rule_matrix(config)
        strategies = build_strategy_matrix(config)

        self.assertEqual(overview["模型名称"], "科创企业基本评价模型")
        self.assertEqual(overview["评分卡类型"], "科创企业基本评价模型")
        self.assertGreaterEqual(overview["指标数量"], 20)
        self.assertTrue(any(item["指标名称"] == "高层次人才股东" for item in indicators))
        self.assertTrue(any(item["指标类型"] == "减分项" for item in indicators))
        self.assertTrue(any(item["规则编号"] == "SR-002" for item in rules))
        self.assertTrue(any(item["等级"] == "AA" and "5000" in item["额度策略"] for item in strategies))

    def test_builds_general_model_governance_views(self) -> None:
        config = self.templates["general"]

        overview = build_model_overview(config)
        indicators = build_indicator_library(config)
        rules = build_rule_matrix(config)
        strategies = build_strategy_matrix(config)

        self.assertEqual(overview["评分卡类型"], "通用加权评分模型")
        self.assertTrue(any(item["指标名称"] == "外部风险" for item in indicators))
        self.assertTrue(any(item["指标名称"] == "重大诉讼金额阈值" for item in indicators))
        self.assertEqual(len(rules), 4)
        self.assertTrue(any(item["等级"] == "AAA" for item in strategies))


if __name__ == "__main__":
    unittest.main()
