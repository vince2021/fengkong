from __future__ import annotations

import unittest

from rating.portfolio_rating import build_portfolio_summary


class PortfolioRatingSummaryTest(unittest.TestCase):
    def test_summary_builds_distribution_watchlist_and_exposure(self) -> None:
        results = [
            {
                "counterparty_id": "cp-low", "counterparty_name": "低风险企业", "counterparty_type": "customer",
                "total_score": 92, "rating": "AA", "risk_segment": "核心客商", "access_strategy": "自动准入",
                "suggested_limit": 1_000_000, "review_required": False, "strong_rule_hit_count": 0,
                "risk_policy_changed": False, "risk_screening_score": 90, "risk_screening_completeness": 1,
            },
            {
                "counterparty_id": "cp-high", "counterparty_name": "高风险企业", "counterparty_type": "supplier",
                "total_score": 45, "rating": "D", "risk_segment": "禁入客商", "access_strategy": "禁入",
                "suggested_limit": 0, "review_required": True, "strong_rule_hit_count": 1,
                "risk_policy_changed": True, "risk_screening_score": 25, "risk_screening_completeness": .5,
            },
        ]

        summary = build_portfolio_summary(results, [{"counterparty_id": "cp-skip"}], 3)

        self.assertEqual(summary["candidate_count"], 3)
        self.assertEqual(summary["success_count"], 2)
        self.assertEqual(summary["skipped_count"], 1)
        self.assertEqual(summary["review_required_count"], 1)
        self.assertEqual(summary["denied_count"], 1)
        self.assertEqual(summary["policy_affected_count"], 1)
        self.assertEqual(summary["total_suggested_limit"], 1_000_000)
        self.assertEqual(summary["rating_distribution"], {"AA": 1, "D": 1})
        self.assertEqual(summary["watchlist"][0]["counterparty_id"], "cp-high")


if __name__ == "__main__":
    unittest.main()
