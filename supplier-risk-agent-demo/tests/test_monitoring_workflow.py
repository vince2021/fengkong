from __future__ import annotations

import unittest

from backend.monitoring_workflow import build_observed_monitoring_dataset, select_effective_monitoring_dataset


class MonitoringWorkflowTest(unittest.TestCase):
    def test_observed_dataset_reaches_formal_backtest_gate(self) -> None:
        outcomes = []
        for index in range(30):
            outcomes.append(
                {
                    "population_period": "2026Q1" if index < 15 else "2026Q2",
                    "predicted_score": 45 + index,
                    "predicted_pd": 0.45 if index < 8 else 0.08,
                    "observed_event": index < 8,
                }
            )

        dataset, readiness = build_observed_monitoring_dataset("general", outcomes)
        selected, source = select_effective_monitoring_dataset(dataset, readiness, {"dataset_id": "proxy"})

        self.assertTrue(readiness["formal_backtest_ready"])
        self.assertEqual(readiness["event_count"], 8)
        self.assertEqual(readiness["period_count"], 2)
        self.assertEqual(dataset["evidence_level"], "observed_outcome")
        self.assertEqual(selected["dataset_id"], dataset["dataset_id"])
        self.assertEqual(source, "observed_outcome")

    def test_incomplete_observations_do_not_replace_proxy_evidence(self) -> None:
        dataset, readiness = build_observed_monitoring_dataset(
            "general",
            [{"population_period": "2026Q2", "predicted_score": 80, "predicted_pd": 0.03, "observed_event": False}],
        )
        proxy = {"dataset_id": "proxy-general", "evidence_level": "simulation_proxy"}
        selected, source = select_effective_monitoring_dataset(dataset, readiness, proxy)

        self.assertFalse(readiness["formal_backtest_ready"])
        self.assertIn("观察记录还差 29 条", readiness["summary"])
        self.assertIs(selected, proxy)
        self.assertEqual(source, "simulation_proxy")


if __name__ == "__main__":
    unittest.main()
