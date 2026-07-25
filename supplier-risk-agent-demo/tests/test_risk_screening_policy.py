from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from rating.enterprise_indicator_pool import list_enterprise_risk_indicators
from rating.risk_screening_policy import validate_risk_screening_policy
from rating.scorecard import rate_counterparty
from rating.template_resolver import resolve_template


class RiskScreeningPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        base = Path(__file__).resolve().parents[1]
        templates = json.loads((base / "data" / "model_templates.json").read_text(encoding="utf-8"))["templates"]
        self.config = resolve_template("general", templates)
        self.counterparty = json.loads((base / "data" / "counterparties.json").read_text(encoding="utf-8"))[0]
        indicator = next(item for item in list_enterprise_risk_indicators() if item["name"] == "股东变更")
        self.config["indicator_selection"] = [{"indicator_id": indicator["id"], "weight": 1, "enabled": True}]
        self.config["risk_screening_policy"] = {
            "enabled": True,
            "aggregation": "most_restrictive",
            "rules": [
                {
                    "id": "TEST-CRITICAL",
                    "name": "关键指标低分",
                    "enabled": True,
                    "metric": "critical_indicator_count",
                    "operator": ">=",
                    "value": 1,
                    "action": {
                        "rating_notch_down": 1,
                        "limit_cap_ratio": 0.5,
                        "term_cap_days": 30,
                        "access_strategy": "限制准入",
                        "monitoring_frequency": "月度",
                    },
                }
            ],
        }

    def test_local_risk_indicator_tightens_final_credit_conclusion(self) -> None:
        low_risk = deepcopy(self.counterparty)
        low_risk["external"]["shareholder_change_count_1y"] = 0
        high_risk = deepcopy(low_risk)
        high_risk["external"]["shareholder_change_count_1y"] = 3

        before = rate_counterparty(low_risk, self.config)
        after = rate_counterparty(high_risk, self.config)

        self.assertEqual(before["risk_screening_policy"]["hits"], [])
        self.assertEqual([item["id"] for item in after["risk_screening_policy"]["hits"]], ["TEST-CRITICAL"])
        self.assertNotEqual(after["rating"], before["rating"])
        self.assertLess(after["suggested_limit"], before["suggested_limit"])
        self.assertLessEqual(after["suggested_payment_term_days"], 30)
        self.assertEqual(after["access_strategy"], "限制准入")
        self.assertTrue(after["risk_screening_policy"]["changed"])

    def test_disabled_policy_preserves_base_strategy(self) -> None:
        counterparty = deepcopy(self.counterparty)
        counterparty["external"]["shareholder_change_count_1y"] = 3
        self.config["risk_screening_policy"]["enabled"] = False

        result = rate_counterparty(counterparty, self.config)

        self.assertEqual(result["risk_screening_policy"]["hits"], [])
        self.assertFalse(result["risk_screening_policy"]["changed"])
        self.assertEqual(result["rating"], result["raw_rating"])

    def test_policy_never_loosens_strong_rule_deny(self) -> None:
        counterparty = deepcopy(self.counterparty)
        counterparty["external"]["dishonesty_count"] = 1
        counterparty["external"]["shareholder_change_count_1y"] = 3

        result = rate_counterparty(counterparty, self.config)

        self.assertEqual(result["rating"], "D")
        self.assertEqual(result["access_strategy"], "禁入")
        self.assertEqual(result["suggested_limit"], 0)
        self.assertEqual(result["suggested_payment_term_days"], 0)

    def test_validation_rejects_invalid_tightening_action(self) -> None:
        invalid = deepcopy(self.config["risk_screening_policy"])
        invalid["rules"][0]["action"]["limit_cap_ratio"] = 1.2
        invalid["rules"][0]["action"]["rating_notch_down"] = -1

        errors, _ = validate_risk_screening_policy(invalid)

        self.assertTrue(any("额度上限比例" in item for item in errors))
        self.assertTrue(any("评级下调档数" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
