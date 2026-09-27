from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import unittest
from uuid import uuid4
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

import backend.database as database
from backend.db_models import ModelChangeRecord, ModelReleaseRecord, ModelRiskAcceptanceRecord, NotificationRecord, TenantMonitoringDiffCaseRecord, TenantMonitoringRunRecord, TenantOutcomeLabelDefinitionRecord, TenantOutcomeLabelRecord, TenantRolloutPolicyRecord, TenantRoutingDecisionRecord, TenantSupervisedEvaluationRecord
from backend.model_risk_catalog import risk_catalog
from backend.model_risk_policy_repository import ModelRiskPolicyError, ModelRiskPolicyRepository
from backend.main import app
from backend.repository import DemoRepository, clear_persistent_data, content_hash
from backend.security import Principal, ROLE_PERMISSIONS, get_current_principal
from scripts.audit_label_evidence_normalization import scan_labels
from backend.jobs.tenant_monitoring_snapshot import run_tenant_monitoring_snapshot
from backend.jobs.tenant_monitoring_gate_scan import run_tenant_monitoring_gate_scan
from backend.tenant_outcome_repository import TenantOutcomeRepository
from tests.database_support import IsolatedTestDatabase


TENANT_ID = "tenant-demo-hengxin"


def principal(subject: str, role: str, tenant_id: str = TENANT_ID) -> Principal:
    return Principal(subject=subject, name=subject, roles=(role,), permissions=frozenset(ROLE_PERMISSIONS[role]), tenant_id=tenant_id, client_id="platform-console")


class TenantOutcomeTest(unittest.TestCase):
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
            now = datetime.now(timezone.utc)
            champion_config = DemoRepository().get_template("corporate_credit_v2")
            challenger_config = deepcopy(champion_config)
            challenger_config["version"] = "chall-v2"
            arm_snapshot = {
                "schema_version": "tenant-rollout-arms-v1",
                "champion": {"model": {"key": "corporate_credit_v2", "version": champion_config["version"], "config": champion_config}},
                "challenger": {"model": {"key": "corporate_credit_v2", "version": "chall-v2", "config": challenger_config}},
            }
            policy = TenantRolloutPolicyRecord(
                id=str(uuid4()), tenant_id=TENANT_ID, name="延迟监督测试策略",
                comparison_run_id=str(uuid4()), comparison_evidence_hash="a" * 64, comparison_assets_hash="b" * 64,
                champion_model_key="corporate_credit_v2", champion_model_version=champion_config["version"], champion_pipeline_code="PIPELINE-GENERAL", champion_pipeline_version="1",
                challenger_model_key="corporate_credit_v2", challenger_model_version="chall-v2", challenger_pipeline_code="PIPELINE-GENERAL", challenger_pipeline_version="1",
                routing_key_field="counterparty_id", traffic_basis_points=5000, observation_window_minutes=1440, min_sample_size=4,
                thresholds_json={"max_challenger_failure_rate": 0.05, "max_latency_increase_ratio": 0.5, "max_score_psi": 0.25, "max_admission_distribution_shift": 0.15},
                config_json={"test": True}, config_hash=content_hash({"test": True}),
                arm_snapshot_json=arm_snapshot, assets_hash=content_hash(arm_snapshot),
                status="rolled_back", starts_at=now - timedelta(days=120), ends_at=now - timedelta(days=10),
                change_reason="验证成熟标签回流与监督评估", created_by="maker", created_by_name="maker",
                rolled_back_at=now - timedelta(days=9), terminal_reason="测试保护性回滚",
            )
            session.add(policy)
            session.commit()
            self.policy_id = policy.id
            self.definition_id = session.query(TenantOutcomeLabelDefinitionRecord.id).filter_by(
                tenant_id=TENANT_ID, code="90_days_default", status="published", is_active=True,
            ).scalar()
        self._as(principal("label-maker", "model_admin"))

    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def _as(self, value: Principal) -> None:
        app.dependency_overrides[get_current_principal] = lambda: value

    def _route(self, counterparty_id: str, arm: str, score: float, *, channel: str = "test") -> str:
        now = datetime.now(timezone.utc)
        with database.SessionLocal() as session:
            policy = session.get(TenantRolloutPolicyRecord, self.policy_id)
            model_key, model_version = (
                (policy.champion_model_key, policy.champion_model_version)
                if arm == "champion"
                else (policy.challenger_model_key, policy.challenger_model_version)
            )
        assets = {"model": {"key": model_key, "version": model_version}}
        route = TenantRoutingDecisionRecord(
            id=str(uuid4()), tenant_id=TENANT_ID, policy_id=self.policy_id,
            policy_config_hash=content_hash({"test": True}), policy_assets_hash=content_hash(policy.arm_snapshot_json),
            channel=channel, request_ref=f"request-{counterparty_id}",
            routing_key_hash=hashlib.sha256(counterparty_id.encode("utf-8")).hexdigest(), bucket=100 if arm == "challenger" else 9000,
            selected_arm=arm, selected_assets_json=assets, selected_assets_hash=content_hash(assets),
            status="completed", elapsed_ms=12, score=score, rating="B" if score < 60 else "A",
            admission="reject" if score < 60 else "approve", result_hash=content_hash({"total_score": score}),
            completed_at=now - timedelta(days=120), created_at=now - timedelta(days=121),
        )
        route.evidence_hash = content_hash({
            "tenant_id": route.tenant_id, "policy_id": route.policy_id,
            "policy_config_hash": route.policy_config_hash, "policy_assets_hash": route.policy_assets_hash,
            "routing_key_hash": route.routing_key_hash, "bucket": route.bucket,
            "selected_arm": route.selected_arm, "selected_assets_hash": route.selected_assets_hash,
            "status": route.status, "elapsed_ms": route.elapsed_ms, "score": str(route.score),
            "rating": route.rating, "admission": route.admission, "error_code": route.error_code,
            "result_hash": route.result_hash,
        })
        with database.SessionLocal() as session:
            session.add(route)
            session.commit()
        return route.id

    def _create(self, route_id: str, counterparty_id: str, observed_event: bool, *, external_id: str, future: bool = False, observation_end: datetime | None = None):
        observation_end = observation_end or (datetime.now(timezone.utc) + timedelta(days=30) if future else datetime.now(timezone.utc) - timedelta(days=30))
        return self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/outcomes", json={
            "source": "贷后核心系统", "external_label_id": external_id, "routing_decision_id": route_id,
            "counterparty_id": counterparty_id, "label_definition_id": self.definition_id,
            "observed_event": observed_event, "observation_end": observation_end.isoformat(),
            "loss_amount": 100 if observed_event else 0, "exposure_amount": 1000,
            "evidence_reference": f"s3://outcomes/{external_id}.json",
        })

    def _verify(self, label: dict) -> dict:
        self._as(principal("label-reviewer", "risk_manager"))
        response = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/outcomes/{label['id']}/verify", json={
            "expected_row_version": label["row_version"], "decision": "verify", "note": "已独立核对贷后结果来源与观察窗口",
        })
        self.assertEqual(response.status_code, 200, response.text)
        self._as(principal("label-maker", "model_admin"))
        return response.json()

    def test_label_is_idempotent_conflicts_and_enforces_tenant_route_link(self) -> None:
        route_id = self._route("cp-001", "champion", 80)
        observation_end = datetime.now(timezone.utc) - timedelta(days=30)
        created = self._create(route_id, "cp-001", False, external_id="LABEL-001", observation_end=observation_end)
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["evidence_schema_version"], "tenant-outcome-label-v4")
        with database.SessionLocal() as session:
            label = session.get(TenantOutcomeLabelRecord, created.json()["id"])
            label.canonical_evidence_json = {**label.canonical_evidence_json, "evidence_reference": "tampered://label"}
            session.commit()
        self._as(principal("label-reviewer", "risk_manager"))
        tampered = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/outcomes/{created.json()['id']}/verify", json={
            "expected_row_version": created.json()["row_version"], "decision": "verify", "note": "篡改规范载荷不得核验",
        })
        self.assertEqual(tampered.status_code, 409)
        with database.SessionLocal() as session:
            label = session.get(TenantOutcomeLabelRecord, created.json()["id"])
            label.canonical_evidence_json = {**label.canonical_evidence_json, "evidence_reference": created.json()["evidence_reference"]}
            session.commit()
        self._as(principal("label-maker", "model_admin"))
        self.assertFalse(created.json()["idempotent"])
        repeated = self._create(route_id, "cp-001", False, external_id="LABEL-001", observation_end=observation_end)
        self.assertEqual(repeated.status_code, 201, repeated.text)
        self.assertTrue(repeated.json()["idempotent"])
        conflict = self._create(route_id, "cp-001", True, external_id="LABEL-001", observation_end=observation_end)
        self.assertEqual(conflict.status_code, 409)
        wrong_counterparty = self._create(route_id, "cp-002", False, external_id="LABEL-002")
        self.assertEqual(wrong_counterparty.status_code, 409)
        self._as(principal("other-maker", "model_admin", "tenant-demo-alt"))
        cross_tenant = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/outcomes", json={
            "source": "贷后核心系统", "external_label_id": "LABEL-X", "routing_decision_id": route_id,
            "counterparty_id": "cp-001", "label_definition_id": self.definition_id, "observed_event": False,
            "observation_end": datetime.now(timezone.utc).isoformat(), "evidence_reference": "test://cross-tenant",
        })
        self.assertEqual(cross_tenant.status_code, 404)

    def test_normalization_audit_is_read_only_and_classifies_legacy_labels(self) -> None:
        route_id = self._route("cp-audit", "champion", 82)
        created = self._create(route_id, "cp-audit", False, external_id="LABEL-AUDIT").json()
        with database.SessionLocal() as session:
            before = session.get(TenantOutcomeLabelRecord, created["id"])
            before_values = (before.evidence_hash, before.evidence_schema_version, before.canonical_evidence_json)
            report = scan_labels(session, TENANT_ID, self.policy_id)
            row = next(item for item in report["rows"] if item["id"] == created["id"])
            self.assertEqual(row["status"], "canonical_valid")
            session.refresh(before)
            self.assertEqual((before.evidence_hash, before.evidence_schema_version, before.canonical_evidence_json), before_values)

            before.evidence_schema_version = "tenant-outcome-label-v3"
            before.canonical_evidence_json = None
            session.commit()
            legacy_report = scan_labels(session, TENANT_ID, self.policy_id)
            legacy_row = next(item for item in legacy_report["rows"] if item["id"] == created["id"])
            self.assertEqual(legacy_row["status"], "legacy_manual_review")
            session.refresh(before)
            self.assertIsNone(before.canonical_evidence_json)

    def test_tenant_monitoring_run_is_tenant_native_and_evaluation_bound(self) -> None:
        now = datetime.now(timezone.utc)
        with database.SessionLocal() as session:
            policy = session.get(TenantRolloutPolicyRecord, self.policy_id)
            model_version = policy.champion_model_version
        run_payload = {
            "run_key": "tenant-run-native-001", "model_key": "corporate_credit_v2",
            "model_version": model_version, "observed_from": (now - timedelta(days=90)).isoformat(),
            "observed_to": (now - timedelta(hours=1)).isoformat(), "dataset_id": "tenant-dataset-q3",
            "evidence_level": "non_supervised", "status": "completed",
            "monitoring": {"psi": 0.08, "ks": None}, "label_watermark": {},
        }
        created = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/tenant-monitoring-runs", json=run_payload)
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["evidence_level"], "non_supervised")
        repeated = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/tenant-monitoring-runs", json=run_payload)
        self.assertEqual(repeated.status_code, 201, repeated.text)
        self.assertTrue(repeated.json()["idempotent"])
        self._as(principal("other-tenant", "model_admin", "tenant-demo-alt"))
        cross_tenant = self.client.get(f"/api/v1/model-governance/rollouts/{self.policy_id}/tenant-monitoring-runs")
        self.assertEqual(cross_tenant.status_code, 404)
        self._as(principal("label-reviewer", "risk_manager"))
        evaluation = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/supervised-evaluate", json={
            "evaluation_as_of": (now - timedelta(hours=1)).isoformat(),
            "tenant_monitoring_run_id": created.json()["id"],
            "min_mature_samples": 2, "min_events": 1, "min_non_events": 1,
        })
        self.assertEqual(evaluation.status_code, 201, evaluation.text)
        self.assertEqual(evaluation.json()["tenant_monitoring_run_id"], created.json()["id"])
        with database.SessionLocal() as session:
            run = session.get(TenantMonitoringRunRecord, created.json()["id"])
            run.monitoring_json = {"psi": 0.99}
            session.commit()
            record = session.get(TenantSupervisedEvaluationRecord, evaluation.json()["id"])
            with self.assertRaisesRegex(Exception, "租户监控运行"):
                __import__("backend.tenant_outcome_repository", fromlist=["TenantOutcomeRepository"]).TenantOutcomeRepository(session)._verify_evaluation_integrity(record)

    def test_monitoring_snapshot_generation_is_derived_and_idempotent(self) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        self._as(principal("label-reviewer", "risk_manager"))
        response = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/tenant-monitoring-runs/generate", json={
            "label_definition_id": self.definition_id, "as_of": (now - timedelta(minutes=1)).isoformat(),
        })
        self.assertEqual(response.status_code, 201, response.text)
        result = response.json()
        self.assertEqual(len(result["runs"]), 2)
        self.assertTrue(all(item["evidence_level"] == "non_supervised" for item in result["runs"]))
        self.assertTrue(all(item["governance_status"] == "draft" for item in result["runs"]))
        self.assertTrue(all(item["monitoring"]["source"] == "tenant_routing_and_verified_outcomes" for item in result["runs"]))
        repeated = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/tenant-monitoring-runs/generate", json={
            "label_definition_id": self.definition_id, "as_of": (now - timedelta(minutes=1)).isoformat(),
        })
        self.assertEqual(repeated.status_code, 201, repeated.text)
        self.assertTrue(repeated.json()["idempotent"])

    def test_monitoring_gate_blocks_thresholds_downgrades_unlabeled_and_closes_notifications(self) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        with database.SessionLocal() as session:
            policy = session.get(TenantRolloutPolicyRecord, self.policy_id)
            repository = TenantOutcomeRepository(session)
            actor = principal("monitoring-maker", "model_admin")
            base = {
                "model_key": policy.champion_model_key, "model_version": policy.champion_model_version,
                "observed_from": now - timedelta(days=30), "observed_to": now - timedelta(minutes=1),
                "dataset_id": "gate-dataset", "status": "completed", "governance_status": "published",
                "label_watermark": {},
            }
            blocked = repository.create_monitoring_run(TENANT_ID, self.policy_id, {
                **base, "run_key": "tenant-gate-blocked", "evidence_level": "supervised",
                "monitoring": {
                    "challenger_failure_rate": 0.01, "latency_increase_ratio": 0.1,
                    "score_psi_champion_vs_challenger": 0.9, "admission_distribution_shift": 0.05,
                    "auc": 0.75, "ks": 0.31,
                    "coverage": {"mature_verified_count": 14, "event_count": 6, "non_event_count": 8},
                },
            }, actor)
            diagnostic = repository.create_monitoring_run(TENANT_ID, self.policy_id, {
                **base, "run_key": "tenant-gate-unlabeled", "dataset_id": "gate-dataset-unlabeled",
                "model_version": policy.challenger_model_version,
                "evidence_level": "non_supervised",
                "monitoring": {
                    "challenger_failure_rate": 0.01, "latency_increase_ratio": 0.1,
                    "score_psi_champion_vs_challenger": 0.08, "admission_distribution_shift": 0.05,
                    "auc": None, "ks": None, "degraded_reason": "标签样本不足",
                },
            }, actor)
            self.assertEqual(repository.monitoring_gate(TENANT_ID, self.policy_id, blocked["id"])["status"], "blocked")
            self.assertEqual(repository.monitoring_gate(TENANT_ID, self.policy_id, diagnostic["id"])["status"], "at_risk")
            unified = ModelRiskPolicyRepository(session).unified_review_queue(
                TENANT_ID, template_key=policy.champion_model_key, now=now,
            )
            gate_priorities = {item["monitoring_run_id"]: item["priority"] for item in unified if item["source"] == "monitoring_gate"}
            self.assertEqual(gate_priorities, {blocked["id"]: "P1", diagnostic["id"]: "P3"})
            self.assertEqual(ModelRiskPolicyRepository(session).unified_review_queue("tenant-demo-alt", now=now), [])
            first_scan = run_tenant_monitoring_gate_scan(session, TENANT_ID)
            self.assertEqual((first_scan["blocked_count"], first_scan["at_risk_count"]), (1, 1))
            self.assertEqual(first_scan["notifications_created"], 4)
            self.assertEqual(run_tenant_monitoring_gate_scan(session, TENANT_ID)["notifications_created"], 0)

            for run_id in (blocked["id"], diagnostic["id"]):
                run = session.get(TenantMonitoringRunRecord, run_id)
                run.evidence_level = "supervised"
                run.monitoring_json = {
                    "challenger_failure_rate": 0.01, "latency_increase_ratio": 0.1,
                    "score_psi_champion_vs_challenger": 0.08, "admission_distribution_shift": 0.05,
                    "auc": 0.75, "ks": 0.31,
                    "coverage": {"mature_verified_count": 14, "event_count": 6, "non_event_count": 8},
                }
                run.evidence_hash = TenantOutcomeRepository.monitoring_run_evidence_hash(run)
            session.commit()
            recovered = run_tenant_monitoring_gate_scan(session, TENANT_ID)
            self.assertEqual(recovered["accepted_count"], 2)
            self.assertEqual(recovered["notifications_resolved"], 4)
            self.assertEqual(session.query(NotificationRecord).filter(
                NotificationRecord.category == "tenant_monitoring_gate",
                NotificationRecord.status != "resolved",
            ).count(), 0)

            run = session.get(TenantMonitoringRunRecord, blocked["id"])
            run.monitoring_json = {**run.monitoring_json, "score_psi_champion_vs_challenger": 0.99}
            session.commit()
            stale = repository.monitoring_gate(TENANT_ID, self.policy_id, blocked["id"])
            self.assertEqual(stale["status"], "evidence_stale")
            stale_queue = ModelRiskPolicyRepository(session).unified_review_queue(
                TENANT_ID, template_key=policy.champion_model_key, now=now,
            )
            self.assertEqual(next(item for item in stale_queue if item["monitoring_run_id"] == blocked["id"])["priority"], "P0")

        response = self.client.get(f"/api/v1/model-governance/rollouts/{self.policy_id}/tenant-monitoring-runs/{blocked['id']}/gate")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "evidence_stale")
        self._as(principal("gate-reviewer", "risk_manager"))
        scan_response = self.client.post("/api/v1/model-governance/rollouts/monitoring-gates/scan")
        self.assertEqual(scan_response.status_code, 200, scan_response.text)
        self.assertEqual(scan_response.json()["stale_count"], 1)
        self.assertEqual(scan_response.json()["notifications_created"], 2)

    def test_monitoring_snapshot_scheduler_is_tenant_scoped_and_idempotent(self) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        with database.SessionLocal() as session:
            policy = session.get(TenantRolloutPolicyRecord, self.policy_id)
            policy.status = "active"
            policy.starts_at = now - timedelta(days=180)
            policy.ends_at = now + timedelta(days=1)
            definition = session.get(TenantOutcomeLabelDefinitionRecord, self.definition_id)
            definition.applicable_model_keys_json = sorted(set(definition.applicable_model_keys_json or []) | {
                policy.champion_model_key, policy.challenger_model_key,
            })
            definition.config_hash = content_hash(TenantOutcomeRepository._definition_config_from_record(definition))
            session.commit()
            # This fixture models a retained historical policy without its original comparison
            # row. The scheduler contract is exercised here; active-policy integrity is covered
            # by the rollout suite and is still enforced in production code.
            with patch("backend.tenant_outcome_repository.TenantRolloutRepository._verify_integrity"):
                generated = run_tenant_monitoring_snapshot(session, now=now, tenant_id=TENANT_ID)
                self.assertEqual(generated["policy_count"], 1)
                self.assertEqual(generated["generated_count"], 1, generated)
                self.assertEqual(generated["failed_count"], 0)
                repeated = run_tenant_monitoring_snapshot(session, now=now, tenant_id=TENANT_ID)
        self.assertEqual(repeated["generated_count"], 1)
        self.assertTrue(repeated["generated"][0]["result"]["idempotent"])
        filtered = run_tenant_monitoring_snapshot(session, now=now, tenant_id="tenant-demo-alt")
        self.assertEqual(filtered["policy_count"], 0)

    def test_monitoring_run_publication_retraction_and_diff_are_governed(self) -> None:
        first_as_of = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=2)
        second_as_of = first_as_of + timedelta(minutes=1)
        self._as(principal("label-reviewer", "risk_manager"))
        first = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/tenant-monitoring-runs/generate", json={
            "label_definition_id": self.definition_id, "as_of": first_as_of.isoformat(),
        }).json()
        second = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/tenant-monitoring-runs/generate", json={
            "label_definition_id": self.definition_id, "as_of": second_as_of.isoformat(),
        }).json()
        first_run = first["runs"][0]
        second_run = second["runs"][0]
        self._as(principal("label-maker", "model_admin"))
        submitted = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/tenant-monitoring-runs/{first_run['id']}/submit", json={
            "expected_row_version": first_run["row_version"], "note": "已核对固定路由水位和标签口径，提交独立复核",
        })
        self.assertEqual(submitted.status_code, 200, submitted.text)
        self.assertEqual(submitted.json()["governance_status"], "pending_review")
        self._as(principal("independent-reviewer", "risk_manager"))
        reviewed = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/tenant-monitoring-runs/{first_run['id']}/review", json={
            "expected_row_version": submitted.json()["row_version"], "decision": "approve", "comment": "独立复核快照完整性和差异口径后发布",
        })
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        self.assertEqual(reviewed.json()["governance_status"], "published")
        diff = self.client.get(f"/api/v1/model-governance/rollouts/{self.policy_id}/tenant-monitoring-runs/{second_run['id']}/diff", params={"against_run_id": first_run["id"]})
        self.assertEqual(diff.status_code, 200, diff.text)
        self.assertEqual(diff.json()["base_run_id"], second_run["id"])
        self.assertEqual(diff.json()["against_run_id"], first_run["id"])
        self.assertTrue(diff.json()["diff_hash"])
        self._as(principal("retraction-reviewer", "risk_manager"))
        retracted = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/tenant-monitoring-runs/{first_run['id']}/retract", json={
            "expected_row_version": reviewed.json()["row_version"], "reason": "回放差异显示标签水位需重新确认，撤回等待补证",
        })
        self.assertEqual(retracted.status_code, 200, retracted.text)
        self.assertEqual(retracted.json()["governance_status"], "retracted")
        gate = self.client.get(f"/api/v1/model-governance/rollouts/{self.policy_id}/tenant-monitoring-runs/{first_run['id']}/gate")
        self.assertEqual(gate.status_code, 200, gate.text)
        self.assertEqual(gate.json()["status"], "blocked")
        self._as(principal("label-reviewer", "risk_manager"))
        blocked = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/supervised-evaluate", json={
            "evaluation_as_of": first_as_of.isoformat(), "tenant_monitoring_run_id": first_run["id"],
            "min_mature_samples": 2, "min_events": 1, "min_non_events": 1,
        })
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertIn("已发布", blocked.text)

    def test_monitoring_diff_case_recompute_four_eyes_and_publication_gate(self) -> None:
        first_as_of = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=3)
        second_as_of = first_as_of + timedelta(minutes=1)
        self._as(principal("diff-owner", "admin"))
        first = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/tenant-monitoring-runs/generate", json={
            "label_definition_id": self.definition_id, "as_of": first_as_of.isoformat(),
        })
        second = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/tenant-monitoring-runs/generate", json={
            "label_definition_id": self.definition_id, "as_of": second_as_of.isoformat(),
        })
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(second.status_code, 201, second.text)
        first_run, second_run = first.json()["runs"][0], second.json()["runs"][0]
        created = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/monitoring-diff-cases", json={
            "base_run_id": second_run["id"], "against_run_id": first_run["id"],
            "reason": "监控差异需要按冻结截止时间与标签口径重算确认",
        })
        self.assertEqual(created.status_code, 201, created.text)
        case = created.json()
        self.assertEqual(case["severity"], "critical")
        self.assertEqual(case["status"], "open")
        self.assertTrue(case["diff_hash"])
        with database.SessionLocal() as session:
            queue_model_key = session.get(TenantRolloutPolicyRecord, self.policy_id).champion_model_key
        queue = self.client.get("/api/v1/model-governance/risk-review-queue", params={"template_key": queue_model_key})
        self.assertEqual(queue.status_code, 200, queue.text)
        diff_item = next(item for item in queue.json() if item["diff_case_id"] == case["id"])
        self.assertEqual((diff_item["source"], diff_item["priority"]), ("monitoring_diff_case", "P1"))
        repeated = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/monitoring-diff-cases", json={
            "base_run_id": second_run["id"], "against_run_id": first_run["id"],
            "reason": "重复立案必须返回原始差异工单而不是新增记录",
        })
        self.assertTrue(repeated.json()["idempotent"])

        submitted = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/tenant-monitoring-runs/{second_run['id']}/submit", json={
            "expected_row_version": second_run["row_version"], "note": "提交快照复核并验证重大差异门禁",
        })
        self.assertEqual(submitted.status_code, 200, submitted.text)
        self._as(principal("diff-reviewer", "risk_manager"))
        blocked = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/tenant-monitoring-runs/{second_run['id']}/review", json={
            "expected_row_version": submitted.json()["row_version"], "decision": "approve",
            "comment": "重大差异工单尚未关闭时不能发布监控快照",
        })
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertIn("重大监控差异工单", blocked.text)

        self._as(principal("diff-owner", "admin"))
        assigned = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/monitoring-diff-cases/{case['id']}/assign", json={
            "expected_row_version": case["row_version"], "reason": "领取工单并核对冻结口径",
        })
        self.assertEqual(assigned.status_code, 200, assigned.text)
        scan_now = datetime.now(timezone.utc).replace(microsecond=0)
        with database.SessionLocal() as session:
            assigned_record = session.get(TenantMonitoringDiffCaseRecord, case["id"])
            assigned_record.due_at = scan_now - timedelta(hours=13)
            session.commit()
            assigned_row_version = assigned_record.row_version
            sla_repository = TenantOutcomeRepository(session)
            sla_scan = sla_repository.scan_monitoring_diff_case_sla(TENANT_ID, now=scan_now)
            self.assertEqual((sla_scan["escalated"], sla_scan["notifications_created"]), (1, 3))
            self.assertEqual(sla_repository.scan_monitoring_diff_case_sla(TENANT_ID, now=scan_now)["notifications_created"], 0)
            dashboard = sla_repository.monitoring_diff_sla_dashboard(TENANT_ID, template_key=queue_model_key, now=scan_now)
            self.assertEqual((dashboard["counts"]["open"], dashboard["counts"]["escalated"]), (1, 1))
            self.assertEqual(len(dashboard["items"]), 1)
        self._as(principal("sla-viewer", "model_admin"))
        dashboard_response = self.client.get(
            "/api/v1/model-governance/rollouts/monitoring-diff-cases/sla-dashboard",
            params={"template_key": queue_model_key},
        )
        self.assertEqual(dashboard_response.status_code, 200, dashboard_response.text)
        self.assertEqual(dashboard_response.json()["counts"]["escalated"], 1)
        self.assertEqual(self.client.post(
            "/api/v1/model-governance/rollouts/monitoring-diff-cases/sla-scan",
        ).status_code, 403)
        self._as(principal("sla-reviewer", "risk_manager"))
        self.assertEqual(self.client.post(
            "/api/v1/model-governance/rollouts/monitoring-diff-cases/sla-scan",
        ).status_code, 200)
        self._as(principal("diff-owner", "admin"))
        recomputed = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/monitoring-diff-cases/{case['id']}/recompute", json={
            "expected_row_version": assigned_row_version, "reason": "按原观察截止时间和标签定义重算",
        })
        self.assertEqual(recomputed.status_code, 200, recomputed.text)
        recomputed_case = recomputed.json()
        self.assertEqual(recomputed_case["status"], "pending_disposition")
        self.assertEqual(recomputed_case["recompute_status"], "completed")
        self.assertTrue(recomputed_case["recomputed_run_id"])
        self.assertTrue(recomputed_case["recomputed_diff_hash"])
        same_actor = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/monitoring-diff-cases/{case['id']}/dispose", json={
            "expected_row_version": recomputed_case["row_version"], "disposition": "accepted_change",
            "conclusion": "重算执行人不能自行关闭差异工单",
        })
        self.assertEqual(same_actor.status_code, 409, same_actor.text)

        self._as(principal("diff-reviewer", "risk_manager"))
        disposed = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/monitoring-diff-cases/{case['id']}/dispose", json={
            "expected_row_version": recomputed_case["row_version"], "disposition": "accepted_change",
            "conclusion": "已独立核对原差异和重算证据，确认属于可接受变化",
        })
        self.assertEqual(disposed.status_code, 200, disposed.text)
        self.assertEqual(disposed.json()["status"], "resolved")
        with database.SessionLocal() as session:
            closed_scan = TenantOutcomeRepository(session).scan_monitoring_diff_case_sla(TENANT_ID, now=scan_now)
            self.assertEqual(closed_scan["notifications_resolved"], 3)
            self.assertEqual(session.query(NotificationRecord).filter(
                NotificationRecord.category == "monitoring_diff_case_sla",
                NotificationRecord.status != "resolved",
            ).count(), 0)
        closed_queue = self.client.get("/api/v1/model-governance/risk-review-queue", params={"template_key": queue_model_key})
        self.assertFalse(any(item["diff_case_id"] == case["id"] for item in closed_queue.json()))
        reviewed = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/tenant-monitoring-runs/{second_run['id']}/review", json={
            "expected_row_version": submitted.json()["row_version"], "decision": "approve",
            "comment": "差异工单已重算并独立关闭，批准发布监控快照",
        })
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        self.assertEqual(reviewed.json()["governance_status"], "published")
        listed = self.client.get(f"/api/v1/model-governance/rollouts/{self.policy_id}/monitoring-diff-cases")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()[0]["id"], case["id"])

    def test_four_eyes_maturity_and_decision_execution_link_are_enforced(self) -> None:
        route_id = self._route("cp-future", "champion", 75)
        created = self._create(route_id, "cp-future", False, external_id="LABEL-FUTURE", future=True).json()
        self._as(principal("label-maker", "risk_manager"))
        same_actor = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/outcomes/{created['id']}/verify", json={
            "expected_row_version": created["row_version"], "decision": "verify", "note": "录入人不能自行核验结果标签",
        })
        self.assertEqual(same_actor.status_code, 409)
        verified = self._verify(created)
        self.assertEqual(verified["maturity_status"], "immature")
        self._as(principal("label-reviewer", "risk_manager"))
        evaluation = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/supervised-evaluate", json={
            "min_mature_samples": 2, "min_events": 1, "min_non_events": 1, "high_risk_threshold": 0.4,
        })
        self.assertEqual(evaluation.status_code, 201, evaluation.text)
        self.assertEqual(evaluation.json()["evidence_level"], "insufficient_maturity")
        self.assertFalse(evaluation.json()["metrics"]["supervised_metrics_available"])

        decision_route = self._route("cp-api", "challenger", 50, channel="decision_api")
        self._as(principal("label-maker", "model_admin"))
        missing_execution = self._create(decision_route, "cp-api", True, external_id="LABEL-API")
        self.assertEqual(missing_execution.status_code, 409)
        self.assertIn("Decision API", missing_execution.text)

    def test_supervised_metrics_are_derived_and_do_not_restore_rollout(self) -> None:
        samples = [
            ("champ-good", "champion", 90, False), ("champ-bad", "champion", 20, True),
            ("chall-good", "challenger", 85, False), ("chall-bad", "challenger", 10, True),
        ]
        for index, (counterparty_id, arm, score, event) in enumerate(samples):
            route_id = self._route(counterparty_id, arm, score)
            label = self._create(route_id, counterparty_id, event, external_id=f"LABEL-{index}")
            self.assertEqual(label.status_code, 201, label.text)
            self._verify(label.json())
        self._as(principal("label-reviewer", "risk_manager"))
        response = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/supervised-evaluate", json={
            "min_mature_samples": 4, "min_events": 1, "min_non_events": 1, "high_risk_threshold": 0.4,
        })
        self.assertEqual(response.status_code, 201, response.text)
        result = response.json()
        self.assertEqual(result["evidence_level"], "supervised")
        self.assertEqual(result["metrics"]["champion"]["auc"], 1.0)
        self.assertEqual(result["metrics"]["challenger"]["ks"], 1.0)
        self.assertEqual(result["metrics"]["champion"]["auc_confidence_interval"]["method"], "stratified_bootstrap_percentile")
        self.assertEqual(result["metrics"]["champion"]["bootstrap_resamples"], 1000)
        self.assertIn(result["metrics"]["comparison"]["auc_difference_signal"], {"directional_only", "significant_challenger_better", "significant_champion_better"})
        self.assertEqual(result["metrics"]["champion"]["segment_stability"]["fairness_audit"], "not_evaluable")
        self.assertEqual(result["metrics"]["champion"]["stability_trend"]["direction"], "insufficient_periods")
        self.assertEqual(result["metrics"]["champion"]["confusion_matrix"], {
            "true_positive": 1, "false_positive": 0, "true_negative": 1, "false_negative": 0, "threshold": 0.4,
        })
        self.assertTrue(result["metrics"]["champion"]["segments"])
        with database.SessionLocal() as session:
            self.assertEqual(session.get(TenantRolloutPolicyRecord, self.policy_id).status, "rolled_back")

    def test_evaluation_rejects_drifted_routing_evidence(self) -> None:
        route_id = self._route("cp-drift", "champion", 80)
        label = self._create(route_id, "cp-drift", False, external_id="LABEL-DRIFT").json()
        self._verify(label)
        with database.SessionLocal() as session:
            route = session.get(TenantRoutingDecisionRecord, route_id)
            route.score = 10
            session.commit()
        self._as(principal("label-reviewer", "risk_manager"))
        response = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/supervised-evaluate", json={})
        self.assertEqual(response.status_code, 409)
        self.assertIn("历史预测结果发生变化", response.text)

    def test_batch_import_reconciles_rows_and_is_idempotent(self) -> None:
        route_ok = self._route("cp-batch-ok", "champion", 82)
        route_bad = self._route("cp-batch-bad", "challenger", 48)
        observed_at = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
        payload = {
            "import_key": "POSTLOAN-2026Q3-001",
            "source": "贷后结果仓",
            "label_definition_id": self.definition_id,
            "expected_count": 3,
            "outcomes": [
                {
                    "external_label_id": "BATCH-LABEL-001",
                    "routing_decision_id": route_ok,
                    "counterparty_id": "cp-batch-ok",
                    "observed_event": False,
                    "observation_end": observed_at,
                    "loss_amount": 0,
                    "exposure_amount": 1000,
                    "evidence_reference": "s3://outcomes/batch-001.json",
                },
                {
                    "external_label_id": "BATCH-LABEL-002",
                    "routing_decision_id": route_bad,
                    "counterparty_id": "wrong-counterparty",
                    "observed_event": True,
                    "observation_end": observed_at,
                    "loss_amount": 100,
                    "exposure_amount": 1000,
                    "evidence_reference": "s3://outcomes/batch-002.json",
                },
            ],
        }
        response = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/outcome-imports", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        imported = response.json()
        self.assertEqual(imported["status"], "completed_with_exceptions")
        self.assertEqual((imported["received_count"], imported["created_count"], imported["rejected_count"]), (2, 1, 1))
        self.assertEqual(imported["results"][0]["status"], "created")
        self.assertEqual(imported["results"][1]["error_code"], "OUTCOME_COUNTERPARTY_MISMATCH")

        repeated = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/outcome-imports", json=payload)
        self.assertEqual(repeated.status_code, 201, repeated.text)
        self.assertTrue(repeated.json()["idempotent"])
        conflict = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/outcome-imports", json={**payload, "expected_count": 2})
        self.assertEqual(conflict.status_code, 409)
        labels = self.client.get(f"/api/v1/model-governance/rollouts/{self.policy_id}/outcomes").json()
        self.assertEqual(len(labels), 1)
        self.assertEqual(labels[0]["import_batch_id"], imported["id"])

        self._as(principal("other-maker", "model_admin", "tenant-demo-alt"))
        cross_tenant = self.client.get(f"/api/v1/model-governance/rollouts/{self.policy_id}/outcome-imports")
        self.assertEqual(cross_tenant.status_code, 404)

    def test_correction_preserves_history_and_replaces_active_sample(self) -> None:
        route_id = self._route("cp-correct", "champion", 78)
        original = self._create(route_id, "cp-correct", False, external_id="LABEL-CORRECT-ORIGINAL").json()
        original = self._verify(original)
        self._as(principal("evaluation-maker", "risk_manager"))
        before = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/supervised-evaluate", json={
            "min_mature_samples": 2, "min_events": 1, "min_non_events": 1, "high_risk_threshold": 0.4,
        }).json()
        self.assertEqual(before["label_watermark"]["label_ids"], [original["id"]])

        self._as(principal("label-corrector", "model_admin"))
        corrected_response = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/outcomes/{original['id']}/correct", json={
            "expected_row_version": original["row_version"],
            "external_label_id": "LABEL-CORRECT-REPLACEMENT",
            "observed_event": True,
            "observation_end": (datetime.now(timezone.utc) - timedelta(days=15)).isoformat(),
            "loss_amount": 250,
            "exposure_amount": 1000,
            "evidence_reference": "s3://outcomes/corrected.json",
            "reason": "贷后系统确认原标签漏记逾期事件，按复核工单完成冲正",
        })
        self.assertEqual(corrected_response.status_code, 201, corrected_response.text)
        corrected = corrected_response.json()
        self.assertEqual(corrected["verification_status"], "pending_verification")
        self.assertEqual(corrected["supersedes_label_id"], original["id"])
        rows = self.client.get(f"/api/v1/model-governance/rollouts/{self.policy_id}/outcomes").json()
        original_view = next(item for item in rows if item["id"] == original["id"])
        self.assertEqual(original_view["record_status"], "superseded")
        self.assertEqual(original_view["superseded_by_label_id"], corrected["id"])

        corrected = self._verify(corrected)
        self._as(principal("evaluation-maker", "risk_manager"))
        after = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/supervised-evaluate", json={
            "min_mature_samples": 2, "min_events": 1, "min_non_events": 1, "high_risk_threshold": 0.4,
        }).json()
        self.assertEqual(after["coverage"]["superseded_count"], 1)
        self.assertEqual(after["label_watermark"]["label_ids"], [corrected["id"]])
        evaluations = self.client.get(f"/api/v1/model-governance/rollouts/{self.policy_id}/supervised-evaluations").json()
        historical = next(item for item in evaluations if item["id"] == before["id"])
        self.assertEqual(historical["label_watermark"]["label_ids"], [original["id"]])

    def test_supervised_review_requires_evidence_and_four_eyes_without_restoring_policy(self) -> None:
        samples = [
            ("review-cg", "champion", 90, False), ("review-cb", "champion", 20, True),
            ("review-ng", "challenger", 88, False), ("review-nb", "challenger", 15, True),
        ]
        for index, (counterparty_id, arm, score, event) in enumerate(samples):
            label = self._create(self._route(counterparty_id, arm, score), counterparty_id, event, external_id=f"REVIEW-{index}").json()
            self._verify(label)

        self._as(principal("evaluation-maker", "risk_manager"))
        evaluation = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/supervised-evaluate", json={
            "min_mature_samples": 4, "min_events": 1, "min_non_events": 1, "high_risk_threshold": 0.4,
        }).json()
        self.assertEqual(evaluation["status"], "draft")
        submitted = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/supervised-evaluations/{evaluation['id']}/submit", json={
            "expected_row_version": evaluation["row_version"], "note": "监督指标及标签水位已核对，提交独立审批",
        })
        self.assertEqual(submitted.status_code, 200, submitted.text)
        submitted_data = submitted.json()
        same_actor = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/supervised-evaluations/{evaluation['id']}/review", json={
            "expected_row_version": submitted_data["row_version"], "decision": "approve",
            "governance_decision": "promote_candidate", "comment": "创建人不能审批自己的监督结论",
        })
        self.assertEqual(same_actor.status_code, 409)

        self._as(principal("other-reviewer", "risk_manager", "tenant-demo-alt"))
        cross_tenant = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/supervised-evaluations/{evaluation['id']}/review", json={
            "expected_row_version": submitted_data["row_version"], "decision": "approve",
            "governance_decision": "promote_candidate", "comment": "其他租户不能查看或审批该监督结论",
        })
        self.assertEqual(cross_tenant.status_code, 404)

        self._as(principal("independent-reviewer", "risk_manager"))
        approved = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/supervised-evaluations/{evaluation['id']}/review", json={
            "expected_row_version": submitted_data["row_version"], "decision": "approve",
            "governance_decision": "promote_candidate", "comment": "已独立复核标签来源、样本门槛及双模型区分度",
        })
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(approved.json()["status"], "approved")
        self.assertEqual(approved.json()["governance_decision"], "promote_candidate")
        self._assert_reacceptance_uses_tenant_evaluation(approved.json())
        with database.SessionLocal() as session:
            self.assertEqual(session.get(TenantRolloutPolicyRecord, self.policy_id).status, "rolled_back")

        degraded = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/supervised-evaluate", json={
            "min_mature_samples": 100, "min_events": 10, "min_non_events": 10, "high_risk_threshold": 0.4,
        }).json()
        blocked = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/supervised-evaluations/{degraded['id']}/submit", json={
            "expected_row_version": degraded["row_version"], "note": "尝试提交样本不足的降级监督证据",
        })
        self.assertEqual(blocked.status_code, 422)

    def _assert_reacceptance_uses_tenant_evaluation(self, evaluation: dict) -> None:
        with database.SessionLocal() as session:
            repository = ModelRiskPolicyRepository(session)
            policy = repository.create_policy(TENANT_ID, {
                "name": "租户在役监督政策", "description": "冻结租户监督标签血缘",
                "levels": risk_catalog(), "reason": "测试在役再接受租户证据隔离",
            }, "policy-maker", "政策制作者")
            submitted = repository.submit_policy(TENANT_ID, policy["id"], policy["row_version"], "提交独立复核", "policy-maker")
            repository.review_policy(TENANT_ID, policy["id"], submitted["row_version"], "publish", "批准租户风险政策", "policy-reviewer", "政策复核人")
            rollout = session.get(TenantRolloutPolicyRecord, self.policy_id)
            evidence = {
                "tenant_id": TENANT_ID, "evaluation_id": evaluation["id"], "report_hash": "r" * 64,
                "report_template_version": "supervised-model-validation-v2", "evidence_level": "supervised",
                "independent_validation": {"status": "approved", "risk_level": "low", "attachments": []},
            }
            change = ModelChangeRecord(
                id=str(uuid4()), template_key=rollout.champion_model_key, base_version="previous",
                candidate_version=rollout.champion_model_version, status="draft", config_json={},
                validation_json={"config_hash": "c" * 64}, impact_json={}, comparison_evidence_json={},
                change_reason="租户监督评估绑定测试", created_by="maker", created_by_name="制作者",
                entity_type="model", supervised_validation_evidence_json=evidence,
                supervised_validation_binding_hash=content_hash(evidence),
            )
            session.add(change)
            session.commit()
            accepted = repository.create_acceptance(TENANT_ID, change.id, "同意在役监督验证模型边界", "maker", "制作者")
            accepted = repository.accept(TENANT_ID, accepted["id"], accepted["row_version"], "model_owner", "确认该模型低风险使用边界", "owner", "模型所有者", ("model_admin",))
            change.status = "published"
            release = ModelReleaseRecord(
                id=str(uuid4()), template_key=rollout.champion_model_key, model_version=rollout.champion_model_version,
                config_json={}, config_hash="c" * 64, source_change_id=change.id, is_active=True, published_by="reviewer",
            )
            session.add(release)
            session.get(ModelRiskAcceptanceRecord, accepted["id"]).review_due_at = datetime.now(timezone.utc) - timedelta(days=1)
            session.commit()
            payload = {
                "rationale": "租户结果标签与灰度资产已独立复核", "observed_from": datetime.now(timezone.utc).date() - timedelta(days=120),
                "observed_to": datetime.now(timezone.utc).date(), "evidence_reference": "tenant-supervised-evaluation",
                "evidence_summary": "同租户成熟结果标签及模型冻结版本已通过独立审批和完整性复核。",
                "supervised_evaluation_id": evaluation["id"], "supervised_evidence_hash": evaluation["evidence_hash"],
            }
            with self.assertRaisesRegex(ModelRiskPolicyError, "当前租户"):
                repository._supervised_binding("tenant-demo-alt", release, payload)
            with self.assertRaisesRegex(ModelRiskPolicyError, "哈希不匹配"):
                repository.create_reacceptance(TENANT_ID, release.id, {**payload, "supervised_evidence_hash": "0" * 64}, "maker", "制作者")
            with self.assertRaisesRegex(ModelRiskPolicyError, "冻结模型"):
                repository._supervised_binding(TENANT_ID, SimpleNamespace(template_key=release.template_key, model_version="unrelated"), payload)
            created = repository.create_reacceptance(TENANT_ID, release.id, payload, "maker", "制作者")
            self.assertEqual(created["operational_evidence"]["supervised_binding"]["label_definition_id"], self.definition_id)
            signed = repository.accept_reacceptance(TENANT_ID, created["id"], created["row_version"], "model_owner", "确认标签血缘及运行边界", "owner-2", "模型所有者乙", ("model_admin",))
            self.assertEqual(signed["effective_status"], "accepted")
            self.assertEqual(repository.audit_package(TENANT_ID, signed["id"])["supervised_evaluation"]["evidence_hash"], evaluation["evidence_hash"])
            label = session.get(TenantOutcomeLabelRecord, evaluation["label_watermark"]["label_ids"][0])
            label.observed_event = not label.observed_event
            session.commit()
            self.assertEqual(repository.in_service_release_status(TENANT_ID, release.id)["effective_status"], "evidence_stale")
            label.observed_event = not label.observed_event
            session.commit()
            self.assertEqual(repository.in_service_release_status(TENANT_ID, release.id)["effective_status"], "accepted")
            definition = session.get(TenantOutcomeLabelDefinitionRecord, self.definition_id)
            original_hash = definition.config_hash
            definition.config_hash = "0" * 64
            session.commit()
            self.assertEqual(repository.in_service_release_status(TENANT_ID, release.id)["effective_status"], "evidence_stale")
            definition.config_hash = original_hash
            session.commit()
            session.get(TenantSupervisedEvaluationRecord, evaluation["id"]).metrics_json = {"tampered": True}
            session.commit()
            self.assertEqual(repository.in_service_release_status(TENANT_ID, release.id)["effective_status"], "evidence_stale")

    def test_label_definition_versions_require_four_eyes_and_retire_previous_release(self) -> None:
        payload = {
            "code": "loss_120d", "name": "120 天损失确认口径",
            "description": "用于确认企业授信敞口在完整观察期内形成的实际损失。",
            "event_type": "loss", "event_threshold": {"minimum_loss_amount": 1},
            "observation_window_days": 120, "maturity_grace_days": 5,
            "source_priorities": [{"source": "贷后结果仓", "priority": 1}],
            "applicable_model_keys": ["general"],
            "require_loss_amount": True, "require_exposure_amount": True,
        }
        created = self.client.post("/api/v1/model-governance/outcome-label-definitions", json=payload)
        self.assertEqual(created.status_code, 201, created.text)
        definition = created.json()
        submitted = self.client.post(f"/api/v1/model-governance/outcome-label-definitions/{definition['id']}/submit", json={
            "expected_row_version": definition["row_version"], "note": "提交标准损失口径进行独立复核",
        })
        self.assertEqual(submitted.status_code, 200, submitted.text)
        self._as(principal("label-maker", "risk_manager"))
        same_actor = self.client.post(f"/api/v1/model-governance/outcome-label-definitions/{definition['id']}/review", json={
            "expected_row_version": submitted.json()["row_version"], "decision": "approve", "comment": "创建人不能审批自己的口径",
        })
        self.assertEqual(same_actor.status_code, 409)
        self._as(principal("definition-reviewer", "risk_manager"))
        approved = self.client.post(f"/api/v1/model-governance/outcome-label-definitions/{definition['id']}/review", json={
            "expected_row_version": submitted.json()["row_version"], "decision": "approve", "comment": "来源、观察期与金额字段要求已独立复核",
        })
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertTrue(approved.json()["is_active"])

        self._as(principal("definition-maker-v2", "model_admin"))
        v2 = self.client.post("/api/v1/model-governance/outcome-label-definitions", json={**payload, "description": "第二版损失口径，补充贷后核销确认要求。"}).json()
        v2 = self.client.post(f"/api/v1/model-governance/outcome-label-definitions/{v2['id']}/submit", json={
            "expected_row_version": v2["row_version"], "note": "提交第二版口径",
        }).json()
        self._as(principal("definition-reviewer-v2", "risk_manager"))
        v2 = self.client.post(f"/api/v1/model-governance/outcome-label-definitions/{v2['id']}/review", json={
            "expected_row_version": v2["row_version"], "decision": "approve", "comment": "第二版口径已完成独立复核",
        }).json()
        rows = self.client.get("/api/v1/model-governance/outcome-label-definitions").json()
        previous = next(item for item in rows if item["id"] == definition["id"])
        self.assertEqual((previous["status"], previous["is_active"]), ("retired", False))
        self.assertEqual((v2["version"], v2["status"], v2["is_active"]), (2, "published", True))

    def test_approved_reliable_promotion_creates_one_draft_without_changing_traffic(self) -> None:
        samples = [
            ("promote-cg", "champion", 90, False), ("promote-cb", "champion", 20, True),
            ("promote-ng", "challenger", 92, False), ("promote-nb", "challenger", 10, True),
        ]
        for index, (counterparty_id, arm, score, event) in enumerate(samples):
            label = self._create(self._route(counterparty_id, arm, score), counterparty_id, event, external_id=f"PROMOTE-{index}").json()
            self._verify(label)
        self._as(principal("promotion-evaluator", "risk_manager"))
        evaluation_response = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/supervised-evaluate", json={
            "label_definition_id": self.definition_id,
            "min_mature_samples": 4, "min_events": 1, "min_non_events": 1,
            "min_reliable_samples_per_arm": 2, "high_risk_threshold": 0.4,
        })
        self.assertEqual(evaluation_response.status_code, 201, evaluation_response.text)
        evaluation = evaluation_response.json()
        self.assertEqual(evaluation["metrics"]["comparison"]["promotion_readiness"], "ready")
        self.assertEqual(evaluation["metrics"]["champion"]["total_exposure_amount"], 2000)
        submitted = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/supervised-evaluations/{evaluation['id']}/submit", json={
            "expected_row_version": evaluation["row_version"], "note": "可靠性及损失证据已核对",
        }).json()
        self._as(principal("promotion-reviewer", "risk_manager"))
        approved_response = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/supervised-evaluations/{evaluation['id']}/review", json={
            "expected_row_version": submitted["row_version"], "decision": "approve",
            "governance_decision": "promote_candidate", "comment": "批准形成候选模型变更草稿，不自动发布或切流",
        })
        self.assertEqual(approved_response.status_code, 200, approved_response.text)
        approved = approved_response.json()
        self._as(principal("promotion-draft-maker", "model_admin"))
        draft_response = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/supervised-evaluations/{evaluation['id']}/create-change-draft", json={
            "expected_evidence_hash": approved["evidence_hash"],
            "change_reason": "基于已批准的延迟监督证据生成 Challenger 晋级候选草稿",
        })
        self.assertEqual(draft_response.status_code, 201, draft_response.text)
        draft = draft_response.json()
        self.assertEqual(draft["model_change"]["status"], "draft")
        self.assertFalse(draft["auto_submitted"])
        self.assertFalse(draft["auto_published"])
        self.assertFalse(draft["traffic_changed"])
        supervised_binding = draft["model_change"]["supervised_validation_evidence"]
        self.assertEqual(supervised_binding["independent_validation"]["status"], "pending")
        self._as(principal("independent-model-validator", "risk_manager"))
        validation_review = self.client.post(f"/api/v1/model-governance/changes/{draft['model_change_id']}/supervised-validation/review", json={
            "expected_row_version": draft["model_change"]["row_version"],
            "expected_binding_hash": supervised_binding["binding_hash"],
            "decision": "approve", "risk_level": "medium",
            "opinion": "监督样本口径、区间和候选资产已完成独立核验，允许进入发布审批。",
            "report_template_version": "supervised-model-validation-v2", "attachments": [],
        })
        self.assertEqual(validation_review.status_code, 200, validation_review.text)
        self.assertEqual(validation_review.json()["supervised_validation_evidence"]["independent_validation"]["status"], "approved")
        self._as(principal("promotion-draft-maker", "model_admin"))
        repeated = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/supervised-evaluations/{evaluation['id']}/create-change-draft", json={
            "expected_evidence_hash": approved["evidence_hash"],
            "change_reason": "重复请求应返回同一模型变更草稿",
        })
        self.assertEqual(repeated.status_code, 201, repeated.text)
        self.assertTrue(repeated.json()["idempotent"])
        self.assertEqual(repeated.json()["model_change_id"], draft["model_change_id"])
        with database.SessionLocal() as session:
            self.assertEqual(session.get(TenantRolloutPolicyRecord, self.policy_id).status, "rolled_back")

    def test_csv_import_and_verification_report_are_bounded_and_repeatable(self) -> None:
        route_a = self._route("csv-champion", "champion", 90)
        route_b = self._route("csv-challenger", "challenger", 10)
        observed_at = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        csv_text = "external_label_id,routing_decision_id,counterparty_id,observed_event,observation_end,loss_amount,exposure_amount,evidence_reference\n"
        csv_text += f"CSV-LABEL-1,{route_a},csv-champion,false,{observed_at},0,1000,post-loan://csv/1\n"
        csv_text += f"CSV-LABEL-2,{route_b},csv-challenger,true,{observed_at},100,1000,post-loan://csv/2\n"
        response = self.client.post(
            f"/api/v1/model-governance/rollouts/{self.policy_id}/outcome-imports/csv",
            data={"import_key": "CSV-2026Q3-001", "source": "贷后结果仓", "label_definition_id": self.definition_id, "expected_count": "2"},
            files={"file": ("outcomes.csv", csv_text.encode("utf-8"), "text/csv")},
        )
        self.assertEqual(response.status_code, 201, response.text)
        imported = response.json()
        self.assertEqual(imported["file"]["row_count"], 2)
        self.assertEqual(imported["file"]["byte_count"], len(csv_text.encode("utf-8")))
        self.assertEqual(imported["created_count"], 2)
        repeated = self.client.post(
            f"/api/v1/model-governance/rollouts/{self.policy_id}/outcome-imports/csv",
            data={"import_key": "CSV-2026Q3-001", "source": "贷后结果仓", "label_definition_id": self.definition_id, "expected_count": "2"},
            files={"file": ("outcomes.csv", csv_text.encode("utf-8"), "text/csv")},
        )
        self.assertEqual(repeated.status_code, 201, repeated.text)
        self.assertTrue(repeated.json()["idempotent"])
        invalid = self.client.post(
            f"/api/v1/model-governance/rollouts/{self.policy_id}/outcome-imports/csv",
            data={"import_key": "CSV-INVALID", "source": "贷后结果仓", "label_definition_id": self.definition_id, "expected_count": "1"},
            files={"file": ("invalid.csv", b"counterparty_id\ncp-1\n", "text/csv")},
        )
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(invalid.json()["detail"]["code"], "OUTCOME_CSV_HEADER_INVALID")
        self._as(principal("csv-reviewer", "risk_manager"))
        labels = self.client.get(f"/api/v1/model-governance/rollouts/{self.policy_id}/outcomes").json()
        for label in labels:
            verified = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/outcomes/{label['id']}/verify", json={
                "expected_row_version": label["row_version"], "decision": "verify", "note": "CSV 来源与历史路由已独立核验",
            })
            self.assertEqual(verified.status_code, 200, verified.text)
        evaluation_response = self.client.post(f"/api/v1/model-governance/rollouts/{self.policy_id}/supervised-evaluate", json={
            "label_definition_id": self.definition_id, "min_mature_samples": 2, "min_events": 1, "min_non_events": 1,
            "min_reliable_samples_per_arm": 2, "high_risk_threshold": 0.4,
        })
        self.assertEqual(evaluation_response.status_code, 201, evaluation_response.text)
        evaluation = evaluation_response.json()
        report = self.client.get(f"/api/v1/model-governance/rollouts/{self.policy_id}/supervised-evaluations/{evaluation['id']}/verification-report")
        self.assertEqual(report.status_code, 200, report.text)
        report_json = report.json()
        repeated_report = self.client.get(f"/api/v1/model-governance/rollouts/{self.policy_id}/supervised-evaluations/{evaluation['id']}/verification-report")
        self.assertEqual(repeated_report.status_code, 200, repeated_report.text)
        self.assertEqual(report_json["report_hash"], repeated_report.json()["report_hash"])
        self.assertEqual(report_json["evaluation"]["evidence_hash"], evaluation["evidence_hash"])
        csv_report = self.client.get(f"/api/v1/model-governance/rollouts/{self.policy_id}/supervised-evaluations/{evaluation['id']}/verification-report.csv")
        self.assertEqual(csv_report.status_code, 200, csv_report.text)
        self.assertTrue(csv_report.content.startswith(b"\xef\xbb\xbfmetric,value"))
        self.assertIn("attachment", csv_report.headers.get("content-disposition", ""))
        self.assertIn(b"comparison.auc_difference_signal", csv_report.content)


if __name__ == "__main__":
    unittest.main()
