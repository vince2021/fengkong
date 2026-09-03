from __future__ import annotations

import unittest
from copy import deepcopy
from datetime import date, timedelta
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy.orm.attributes import flag_modified

import backend.database as database
from backend.database import Base
from backend.db_models import (
    AuditEventRecord,
    ModelChangeRecord,
    ModelReleaseRecord,
    RuleCenterReplayComparisonException,
    RuleCenterReplayComparisonRun,
    RuleCenterReplayDataset,
    RuleCenterReplayDatasetSnapshot,
)
from backend.repository import (
    ModelGovernanceRepository,
    RuleCenterReplayComparisonRepository,
    RuleCenterReplayDatasetRepository,
    content_hash,
)
from tests.database_support import IsolatedTestDatabase


class _Demo:
    def get_template(self, key):
        if key != "governed_model":
            return None
        return {"version": "1.0", "marker": "champion", "decision_pipeline_code": ""}


def _rate(sample, config):
    marker = config["marker"]
    return {
        "ok": True,
        "total_score": sample[f"{marker}_score"],
        "rating": sample[f"{marker}_rating"],
        "access_strategy": sample[f"{marker}_admission"],
    }


class TestModelChangeComparisonEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = IsolatedTestDatabase()
        cls.db.start()

    @classmethod
    def tearDownClass(cls):
        cls.db.stop()

    def setUp(self):
        Base.metadata.create_all(self.db.engine)
        with database.SessionLocal() as session:
            session.query(RuleCenterReplayComparisonException).delete()
            session.query(RuleCenterReplayComparisonRun).delete()
            session.query(RuleCenterReplayDatasetSnapshot).delete()
            session.query(RuleCenterReplayDataset).delete()
            session.query(ModelReleaseRecord).delete()
            session.query(ModelChangeRecord).delete()
            session.query(AuditEventRecord).delete()
            session.commit()

    def _snapshot(self):
        with database.SessionLocal() as session:
            dataset = RuleCenterReplayDataset(
                id=str(uuid4()), code=f"GOV-{uuid4().hex[:8]}", name="模型治理比较样本",
                description="验证候选配置与发布证据绑定", status="active",
                created_by="maker", created_by_name="制作者",
            )
            rows = [
                {"sample": {"id": "A", "counterparty_type": "supplier", "champion_score": 80, "challenger_score": 60, "champion_rating": "A", "challenger_rating": "BB", "champion_admission": "approve", "challenger_admission": "manual_review"}, "label": "good"},
                {"sample": {"id": "B", "counterparty_type": "customer", "champion_score": 30, "challenger_score": 15, "champion_rating": "C", "challenger_rating": "D", "champion_admission": "reject", "challenger_admission": "reject"}, "label": "bad"},
            ]
            snapshot = RuleCenterReplayDatasetSnapshot(
                id=str(uuid4()), dataset_id=dataset.id, version=1, source_name="test",
                schema_version="1", as_of_date=date(2026, 6, 30), evidence_reference="test://governance",
                data_classification="synthetic", field_mapping_json={}, label_field="label",
                observed_at_field=None, sample_count=len(rows), samples_json=rows,
                coverage_json={}, source_hash="a" * 64, content_hash="pending",
                created_by="maker", created_by_name="制作者",
            )
            session.add_all([dataset, snapshot])
            session.flush()
            snapshot.content_hash = RuleCenterReplayDatasetRepository.snapshot_content_hash(snapshot)
            snapshot_id = snapshot.id
            session.commit()
        return snapshot_id

    def _change(self):
        config = {"version": "2.0", "marker": "challenger", "decision_pipeline_code": ""}
        with database.SessionLocal() as session:
            record = ModelChangeRecord(
                id=str(uuid4()), template_key="governed_model", base_version="1.0",
                candidate_version="2.0", status="draft", config_json=config,
                validation_json={"valid": True, "config_hash": content_hash(config), "model_risk": {"release_gate": {"passed": True, "summary": "通过"}}},
                impact_json={}, comparison_evidence_json={}, change_reason="验证候选比较发布证据",
                created_by="maker", created_by_name="制作者", entity_type="model",
            )
            session.add(record)
            session.commit()
            return record.id

    @staticmethod
    def _payload(snapshot_id, *, permissive=True):
        return {
            "expected_row_version": 1, "dataset_snapshot_id": snapshot_id,
            "champion_pipeline_code": None, "challenger_pipeline_code": None,
            "segment_field": "counterparty_type", "positive_labels": ["bad"],
            "positive_admissions": ["reject"], "sample_limit": 500,
            "max_execution_failure_rate": 0, "max_psi": 100 if permissive else 0,
            "max_rating_change_rate": 1 if permissive else 0,
            "max_admission_change_rate": 1 if permissive else 0,
            "max_absolute_average_score_delta": 100 if permissive else 0,
            "max_segment_absolute_score_delta": 100 if permissive else 0,
            "max_ks_drop": 1 if permissive else 0,
            "require_labeled_evidence": False, "evidence_valid_days": 30,
        }

    @patch("rating.scorecard.rate_counterparty", side_effect=_rate)
    def test_candidate_draft_is_executed_and_edit_clears_binding(self, mocked_rate):
        snapshot_id, change_id = self._snapshot(), self._change()
        with database.SessionLocal() as session:
            repository = ModelGovernanceRepository(session)
            bound = repository.run_and_bind_comparison_evidence(
                change_id, 1, self._payload(snapshot_id), _Demo(), "maker", "制作者"
            )
            self.assertTrue(bound["comparison_evidence"]["gate"]["passed"])
            self.assertEqual(bound["comparison_evidence"]["challenger_model_version"], "2.0")
            self.assertTrue(any(call.args[1].get("marker") == "challenger" for call in mocked_rate.call_args_list))
            updated_config = {"version": "2.0", "marker": "challenger-updated", "decision_pipeline_code": ""}
            updated = repository.update_change(
                change_id, bound["row_version"],
                {"config": updated_config, "validation": {"valid": True, "config_hash": content_hash(updated_config), "model_risk": {"release_gate": {"passed": True, "summary": "通过"}}}, "impact": {}, "change_reason": "修改候选后旧比较证据必须失效"},
                "maker", "制作者",
            )
            self.assertEqual(updated["comparison_evidence"], {})
            with self.assertRaisesRegex(ValueError, "缺少 Champion/Challenger 比较证据"):
                repository.submit_change(change_id, updated["row_version"], "maker", "制作者")

    @patch("rating.scorecard.rate_counterparty", side_effect=_rate)
    def test_expired_binding_is_rejected_on_submit(self, _mock):
        snapshot_id, change_id = self._snapshot(), self._change()
        with database.SessionLocal() as session:
            repository = ModelGovernanceRepository(session)
            bound = repository.run_and_bind_comparison_evidence(change_id, 1, self._payload(snapshot_id), _Demo(), "maker", "制作者")
            record = session.get(ModelChangeRecord, change_id)
            binding = deepcopy(record.comparison_evidence_json)
            binding.pop("binding_hash")
            binding["valid_until"] = (date.today() - timedelta(days=1)).isoformat()
            binding["binding_hash"] = content_hash(binding)
            record.comparison_evidence_json = binding
            session.commit()
            session.refresh(record)
            with self.assertRaisesRegex(ValueError, "已过期"):
                repository.submit_change(change_id, record.row_version, "maker", "制作者")

    @patch("rating.scorecard.rate_counterparty", side_effect=_rate)
    def test_tampered_run_is_rejected_again_at_final_publish(self, _mock):
        snapshot_id, change_id = self._snapshot(), self._change()
        with database.SessionLocal() as session:
            repository = ModelGovernanceRepository(session)
            bound = repository.run_and_bind_comparison_evidence(change_id, 1, self._payload(snapshot_id), _Demo(), "maker", "制作者")
            submitted = repository.submit_change(change_id, bound["row_version"], "maker", "制作者")
            record = session.get(ModelChangeRecord, change_id)
            run = session.get(RuleCenterReplayComparisonRun, record.comparison_evidence_json["comparison_run_id"])
            run.details_json[0]["challenger"]["score"] = 99
            flag_modified(run, "details_json")
            session.commit()
            with self.assertRaisesRegex(ValueError, "证据哈希不一致"):
                repository.review_change(change_id, submitted["row_version"], "publish", "独立复核同意发布", "risk", "风控经理", _Demo())

    @patch("rating.scorecard.rate_counterparty", side_effect=_rate)
    def test_approved_exception_changes_disposition_not_original_gate(self, _mock):
        snapshot_id, change_id = self._snapshot(), self._change()
        with database.SessionLocal() as session:
            governance = ModelGovernanceRepository(session)
            bound = governance.run_and_bind_comparison_evidence(change_id, 1, self._payload(snapshot_id, permissive=False), _Demo(), "maker", "制作者")
            self.assertFalse(bound["comparison_evidence"]["gate"]["passed"])
            comparison_id = bound["comparison_evidence"]["comparison_run_id"]
            comparisons = RuleCenterReplayComparisonRepository(session)
            exception = comparisons.request_exception(comparison_id, {
                "reason": "候选模型用于受控观察并需要保留原始门禁失败证据",
                "business_impact": "立即阻断会中断已批准的受控验证计划",
                "compensating_controls": "限期内全部结果进入人工复核并每日监控",
                "valid_until": date.today() + timedelta(days=30),
            }, "maker", "制作者")
            comparisons.review_exception(comparison_id, exception["id"], 1, "approve", "同意限期观察并保持原门禁结论", "risk", "风控经理")
            refreshed = governance.get_change(change_id)
            self.assertFalse(refreshed["comparison_evidence"]["current_gate"]["passed"])
            self.assertEqual(refreshed["comparison_evidence"]["current_effective_status"], "exception_approved")
            submitted = governance.submit_change(change_id, bound["row_version"], "maker", "制作者")
            self.assertEqual(submitted["status"], "pending_review")


if __name__ == "__main__":
    unittest.main()
