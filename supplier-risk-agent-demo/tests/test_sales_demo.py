from __future__ import annotations

import unittest
import io
import json
import zipfile

from fastapi.testclient import TestClient

import backend.database as database
from backend.main import app
from backend.repository import clear_persistent_data
from tests.database_support import IsolatedTestDatabase


class SalesDemoApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.database = IsolatedTestDatabase()
        cls.database.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.database.stop()

    def setUp(self) -> None:
        with database.SessionLocal() as session:
            clear_persistent_data(session)
        self.client = TestClient(app)
        self.headers = {"Authorization": "Bearer dev-model-admin"}

    def test_overview_exposes_three_traceable_market_scenarios(self) -> None:
        response = self.client.get("/api/v1/sales-demo/overview", headers=self.headers)

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["schema_version"], "sales-demo-overview-v1")
        self.assertEqual(body["metrics"]["scenario_count"], 3)
        self.assertEqual(body["metrics"]["sample_count"], 9)
        self.assertEqual(body["metrics"]["indicator_count"], 201)
        self.assertEqual(body["metrics"]["traceable_rate"], 1.0)
        self.assertEqual(
            [item["key"] for item in body["scenarios"]],
            ["manufacturing_supplier", "channel_credit", "tech_enterprise"],
        )
        self.assertTrue(all(len(item["stories"]) == 3 for item in body["scenarios"]))
        self.assertTrue(all(item["evidence_hash"] for item in body["scenarios"]))

    def test_same_fixed_scenario_produces_identical_evidence(self) -> None:
        url = "/api/v1/sales-demo/scenarios/manufacturing_supplier?story=stable"

        first = self.client.get(url, headers=self.headers)
        second = self.client.get(url, headers=self.headers)

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(first.json()["evidence"], second.json()["evidence"])
        self.assertEqual(first.json()["result"], second.json()["result"])

    def test_restricted_technology_story_demonstrates_policy_tightening(self) -> None:
        response = self.client.get(
            "/api/v1/sales-demo/scenarios/tech_enterprise?story=restricted",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["story"]["key"], "restricted")
        self.assertEqual(body["result"]["rating"], "D")
        self.assertIn(body["result"]["access_strategy"], {"限制准入", "禁入", "拒绝"})

    def test_run_contains_complete_decision_path_and_hash_chain(self) -> None:
        response = self.client.get(
            "/api/v1/sales-demo/scenarios/channel_credit?story=growth",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["schema_version"], "sales-demo-run-v1")
        self.assertEqual(len(body["decision_path"]), 6)
        self.assertEqual(
            [node["key"] for node in body["decision_path"]],
            ["data", "indicator", "model", "rules", "strategy", "governance"],
        )
        self.assertTrue(all(node["proof"] for node in body["decision_path"]))
        for key in ("input_snapshot_hash", "model_config_hash", "result_hash", "evidence_hash"):
            self.assertEqual(len(body["evidence"][key]), 64)

    def test_unknown_scenario_or_story_returns_not_found(self) -> None:
        unknown_scenario = self.client.get(
            "/api/v1/sales-demo/scenarios/not-a-scenario",
            headers=self.headers,
        )
        unknown_story = self.client.get(
            "/api/v1/sales-demo/scenarios/channel_credit?story=not-a-story",
            headers=self.headers,
        )

        self.assertEqual(unknown_scenario.status_code, 404)
        self.assertEqual(unknown_story.status_code, 404)

    def test_demo_requires_model_view_permission(self) -> None:
        forbidden = self.client.get(
            "/api/v1/sales-demo/overview",
            headers={"Authorization": "Bearer dev-client"},
        )

        self.assertEqual(forbidden.status_code, 403)

    def test_executive_brief_is_downloadable_and_evidence_bound(self) -> None:
        response = self.client.get(
            "/api/v1/sales-demo/scenarios/tech_enterprise/brief?story=priority",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.headers["content-type"].startswith("text/markdown"))
        self.assertIn("attachment", response.headers["content-disposition"])
        self.assertIn("filename*=UTF-8''", response.headers["content-disposition"])
        self.assertEqual(len(response.headers["x-evidence-hash"]), 64)
        self.assertIn("# 科创企业评级｜管理层路演摘要", response.text)
        self.assertIn("## 可追溯决策路径", response.text)
        self.assertIn("正式授信政策", response.text)

    def test_value_dashboard_exposes_42_fixed_unlabeled_replay_cases(self) -> None:
        first = self.client.get("/api/v1/sales-demo/value-dashboard", headers=self.headers)
        second = self.client.get("/api/v1/sales-demo/value-dashboard", headers=self.headers)

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        body = first.json()
        self.assertEqual(body["schema_version"], "sales-demo-value-dashboard-v1")
        self.assertEqual(body["metrics"]["fixed_case_count"], 42)
        self.assertEqual(body["metrics"]["source_counterparty_count"], 14)
        self.assertEqual(body["metrics"]["model_count"], 3)
        self.assertEqual(body["metrics"]["execution_success_rate"], 1.0)
        self.assertEqual(len(body["cases"]), 42)
        self.assertEqual(len({item["case_id"] for item in body["cases"]}), 42)
        self.assertTrue(all(item["data_classification"] == "synthetic_demo" for item in body["cases"]))
        self.assertEqual(body["supervised_metrics"]["status"], "not_available")
        self.assertIsNone(body["supervised_metrics"]["risk_capture_rate"])
        self.assertIsNone(body["supervised_metrics"]["ks"])
        self.assertEqual(body["evidence"], second.json()["evidence"])

    def test_champion_challenger_is_fixed_and_degrades_without_labels(self) -> None:
        response = self.client.get(
            "/api/v1/sales-demo/showcases/champion-challenger",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["schema_version"], "sales-demo-champion-challenger-v1")
        self.assertEqual(body["metrics"]["sample_count"], 14)
        self.assertEqual(body["metrics"]["failure_count"], 0)
        self.assertEqual(body["champion"]["key"], "general")
        self.assertEqual(body["challenger"]["key"], "corporate_credit_v2")
        self.assertEqual(body["supervised_metrics"]["status"], "degraded_to_unsupervised")
        self.assertIsNone(body["supervised_metrics"]["champion_ks"])
        self.assertIsNone(body["supervised_metrics"]["champion_confusion_matrix"])
        self.assertEqual({item["segment"] for item in body["metrics"]["segments"]}, {"supplier", "customer"})
        for key in ("input_snapshot_hash", "champion_model_hash", "challenger_model_hash", "comparison_hash"):
            self.assertEqual(len(body["evidence"][key]), 64)

    def test_post_credit_showcase_is_read_only_and_evidence_bound(self) -> None:
        response = self.client.get(
            "/api/v1/sales-demo/showcases/post-credit-alert",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["schema_version"], "sales-demo-post-credit-alert-v1")
        self.assertEqual(body["record_status"], "read_only_demo")
        self.assertEqual(body["alert"]["severity"], "critical")
        self.assertEqual(body["alert"]["owner_role"], "贷后风控经理")
        self.assertEqual(body["alert"]["sla_hours"], 4)
        self.assertGreaterEqual(len(body["triggers"]), 3)
        self.assertEqual(len(body["evidence"]["alert_evidence_hash"]), 64)
        self.assertIn("不写入真实贷后台账", body["disclaimer"])

    def test_pilot_package_is_repeatable_and_contains_delivery_materials(self) -> None:
        first = self.client.get("/api/v1/sales-demo/pilot-package", headers=self.headers)
        second = self.client.get("/api/v1/sales-demo/pilot-package", headers=self.headers)

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(first.content, second.content)
        self.assertEqual(first.headers["x-package-hash"], second.headers["x-package-hash"])
        self.assertEqual(len(first.headers["x-evidence-hash"]), 64)
        self.assertTrue(first.headers["content-type"].startswith("application/zip"))
        with zipfile.ZipFile(io.BytesIO(first.content)) as archive:
            names = set(archive.namelist())
            self.assertTrue({
                "README.md", "15-minute-roadshow.md", "5-minute-demo.md", "faq.md",
                "data-field-template.csv", "api-quick-start.md", "pilot-scope-and-acceptance.md",
                "responsibility-matrix.md", "solution-cards.md", "evidence-manifest.json",
            }.issubset(names))
            manifest = json.loads(archive.read("evidence-manifest.json"))
        self.assertEqual(manifest["fixed_case_count"], 42)
        self.assertEqual(manifest["data_classification"], "synthetic_demo")
        self.assertEqual(manifest["manifest_hash"], first.headers["x-evidence-hash"])


if __name__ == "__main__":
    unittest.main()
