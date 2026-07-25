from __future__ import annotations

import unittest

from backend.model_monitoring import build_monitoring_metrics
from backend.repository import DemoRepository


class ModelMonitoringTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = DemoRepository()

    def test_computes_drift_discrimination_and_calibration_metrics(self) -> None:
        result = build_monitoring_metrics(self.repository.get_model_monitoring_dataset("general"))
        metrics = {item["key"]: item for item in result["performance_metrics"]}

        self.assertEqual(result["dataset"]["evidence_level"], "simulation_proxy")
        self.assertAlmostEqual(result["population_stability"]["value"], 0.0188)
        self.assertEqual(result["population_stability"]["status"], "pass")
        self.assertAlmostEqual(metrics["auc"]["value"], 0.8923)
        self.assertAlmostEqual(metrics["ks"]["value"], 0.6212)
        self.assertAlmostEqual(metrics["brier"]["value"], 0.1709)
        self.assertEqual(metrics["calibration_gap"]["status"], "fail")
        self.assertEqual(result["backtesting"]["sample_count"], 51)

    def test_marks_monitoring_not_testable_without_cross_period_dataset(self) -> None:
        result = build_monitoring_metrics(None)

        self.assertIsNone(result["dataset"])
        self.assertEqual(result["population_stability"]["status"], "not_testable")
        self.assertEqual(result["backtesting"]["status"], "blocked")
        self.assertEqual(result["performance_metrics"], [])


if __name__ == "__main__":
    unittest.main()
