from __future__ import annotations

import unittest
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

import backend.database as database
from backend.db_models import ModelReleaseRecord, NotificationRecord, RuleCenterReplayComparisonRun, RuleCenterReplayDataset, RuleCenterReplayDatasetSnapshot, TenantRolloutPolicyRecord, TenantRolloutScanRecord
from backend.dependencies import demo_repository
from backend.main import app
from backend.repository import RuleCenterReplayComparisonRepository, RuleCenterReplayDatasetRepository, clear_persistent_data, content_hash
from backend.security import Principal, ROLE_PERMISSIONS, get_current_principal
from backend.tenant_asset_repository import TenantAssetRepository
from backend.tenant_rollout_repository import TenantRolloutRepository
from backend.jobs.tenant_rollout_scan import run_tenant_rollout_scan
from scripts.seed_indicators import seed_from_pool_json
from scripts.seed_rule_center import seed_all
from tests.database_support import IsolatedTestDatabase


TENANT_ID = "tenant-demo-hengxin"


def principal(subject: str, role: str) -> Principal:
    return Principal(
        subject=subject, name=subject, roles=(role,), permissions=frozenset(ROLE_PERMISSIONS[role]),
        tenant_id=TENANT_ID, client_id="platform-console",
    )


class TenantRolloutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.database = IsolatedTestDatabase()
        cls.database.start()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        app.dependency_overrides.clear()
        cls.client.close()
        cls.database.stop()

    def setUp(self) -> None:
        app.dependency_overrides.clear()
        with database.SessionLocal() as session:
            clear_persistent_data(session)
            session.query(RuleCenterReplayComparisonRun).delete()
            session.query(RuleCenterReplayDatasetSnapshot).delete()
            session.query(RuleCenterReplayDataset).delete()
            seed_from_pool_json(session)
            seed_all(session=session)
            base = demo_repository.get_template("general")
            champion = deepcopy(base)
            champion["version"] = "rollout-champion-v1"
            challenger = deepcopy(base)
            challenger["name"] = "企业信用灰度候选模型"
            challenger["version"] = "rollout-challenger-v2"
            challenger["thresholds"]["overdue_rate"] = 0.08
            session.add_all([
                ModelReleaseRecord(id=str(uuid4()), template_key="general", model_version=champion["version"], config_json=champion, config_hash=content_hash(champion), source_change_id=None, is_active=True, published_by="seed"),
                ModelReleaseRecord(id=str(uuid4()), template_key="general-next", model_version=challenger["version"], config_json=challenger, config_hash=content_hash(challenger), source_change_id=None, is_active=True, published_by="seed"),
            ])
            dataset = RuleCenterReplayDataset(
                id=str(uuid4()), tenant_id=TENANT_ID, code="ROLLOUT-EVIDENCE", name="灰度上线证据",
                description="固定 Champion Challenger 上线门禁证据", status="active", created_by="seed", created_by_name="seed",
            )
            snapshot = RuleCenterReplayDatasetSnapshot(
                id=str(uuid4()), tenant_id=TENANT_ID, dataset_id=dataset.id, version=1, source_name="test",
                schema_version="1", as_of_date=date.today(), evidence_reference="test://rollout",
                data_classification="synthetic", field_mapping_json={}, label_field=None, observed_at_field=None,
                sample_count=2, samples_json=[{"sample": {"id": "A"}}, {"sample": {"id": "B"}}],
                coverage_json={}, source_hash="a" * 64, content_hash="pending", created_by="seed", created_by_name="seed",
            )
            session.add_all([dataset, snapshot])
            session.flush()
            snapshot.content_hash = RuleCenterReplayDatasetRepository.snapshot_content_hash(snapshot)
            comparison_assets = {"schema_version": "tenant-replay-comparison-assets-v1", "tenant_id": TENANT_ID}
            comparison = RuleCenterReplayComparisonRun(
                id=str(uuid4()), tenant_id=TENANT_ID, dataset_snapshot_id=snapshot.id, dataset_snapshot_hash=snapshot.content_hash,
                champion_model_key="general", champion_model_version=champion["version"],
                challenger_model_key="general-next", challenger_model_version=challenger["version"],
                champion_pipeline_code="PIPELINE-GENERAL", champion_pipeline_version="1",
                challenger_pipeline_code="PIPELINE-GENERAL", challenger_pipeline_version="1",
                segment_field="counterparty_type", evidence_level="unlabeled", config_json={}, metrics_json={}, details_json=[],
                gate_json={"passed": True, "summary": "固定回放门禁通过", "violations": [], "warnings": ["非监督证据"]},
                asset_snapshot_json=comparison_assets, assets_hash=content_hash(comparison_assets), evidence_hash="pending",
                created_by="seed", created_by_name="seed",
            )
            session.add(comparison)
            session.flush()
            comparison.evidence_hash = RuleCenterReplayComparisonRepository.comparison_evidence_hash(comparison)
            self.comparison_id = comparison.id
            session.commit()
        self._as(principal("rollout-maker", "model_admin"))

    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def _as(self, value: Principal) -> None:
        app.dependency_overrides[get_current_principal] = lambda: value

    def _create_active(self, *, min_sample_size: int = 10, thresholds: dict | None = None) -> dict:
        now = datetime.now(timezone.utc)
        created = self.client.post("/api/v1/model-governance/rollouts", json={
            "name": "企业信用模型 50% 灰度", "comparison_run_id": self.comparison_id,
            "routing_key_field": "counterparty_id", "traffic_basis_points": 5000,
            "observation_window_minutes": 60, "min_sample_size": min_sample_size,
            "thresholds": thresholds or {"max_challenger_failure_rate": 0.05, "max_latency_increase_ratio": 0.5, "max_score_psi": 10, "max_admission_distribution_shift": 1},
            "starts_at": (now - timedelta(minutes=1)).isoformat(), "ends_at": (now + timedelta(days=7)).isoformat(),
            "reason": "启动企业信用候选模型受控灰度观察",
        })
        self.assertEqual(created.status_code, 201, created.text)
        submitted = self.client.post(f"/api/v1/model-governance/rollouts/{created.json()['id']}/submit", json={
            "expected_row_version": created.json()["row_version"], "reason": "回放证据与在线保护阈值已核对",
        })
        self.assertEqual(submitted.status_code, 200, submitted.text)
        same_actor = self.client.post(f"/api/v1/model-governance/rollouts/{created.json()['id']}/review", json={
            "expected_row_version": submitted.json()["row_version"], "decision": "approve", "comment": "批准进入租户受控灰度",
        })
        self.assertEqual(same_actor.status_code, 403)
        self._as(principal("rollout-reviewer", "risk_manager"))
        approved = self.client.post(f"/api/v1/model-governance/rollouts/{created.json()['id']}/review", json={
            "expected_row_version": submitted.json()["row_version"], "decision": "approve", "comment": "独立复核固定证据与熔断阈值后批准",
        })
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(approved.json()["status"], "active")
        return approved.json()

    def test_four_eyes_stable_routing_and_explicit_selection_bypass(self) -> None:
        policy = self._create_active()
        with database.SessionLocal() as session:
            repository = TenantRolloutRepository(session, demo_repository)
            first = repository.route(TENANT_ID, "general", "company-001", "test", "request-001")
            second = repository.route(TENANT_ID, "general", "company-001", "test", "request-002")
            self.assertEqual(first["routing"]["bucket"], second["routing"]["bucket"])
            self.assertEqual(first["routing"]["selected_arm"], second["routing"]["selected_arm"])
            self.assertEqual(first["routing"]["policy_id"], policy["id"])
            bypassed = repository.route(TENANT_ID, "general", "company-001", "test", "request-003", explicit_selection=True)
            self.assertIsNone(bypassed)
            session.rollback()

        self._as(principal("rating-user", "risk_manager"))
        rated = self.client.post("/api/v1/ratings/run", json={"counterparty_id": "cp_supplier_low_001", "template_key": "general"})
        self.assertEqual(rated.status_code, 200, rated.text)
        self.assertEqual(rated.json()["asset_resolution"]["routing"]["policy_id"], policy["id"])

        self._as(principal("integration-user", "integration_admin"))
        decided = self.client.post("/api/v1/decisions", json={
            "request_id": "ROLLOUT-DECISION-001", "counterparty_id": "cp_supplier_low_001", "input": None,
            "assets": {"model_key": "general", "pipeline_code": "PIPELINE-GENERAL", "rule_set_versions": {}, "rule_versions": {}},
            "metadata": {"source_system": "ERP", "scenario": "supplier_admission"},
        })
        self.assertEqual(decided.status_code, 200, decided.text)
        self.assertEqual(decided.json()["assets"]["routing"]["policy_id"], policy["id"])
        pinned = self.client.post("/api/v1/decisions", json={
            "request_id": "ROLLOUT-DECISION-002", "counterparty_id": "cp_supplier_low_001", "input": None,
            "assets": {"model_key": "general", "model_version": "rollout-champion-v1", "pipeline_code": "PIPELINE-GENERAL", "rule_set_versions": {}, "rule_versions": {}},
            "metadata": {"source_system": "ERP", "scenario": "supplier_admission"},
        })
        self.assertEqual(pinned.status_code, 200, pinned.text)
        self.assertNotIn("routing", pinned.json()["assets"])

    def test_online_unlabeled_evidence_triggers_automatic_rollback(self) -> None:
        policy = self._create_active(min_sample_size=2, thresholds={
            "max_challenger_failure_rate": 0, "max_latency_increase_ratio": 10,
            "max_score_psi": 10, "max_admission_distribution_shift": 1,
        })
        with database.SessionLocal() as session:
            repository = TenantRolloutRepository(session, demo_repository)
            routed = {}
            index = 0
            while set(routed) != {"champion", "challenger"}:
                key = f"company-{index}"
                assets = repository.route(TENANT_ID, "general", key, "test", f"auto-{index}")
                routed.setdefault(assets["routing"]["selected_arm"], assets)
                index += 1
                self.assertLess(index, 100)
            repository.complete_route(routed["champion"], {"total_score": 80, "rating": "A", "final_admission": "approve"}, 10)
            repository.complete_route(routed["challenger"], None, 10, "MODEL_EXECUTION_FAILED")
            session.commit()
            stored = session.get(TenantRolloutPolicyRecord, policy["id"])
            self.assertEqual(stored.status, "rolled_back")
            evaluations = repository.list_evaluations(TENANT_ID, policy["id"])
            self.assertEqual(evaluations[0]["action"], "automatic_rollback")
            self.assertEqual(evaluations[0]["evidence_level"], "unlabeled_online")
            self.assertFalse(evaluations[0]["metrics"]["supervised_metrics_available"])
            self.assertEqual(stored.incident_status, "open")
            self.assertEqual(session.query(NotificationRecord).filter(
                NotificationRecord.tenant_id == TENANT_ID,
                NotificationRecord.category == "model_governance",
            ).count(), 2)

        self._as(principal("rollout-reviewer", "risk_manager"))
        missing = self.client.post(f"/api/v1/model-governance/rollouts/{policy['id']}/incident", json={
            "expected_row_version": stored.row_version, "action": "approve_resolution", "reason": "不能跳过异常确认和整改提交",
        })
        self.assertEqual(missing.status_code, 409)
        acknowledged = self.client.post(f"/api/v1/model-governance/rollouts/{policy['id']}/incident", json={
            "expected_row_version": stored.row_version, "action": "acknowledge", "reason": "核对失败率阈值并保留原有执行证据",
        })
        self.assertEqual(acknowledged.status_code, 200, acknowledged.text)
        requested = self.client.post(f"/api/v1/model-governance/rollouts/{policy['id']}/incident", json={
            "expected_row_version": acknowledged.json()["row_version"], "action": "request_resolution", "reason": "确认数据源异常并准备新版本灰度方案",
        })
        self.assertEqual(requested.status_code, 200, requested.text)
        same_actor = self.client.post(f"/api/v1/model-governance/rollouts/{policy['id']}/incident", json={
            "expected_row_version": requested.json()["row_version"], "action": "approve_resolution", "reason": "申请关闭事故并保留回滚事实",
        })
        self.assertEqual(same_actor.status_code, 409)
        self._as(principal("independent-reviewer", "risk_manager"))
        resolved = self.client.post(f"/api/v1/model-governance/rollouts/{policy['id']}/incident", json={
            "expected_row_version": requested.json()["row_version"], "action": "approve_resolution", "reason": "独立核对整改依据，同意关闭事故但不得自动恢复流量",
        })
        self.assertEqual(resolved.status_code, 200, resolved.text)
        self.assertEqual(resolved.json()["incident_status"], "resolved")
        self.assertEqual(resolved.json()["status"], "rolled_back")
        with database.SessionLocal() as session:
            self.assertEqual(session.query(NotificationRecord).filter(
                NotificationRecord.tenant_id == TENANT_ID, NotificationRecord.category == "model_governance",
                NotificationRecord.status == "resolved",
            ).count(), 2)

    def test_periodic_scan_closes_low_sample_window_and_is_idempotent(self) -> None:
        policy = self._create_active(min_sample_size=100)
        after_window = datetime.fromisoformat(policy["ends_at"]) + timedelta(minutes=1)
        with database.SessionLocal() as session:
            first = run_tenant_rollout_scan(session, now=after_window)["runs"][0]
            second = TenantRolloutRepository(session, demo_repository).scan(
                TENANT_ID, principal("rollout-scheduler", "risk_manager"), now=after_window,
                trigger_type="scheduler",
            )
            self.assertFalse(first["idempotent"])
            self.assertTrue(second["idempotent"])
            self.assertEqual(first["run"]["evidence_hash"], second["run"]["evidence_hash"])
            self.assertEqual(session.query(TenantRolloutScanRecord).count(), 1)
            closed = session.get(TenantRolloutPolicyRecord, policy["id"])
            self.assertEqual(closed.status, "completed")
            self.assertIn("证据不足", closed.terminal_reason)
            self.assertEqual(closed.incident_status, "not_applicable")
            self.assertEqual(TenantRolloutRepository(session, demo_repository).route(
                TENANT_ID, "general", "company-after", "test", "after-window",
            ), None)

        scans = self.client.get("/api/v1/model-governance/rollouts/scans")
        self.assertEqual(scans.status_code, 200, scans.text)
        self.assertEqual(scans.json()[0]["status"], "completed")
        self._as(Principal(subject="other", name="other", roles=("risk_manager",), permissions=frozenset(ROLE_PERMISSIONS["risk_manager"]), tenant_id="tenant-demo-alt", client_id="platform-console"))
        self.assertEqual(self.client.get("/api/v1/model-governance/rollouts/scans").json(), [])
        self.assertEqual(self.client.post(f"/api/v1/model-governance/rollouts/{policy['id']}/incident", json={
            "expected_row_version": closed.row_version, "action": "acknowledge", "reason": "跨租户尝试不可见",
        }).status_code, 404)

    def test_scan_activates_scheduled_policy_and_replaces_previous(self) -> None:
        previous = self._create_active()
        self._as(principal("new-rollout-maker", "model_admin"))
        now = datetime.now(timezone.utc)
        created = self.client.post("/api/v1/model-governance/rollouts", json={
            "name": "下一期灰度排期", "comparison_run_id": self.comparison_id,
            "routing_key_field": "counterparty_id", "traffic_basis_points": 1000,
            "observation_window_minutes": 60, "min_sample_size": 10,
            "thresholds": {"max_challenger_failure_rate": 0.05, "max_latency_increase_ratio": 0.5, "max_score_psi": 10, "max_admission_distribution_shift": 1},
            "starts_at": (now + timedelta(minutes=1)).isoformat(), "ends_at": (now + timedelta(days=7)).isoformat(),
            "reason": "预约下一期租户候选模型灰度",
        })
        self.assertEqual(created.status_code, 201, created.text)
        submitted = self.client.post(f"/api/v1/model-governance/rollouts/{created.json()['id']}/submit", json={
            "expected_row_version": created.json()["row_version"], "reason": "固定证据与排期已核对",
        })
        self._as(principal("new-rollout-reviewer", "risk_manager"))
        approved = self.client.post(f"/api/v1/model-governance/rollouts/{created.json()['id']}/review", json={
            "expected_row_version": submitted.json()["row_version"], "decision": "approve", "comment": "独立批准下一期灰度排期",
        })
        self.assertEqual(approved.json()["status"], "scheduled")
        with database.SessionLocal() as session:
            result = run_tenant_rollout_scan(session, now=now + timedelta(minutes=2))
            self.assertEqual(result["failed_count"], 0, result)
            self.assertEqual(session.get(TenantRolloutPolicyRecord, created.json()["id"]).status, "active")
            self.assertEqual(session.get(TenantRolloutPolicyRecord, previous["id"]).status, "completed")
            self.assertEqual(result["runs"][0]["run"]["results"][0]["action"], "activate")
            drifted = session.get(TenantRolloutPolicyRecord, previous["id"])
            drifted.status = "scheduled"
            drifted.starts_at = now + timedelta(minutes=3)
            session.commit()
            failed = run_tenant_rollout_scan(session, now=now + timedelta(minutes=7))
            self.assertEqual(failed["failed_count"], 1)
            self.assertEqual(failed["runs"][0]["run"]["status"], "failed")
            self.assertEqual(session.get(TenantRolloutPolicyRecord, created.json()["id"]).status, "active")
            self.assertEqual(session.query(NotificationRecord).filter(
                NotificationRecord.tenant_id == TENANT_ID,
                NotificationRecord.title == "灰度周期扫描执行异常",
            ).count(), 2)


if __name__ == "__main__":
    unittest.main()
