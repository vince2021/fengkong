from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

import backend.database as database
from backend.database import Base
from backend.db_models import (
    AuditEventRecord,
    RuleCenterReplayComparisonRun,
    RuleCenterReplayDataset,
    RuleCenterReplayDatasetSnapshot,
)
from backend.main import app
from backend.repository import RuleCenterReplayComparisonRepository, RuleCenterReplayDatasetRepository
from tests.database_support import IsolatedTestDatabase


class _Models:
    def get_config(self, _demo, key):
        if key not in {"champion", "challenger"}:
            return None
        return {"version": "1.0" if key == "champion" else "2.0", "decision_pipeline_code": ""}


def _rate(sample, config):
    side = "champion" if config["version"] == "1.0" else "challenger"
    return {
        "ok": True,
        "total_score": sample[f"{side}_score"],
        "rating": sample[f"{side}_rating"],
        "access_strategy": sample[f"{side}_admission"],
    }


class TestRuleCenterReplayComparisons(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = IsolatedTestDatabase()
        cls.db.start()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.db.stop()

    def setUp(self):
        Base.metadata.create_all(self.db.engine)
        self._clear()

    def tearDown(self):
        self._clear()

    def _clear(self):
        with database.SessionLocal() as session:
            session.query(RuleCenterReplayComparisonRun).delete()
            session.query(RuleCenterReplayDatasetSnapshot).delete()
            session.query(RuleCenterReplayDataset).delete()
            session.query(AuditEventRecord).delete()
            session.commit()

    def _snapshot(self, labels=("good", "bad", "good", "bad")):
        with database.SessionLocal() as session:
            dataset = RuleCenterReplayDataset(
                id=str(uuid4()), code=f"CMP-{uuid4().hex[:8]}", name="比较样本",
                description="Champion Challenger 验证", status="active",
                created_by="maker", created_by_name="制作者",
            )
            rows = []
            values = [
                (80, 85, "A", "A", "approve", "approve", "supplier"),
                (30, 20, "C", "D", "reject", "reject", "supplier"),
                (70, 55, "A", "BBB", "approve", "manual_review", "customer"),
                (40, 25, "BB", "C", "manual_review", "reject", "customer"),
            ]
            for index, value in enumerate(values):
                c_score, n_score, c_rating, n_rating, c_admission, n_admission, segment = value
                rows.append({
                    "sample": {
                        "id": f"S-{index}", "name": f"企业{index}", "counterparty_type": segment,
                        "champion_score": c_score, "challenger_score": n_score,
                        "champion_rating": c_rating, "challenger_rating": n_rating,
                        "champion_admission": c_admission, "challenger_admission": n_admission,
                    },
                    "label": labels[index] if labels else None, "observed_at": "2026-06-01",
                })
            snapshot = RuleCenterReplayDatasetSnapshot(
                id=str(uuid4()), dataset_id=dataset.id, version=1, source_name="test",
                schema_version="1", as_of_date=date(2026, 6, 30), evidence_reference="test://comparison",
                data_classification="synthetic", field_mapping_json={}, label_field="label" if labels else None,
                observed_at_field="observed_at", sample_count=len(rows), samples_json=rows,
                coverage_json={}, source_hash="a" * 64, content_hash="pending",
                created_by="maker", created_by_name="制作者",
            )
            session.add_all([dataset, snapshot])
            session.flush()
            snapshot.content_hash = RuleCenterReplayDatasetRepository.snapshot_content_hash(snapshot)
            snapshot_id = snapshot.id
            session.commit()
        return snapshot_id

    @staticmethod
    def _payload(snapshot_id):
        return {
            "dataset_snapshot_id": snapshot_id, "champion_model_key": "champion",
            "challenger_model_key": "challenger", "champion_pipeline_code": None,
            "challenger_pipeline_code": None, "segment_field": "counterparty_type",
            "positive_labels": ["bad"], "positive_admissions": ["reject"],
            "sample_limit": 500, "max_execution_failure_rate": 0,
        }

    @patch("rating.scorecard.rate_counterparty", side_effect=_rate)
    def test_labeled_run_calculates_ks_confusion_psi_and_segments(self, _mock):
        snapshot_id = self._snapshot()
        with database.SessionLocal() as session:
            result = RuleCenterReplayComparisonRepository(session).run(
                self._payload(snapshot_id), object(), _Models(), "maker", "制作者"
            )
        self.assertEqual(result["evidence_level"], "labeled")
        self.assertEqual(result["champion_model_version"], "1.0")
        self.assertEqual(result["challenger_model_version"], "2.0")
        self.assertIsInstance(result["metrics"]["psi"], float)
        self.assertEqual(len(result["metrics"]["segments"]), 2)
        self.assertEqual(result["metrics"]["champion"]["ks"], 1)
        self.assertEqual(result["metrics"]["challenger"]["confusion_matrix"], {"tp": 2, "fp": 0, "tn": 2, "fn": 0})
        self.assertEqual(len(result["evidence_hash"]), 64)

    @patch("rating.scorecard.rate_counterparty", side_effect=_rate)
    def test_unlabeled_run_explicitly_downgrades_supervised_evidence(self, _mock):
        snapshot_id = self._snapshot(labels=())
        with database.SessionLocal() as session:
            result = RuleCenterReplayComparisonRepository(session).run(
                self._payload(snapshot_id), object(), _Models(), "maker", "制作者"
            )
        self.assertEqual(result["evidence_level"], "unlabeled")
        self.assertIsNone(result["metrics"]["champion"]["ks"])
        self.assertIsNone(result["metrics"]["challenger"]["confusion_matrix"])
        self.assertIn("非监督稳定性证据", result["metrics"]["warning"])

    @patch("rating.scorecard.rate_counterparty", side_effect=_rate)
    def test_tampered_snapshot_is_rejected(self, _mock):
        snapshot_id = self._snapshot()
        with database.SessionLocal() as session:
            snapshot = session.get(RuleCenterReplayDatasetSnapshot, snapshot_id)
            snapshot.samples_json[0]["sample"]["champion_score"] = 99
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(snapshot, "samples_json")
            session.commit()
            with self.assertRaisesRegex(ValueError, "哈希不一致"):
                RuleCenterReplayComparisonRepository(session).run(
                    self._payload(snapshot_id), object(), _Models(), "maker", "制作者"
                )

    def test_permissions_fail_closed(self):
        viewer = {"Authorization": "Bearer dev-auditor"}
        listed = self.client.get("/api/v1/rule-center/governance/replay-comparisons", headers=viewer)
        self.assertEqual(listed.status_code, 200, listed.text)
        forbidden = self.client.post(
            "/api/v1/rule-center/governance/replay-comparisons",
            json=self._payload(str(uuid4())), headers=viewer,
        )
        self.assertEqual(forbidden.status_code, 403, forbidden.text)


if __name__ == "__main__":
    unittest.main()
