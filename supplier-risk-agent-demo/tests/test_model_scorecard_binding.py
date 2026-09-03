from __future__ import annotations

import unittest
from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm.attributes import flag_modified

import backend.database as database
from backend.db_models import ModelChangeRecord, ScorecardDevelopmentRun
from backend.main import app
from backend.repository import DemoRepository, ModelGovernanceRepository, RuleCenterReplayDatasetRepository, clear_persistent_data, content_hash
from backend.scorecard_repository import ScorecardRepository
from tests.database_support import IsolatedTestDatabase
from tests.test_scorecard_center import scorecard


class TestModelScorecardBindingApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = IsolatedTestDatabase()
        cls.db.start()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.db.stop()

    def setUp(self):
        with database.SessionLocal() as session:
            clear_persistent_data(session)
            repository = ScorecardRepository(session)
            draft = repository.create_draft(scorecard("MODEL_BIND_SCORE"), "建立模型绑定评分卡", "maker", "模型管理员")
            submitted = repository.submit(draft["id"], draft["row_version"], "maker", False)
            repository.review(submitted["id"], submitted["row_version"], "publish", "模型绑定复核通过", "reviewer", "风控经理")
            self.asset = repository.list_assets()[0]
        self.headers = {"Authorization": "Bearer dev-model-admin"}

    def _payload(self) -> dict:
        model = self.client.get("/api/v1/models/general", headers=self.headers).json()
        return {
            "template_key": "general", "candidate_version": f"{model['version']}-SCORECARD",
            "change_reason": "绑定已发布评分卡并验证不可变执行快照",
            "weights": model["weights"], "thresholds": model["thresholds"],
            "strong_rules": model["strong_rules"], "strategy_mapping": model["strategy_mapping"],
            "indicator_selection": [{"indicator_id": item["id"], "weight": item["model_weight"], "enabled": item["enabled"]} for item in model["indicator_selection"]],
            "risk_screening_policy": model["risk_screening_policy"], "scorecard_id": self.asset["id"],
        }

    def _approved_validation(self) -> dict:
        with database.SessionLocal() as session:
            datasets = RuleCenterReplayDatasetRepository(session)
            snapshots = []
            for split in ("TRAIN", "VALID", "OOT"):
                dataset = datasets.create_dataset(f"MODEL-{split}-{uuid4().hex[:8]}", f"模型{split}样本", "评分卡模型绑定验证", "validator", "模型验证员")
                records = []
                for index in range(8):
                    event = index >= 4
                    records.append({
                        "id": f"{split.lower()}-{index}",
                        "name": f"{split}样本{index}",
                        "counterparty_type": "supplier",
                        "enterprise_risk": {"shareholder_change": 2 if event else 0},
                        "observed_at": f"2026-01-{index + 1:02d}",
                        "outcome": "bad" if event else "good",
                        "predicted_pd": 0.8 if event else 0.2,
                    })
                snapshots.append(datasets.import_snapshot(dataset["id"], {
                    "source_name": f"{split}固定样本", "schema_version": "1.0", "as_of_date": date(2026, 6, 30),
                    "evidence_reference": f"test://model-scorecard/{split.lower()}", "data_classification": "synthetic",
                    "field_mapping": {}, "label_field": "outcome", "observed_at_field": "observed_at", "records": records,
                }, "validator", "模型验证员"))
            scorecards = ScorecardRepository(session)
            run = scorecards.create_development_run({
                "scorecard_asset_id": self.asset["id"], "dataset_snapshot_id": snapshots[0]["id"],
                "validation_snapshot_id": snapshots[1]["id"], "oot_snapshot_id": snapshots[2]["id"],
                "subject_id_field": "id", "predicted_probability_field": "predicted_pd",
                "positive_labels": ["bad"], "observation_start": date(2026, 1, 1), "observation_end": date(2026, 3, 31),
                "performance_window_days": 90, "maturity_days": 30, "min_sample_count": 8,
                "min_event_count": 4, "min_non_event_count": 4, "exclusion_rules": [],
            }, "validator", "模型验证员")
            return scorecards.review_development_run(run["id"], run["row_version"], "approve", "独立复核确认评分卡验证门禁通过", "risk", "风控经理")

    def test_candidate_resolves_published_asset_to_immutable_binding(self):
        response = self.client.post("/api/v1/model-governance/changes", json=self._payload(), headers=self.headers)
        self.assertEqual(response.status_code, 201, response.text)
        change = response.json()
        binding = change["config"]["scorecard_binding"]
        self.assertEqual(binding["scorecard_asset_id"], self.asset["id"])
        self.assertEqual(binding["code"], self.asset["code"])
        self.assertEqual(binding["version"], self.asset["version"])
        self.assertEqual(binding["config_hash"], self.asset["config_hash"])
        self.assertEqual(content_hash(binding["config"]), binding["config_hash"])
        self.assertTrue(change["impact"]["scorecard_binding_changed"])

    def test_unknown_scorecard_asset_is_rejected(self):
        payload = self._payload()
        payload["scorecard_id"] = "missing-scorecard"
        response = self.client.post("/api/v1/model-governance/changes", json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 404)

    def test_candidate_binds_matching_approved_pass_validation(self):
        validation = self._approved_validation()
        payload = self._payload()
        payload["scorecard_validation_run_id"] = validation["id"]
        response = self.client.post("/api/v1/model-governance/changes", json=payload, headers=self.headers)

        self.assertEqual(response.status_code, 201, response.text)
        evidence = response.json()["scorecard_validation_evidence"]
        self.assertTrue(evidence["current_valid"])
        self.assertEqual(evidence["validation_run_id"], validation["id"])
        self.assertEqual(evidence["scorecard_asset_id"], self.asset["id"])
        self.assertEqual(evidence["evidence_hash"], validation["evidence_hash"])
        self.assertEqual(evidence["review_hash"], validation["review_hash"])
        self.assertTrue(evidence["binding_hash"])

    def test_scorecard_candidate_without_validation_cannot_submit(self):
        created = self.client.post("/api/v1/model-governance/changes", json=self._payload(), headers=self.headers).json()
        response = self.client.post(
            f"/api/v1/model-governance/changes/{created['id']}/submit",
            json={"expected_row_version": created["row_version"]}, headers=self.headers,
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("缺少已批准的评分卡开发验证证据", response.text)

    def test_pending_validation_run_cannot_be_bound(self):
        validation = self._approved_validation()
        with database.SessionLocal() as session:
            run = session.get(ScorecardDevelopmentRun, validation["id"])
            run.review_status = "pending_review"
            run.review_hash = None
            session.commit()
        payload = self._payload()
        payload["candidate_version"] += "-PENDING"
        payload["scorecard_validation_run_id"] = validation["id"]
        response = self.client.post("/api/v1/model-governance/changes", json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("尚未完成有效的独立批准", response.text)

    def test_tampered_validation_binding_is_reported_and_blocks_submit(self):
        validation = self._approved_validation()
        payload = self._payload()
        payload["scorecard_validation_run_id"] = validation["id"]
        created = self.client.post("/api/v1/model-governance/changes", json=payload, headers=self.headers).json()
        with database.SessionLocal() as session:
            record = session.get(ModelChangeRecord, created["id"])
            record.scorecard_validation_evidence_json["evidence_hash"] = "0" * 64
            flag_modified(record, "scorecard_validation_evidence_json")
            session.commit()

        listed = self.client.get("/api/v1/model-governance/changes?template_key=general", headers=self.headers).json()
        current = next(item for item in listed if item["id"] == created["id"])
        self.assertFalse(current["scorecard_validation_evidence"]["current_valid"])
        self.assertIn("绑定哈希不一致", current["scorecard_validation_evidence"]["current_error"])
        blocked = self.client.post(f"/api/v1/model-governance/changes/{created['id']}/submit", json={"expected_row_version": current["row_version"]}, headers=self.headers)
        self.assertEqual(blocked.status_code, 422, blocked.text)
        self.assertIn("绑定哈希不一致", blocked.text)

    def test_final_publish_revalidates_underlying_scorecard_evidence(self):
        validation = self._approved_validation()
        payload = self._payload()
        payload["scorecard_validation_run_id"] = validation["id"]
        created = self.client.post("/api/v1/model-governance/changes", json=payload, headers=self.headers).json()
        with database.SessionLocal() as session:
            change = session.get(ModelChangeRecord, created["id"])
            change.status = "pending_review"
            run = session.get(ScorecardDevelopmentRun, validation["id"])
            run.report_json["summary"]["eligible_sample_count"] = 999
            flag_modified(run, "report_json")
            session.commit()
            session.refresh(change)
            with self.assertRaisesRegex(ValueError, "证据完整性校验失败"):
                ModelGovernanceRepository(session).review_change(
                    change.id, change.row_version, "publish", "最终审核尝试发布篡改证据",
                    "final-reviewer", "最终审核人", DemoRepository(),
                )

    def test_bound_version_does_not_drift_when_new_scorecard_version_is_published(self):
        with database.SessionLocal() as session:
            repository = ScorecardRepository(session)
            frozen = repository.binding_for_asset(self.asset["id"])
            definition_v2 = scorecard("MODEL_BIND_SCORE")
            definition_v2["indicators"][0]["bins"][0]["score"] = 95
            draft = repository.create_draft(definition_v2, "发布评分卡第二版", "maker", "模型管理员")
            submitted = repository.submit(draft["id"], draft["row_version"], "maker", False)
            repository.review(submitted["id"], submitted["row_version"], "publish", "第二版独立复核通过", "reviewer", "风控经理")
            reloaded = repository.binding_for_asset(self.asset["id"])
            active = next(asset for asset in repository.list_assets() if asset["is_active"])

        self.assertEqual(reloaded, frozen)
        self.assertEqual(reloaded["version"], 1)
        self.assertEqual(active["version"], 2)
        self.assertNotEqual(active["config_hash"], frozen["config_hash"])

    def test_changing_scorecard_binding_clears_stale_comparison_evidence(self):
        created = self.client.post("/api/v1/model-governance/changes", json=self._payload(), headers=self.headers).json()
        with database.SessionLocal() as session:
            record = session.get(ModelChangeRecord, created["id"])
            record.comparison_evidence_json = {"comparison_run_id": "stale-comparison"}
            session.commit()
            session.refresh(record)
            expected_row_version = record.row_version

        payload = self._payload()
        payload.pop("template_key")
        payload.pop("candidate_version")
        payload["expected_row_version"] = expected_row_version
        payload["scorecard_id"] = None
        response = self.client.put(f"/api/v1/model-governance/changes/{created['id']}", json=payload, headers=self.headers)

        self.assertEqual(response.status_code, 200, response.text)
        updated = response.json()
        self.assertIsNone(updated["config"]["scorecard_binding"])
        self.assertFalse(updated["impact"]["scorecard_binding_changed"])
        self.assertEqual(updated["comparison_evidence"], {})


if __name__ == "__main__":
    unittest.main()
