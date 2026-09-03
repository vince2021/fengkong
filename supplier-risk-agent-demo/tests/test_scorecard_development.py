from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient

import backend.database as database
from backend.database import Base
from backend.db_models import AuditEventRecord, ModelChangeRecord, NotificationRecord, RuleCenterReplayDataset, RuleCenterReplayDatasetSnapshot, ScorecardDefinition, ScorecardDevelopmentRun, ScorecardMonitoringSavedView, ScorecardMonitoringSchedulerLease, ScorecardMonitoringSchedulerRun, ScorecardMonitoringSlaPolicy, ScorecardValidationMonitoringEvent, ScorecardValidationMonitoringPlan, ScorecardValidationPolicy
from backend.main import app
from backend.repository import ConcurrentUpdateError, RuleCenterReplayDatasetRepository
from backend.scorecard_repository import ScorecardRepository
from backend.scorecard_development import DEFAULT_VALIDATION_THRESHOLDS
from backend.sla_monitor import build_personal_task_queue
from tests.database_support import IsolatedTestDatabase
from tests.test_scorecard_center import scorecard


class TestScorecardDevelopment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = IsolatedTestDatabase()
        cls.db.start()

    @classmethod
    def tearDownClass(cls):
        cls.db.stop()

    def setUp(self):
        Base.metadata.create_all(self.db.engine)
        self.session = database.SessionLocal()
        for model in [NotificationRecord, ScorecardMonitoringSchedulerRun, ScorecardMonitoringSchedulerLease, ScorecardValidationMonitoringEvent, ScorecardMonitoringSavedView, ScorecardMonitoringSlaPolicy, ScorecardValidationMonitoringPlan, ScorecardDevelopmentRun, ScorecardValidationPolicy, ScorecardDefinition, RuleCenterReplayDatasetSnapshot, RuleCenterReplayDataset, ModelChangeRecord, AuditEventRecord]:
            self.session.query(model).delete()
        self.session.commit()
        scorecards = ScorecardRepository(self.session)
        draft = scorecards.create_draft(scorecard("DEV_SCORE"), "建立开发验证评分卡", "maker", "模型管理员")
        submitted = scorecards.submit(draft["id"], draft["row_version"], "maker", False)
        scorecards.review(submitted["id"], submitted["row_version"], "publish", "独立复核通过", "reviewer", "风控经理")
        self.asset = scorecards.list_assets()[0]

    def tearDown(self):
        self.session.close()

    def _snapshot(self, labeled: bool = True, code: str = "SC_DEV", id_prefix: str = "sample", shift: bool = False) -> dict:
        repository = RuleCenterReplayDatasetRepository(self.session)
        dataset = repository.create_dataset(code, "评分卡开发样本", "脱敏历史表现样本", "maker", "模型管理员")
        records = []
        for index in range(8):
            event = index >= 4
            record = {
                "id": f"{id_prefix}-{index}", "name": f"样本 {index}", "counterparty_type": "supplier",
                "enterprise_risk": {"shareholder_change": 2 if event or shift and index >= 2 else 0},
                "region": "east" if index in {0, 1, 4, 5} else "west",
                "observed_at": f"2026-01-{index + 1:02d}",
                "predicted_pd": 0.8 if event else 0.2,
            }
            if labeled:
                record["outcome"] = "bad" if event else "good"
            records.append(record)
        return repository.import_snapshot(dataset["id"], {
            "source_name": "历史表现样本", "schema_version": "1.0", "as_of_date": date(2026, 6, 30),
            "evidence_reference": "test://scorecard-development", "data_classification": "synthetic",
            "field_mapping": {}, "label_field": "outcome" if labeled else None,
            "observed_at_field": "observed_at", "records": records,
        }, "maker", "模型管理员")

    def _payload(self, snapshot: dict) -> dict:
        return {
            "scorecard_asset_id": self.asset["id"], "dataset_snapshot_id": snapshot["id"],
            "positive_labels": ["bad"], "observation_start": date(2026, 1, 1),
            "observation_end": date(2026, 3, 31), "performance_window_days": 90, "maturity_days": 30,
            "min_sample_count": 8, "min_event_count": 4, "min_non_event_count": 4,
            "exclusion_rules": [],
        }

    def _policy(self, code: str = "INSTITUTION_STANDARD", *, is_default: bool = True, applicable: list[str] | None = None) -> dict:
        return {
            "code": code, "name": "机构标准验证策略", "description": "统一约束评分卡开发验证的最低上线标准",
            "applicable_scorecard_codes": applicable or [], "is_default": is_default,
            "thresholds": {**DEFAULT_VALIDATION_THRESHOLDS, "require_validation_snapshot": True, "require_oot_snapshot": True, "min_auc": 0.75},
        }

    def _publish_policy(self, payload: dict | None = None) -> dict:
        repository = ScorecardRepository(self.session)
        draft = repository.create_validation_policy(payload or self._policy(), "建立机构统一验证门槛", "maker", "模型管理员")
        submitted = repository.submit_validation_policy(draft["id"], draft["row_version"], "maker", False)
        return repository.review_validation_policy(submitted["id"], submitted["row_version"], "publish", "独立复核确认机构门槛适用", "reviewer", "风控经理")

    def _publish_sla_policy(self, *, code: str = "MONITORING_SLA_STANDARD", critical_hours: int = 24, warning_hours: int = 72, is_default: bool = True, scorecards: list[str] | None = None, event_types: list[str] | None = None) -> dict:
        repository = ScorecardRepository(self.session)
        payload = {
            "code": code, "name": "持续验证预警 SLA", "description": "统一约束持续验证预警的响应、临期和升级窗口",
            "applicable_scorecard_codes": scorecards or [], "applicable_event_types": event_types or [], "is_default": is_default,
            "severity_rules": {
                "critical": {"response_hours": critical_hours, "due_soon_ratio": 0.25, "escalation_after_hours": 3},
                "warning": {"response_hours": warning_hours, "due_soon_ratio": 0.2, "escalation_after_hours": 6},
            },
        }
        draft = repository.create_monitoring_sla_policy(payload, "建立持续验证预警分级 SLA", "maker", "模型管理员")
        submitted = repository.submit_monitoring_sla_policy(draft["id"], draft["row_version"], "maker", False)
        return repository.review_monitoring_sla_policy(submitted["id"], submitted["row_version"], "publish", "独立确认响应时限与升级窗口", "reviewer", "风控经理")

    def _monitoring_plan(self, policy: dict, training: dict, validation: dict | None = None, oot: dict | None = None, *, code: str = "DEV_SCORE_MONTHLY", next_run_at: datetime | None = None) -> dict:
        return {
            "code": code, "name": "开发评分卡月度持续验证", "description": "固定评分卡与机构策略并按数据集最新截面持续验证",
            "scorecard_asset_id": self.asset["id"], "validation_policy_id": policy["id"],
            "training_dataset_id": training["dataset_id"],
            "validation_dataset_id": validation["dataset_id"] if validation else None,
            "oot_dataset_id": oot["dataset_id"] if oot else None,
            "run_config": {
                "subject_id_field": "id", "predicted_probability_field": "predicted_pd", "segment_fields": ["region"],
                "sensitive_attribute_fields": [], "min_segment_sample_count": 2, "classification_threshold": 0.5,
                "positive_labels": ["bad"], "performance_window_days": 90, "maturity_days": 30,
                "min_sample_count": 8, "min_event_count": 4, "min_non_event_count": 4, "exclusion_rules": [],
            },
            "cadence": "monthly", "timezone_name": "Asia/Shanghai", "enabled": True,
            "next_run_at": next_run_at or datetime(2026, 9, 30, tzinfo=timezone.utc), "owner": "model-risk-owner",
        }

    def _operational_events(self) -> tuple[ScorecardRepository, dict, list[dict]]:
        repository = ScorecardRepository(self.session)
        policy = self._publish_policy()
        training = self._snapshot(code="MON_OPS", id_prefix="mon-ops")
        plan = repository.create_monitoring_plan(self._monitoring_plan(policy, training, code="MON_OPS_PLAN"), "maker")
        events = repository.run_monitoring_plan(plan["id"], plan["row_version"], "maker", "模型管理员")["events"]
        self.assertGreaterEqual(len(events), 2)
        return repository, plan, events

    def test_monitoring_plan_uses_latest_snapshots_and_due_tick_is_idempotent(self):
        repository = ScorecardRepository(self.session)
        policy = self._publish_policy()
        training = self._snapshot(code="MON_TRAIN", id_prefix="mon-train")
        validation = self._snapshot(code="MON_VALID", id_prefix="mon-valid")
        oot = self._snapshot(code="MON_OOT", id_prefix="mon-oot")
        plan = repository.create_monitoring_plan(self._monitoring_plan(policy, training, validation, oot, next_run_at=datetime(2026, 8, 31, tzinfo=timezone.utc)), "maker")
        self.assertTrue(plan["next_run_at"].endswith("+00:00"))

        tick = repository.run_due_monitoring_plans(datetime(2026, 9, 1, tzinfo=timezone.utc), 20, "maker", "模型管理员")
        self.assertEqual(tick["due_count"], 1)
        self.assertEqual(tick["completed_count"], 1)
        self.assertEqual(tick["results"][0]["run"]["dataset_snapshot_id"], training["id"])
        self.assertEqual(tick["results"][0]["run"]["validation_snapshot_id"], validation["id"])
        self.assertEqual(tick["results"][0]["run"]["oot_snapshot_id"], oot["id"])
        self.assertEqual(tick["results"][0]["plan"]["scorecard"]["version"], 1)
        self.assertEqual(tick["results"][0]["plan"]["validation_policy"]["version"], 1)
        self.assertGreater(tick["results"][0]["plan"]["next_run_at"], plan["next_run_at"])
        repeated = repository.run_due_monitoring_plans(datetime(2026, 9, 1, tzinfo=timezone.utc), 20, "maker", "模型管理员")
        self.assertEqual(repeated["due_count"], 0)
        self.assertEqual(self.session.query(ScorecardDevelopmentRun).count(), 1)

    def test_monitoring_scheduler_lease_idempotency_heartbeat_and_health(self):
        repository = ScorecardRepository(self.session)
        policy = self._publish_policy()
        training = self._snapshot(code="SCHED_TRAIN", id_prefix="sched-train")
        validation = self._snapshot(code="SCHED_VALID", id_prefix="sched-valid")
        oot = self._snapshot(code="SCHED_OOT", id_prefix="sched-oot")
        repository.create_monitoring_plan(self._monitoring_plan(
            policy, training, validation, oot, code="SCHED_MONTHLY",
            next_run_at=datetime(2026, 8, 31, tzinfo=timezone.utc),
        ), "maker")

        result = repository.run_monitoring_scheduler(
            datetime(2026, 9, 1, tzinfo=timezone.utc), 20, "scheduler", "持续验证调度器",
            run_key="scorecard-monitoring:test-window", trigger_type="scheduler",
        )
        self.assertEqual(result["run"]["status"], "completed")
        self.assertEqual(result["run"]["due_count"], 1)
        self.assertEqual(result["run"]["completed_count"], 1)
        self.assertEqual(result["run"]["backlog_before"], 1)
        self.assertEqual(result["run"]["backlog_after"], 0)
        self.assertGreaterEqual(result["run"]["progress"]["completed"], 1)
        self.assertEqual(repository.monitoring_scheduler_health()["lease"]["status"], "idle")

        repeated = repository.run_monitoring_scheduler(
            datetime(2026, 9, 1, tzinfo=timezone.utc), 20, "other", "另一实例",
            run_key="scorecard-monitoring:test-window", trigger_type="scheduler",
        )
        self.assertTrue(repeated["deduplicated"])
        self.assertEqual(self.session.query(ScorecardMonitoringSchedulerRun).count(), 1)
        health = repository.monitoring_scheduler_health()
        self.assertEqual(health["scheduler"]["last_status"], "completed")
        self.assertEqual(health["summary"]["completed"], 1)

    def test_monitoring_scheduler_busy_lease_skips_second_instance(self):
        repository = ScorecardRepository(self.session)
        now = datetime.now(timezone.utc)
        self.session.add(ScorecardMonitoringSchedulerLease(
            lease_key=repository.MONITORING_SCHEDULER_LEASE_KEY,
            execution_id="active-execution", run_key="scorecard-monitoring:active", actor="instance-a",
            trigger_type="scheduler", acquired_at=now, expires_at=now + timedelta(minutes=10),
            last_heartbeat_at=now, heartbeat_count=2,
        ))
        self.session.commit()

        result = repository.run_monitoring_scheduler(
            now, 20, "instance-b", "另一实例", run_key="scorecard-monitoring:blocked", trigger_type="scheduler",
        )
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["skip_reason"], "scheduler_busy")
        self.assertEqual(result["active_lease"]["actor"], "instance-a")
        self.assertEqual(self.session.query(ScorecardMonitoringSchedulerRun).count(), 0)

    def test_monitoring_scheduler_retries_to_dead_letter_and_supports_manual_recovery(self):
        repository = ScorecardRepository(self.session)
        policy = self._publish_policy()
        empty_dataset = RuleCenterReplayDatasetRepository(self.session).create_dataset(
            "SCHED_EMPTY", "尚无快照的数据集", "用于验证调度失败恢复", "maker", "模型管理员"
        )
        due_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        repository.create_monitoring_plan(self._monitoring_plan(
            policy, {"dataset_id": empty_dataset["id"]}, code="SCHED_FAILURE", next_run_at=due_at,
        ), "maker")

        first = repository.run_monitoring_scheduler(
            datetime.now(timezone.utc), 20, "scheduler", "持续验证调度器",
            run_key="scorecard-monitoring:failure", trigger_type="scheduler",
        )
        self.assertEqual(first["run"]["status"], "partial_failed")
        second = repository.retry_monitoring_scheduler_run(first["run"]["id"], "确认数据快照缺失后执行第一次重试", "operator", "模型管理员")
        self.assertEqual(second["run"]["status"], "partial_failed")
        self.assertEqual(second["run"]["attempt_number"], 2)
        third = repository.retry_monitoring_scheduler_run(second["run"]["id"], "确认依赖仍未恢复后执行第二次重试", "operator", "模型管理员")
        self.assertEqual(third["run"]["status"], "dead_letter")
        self.assertEqual(third["run"]["attempt_number"], 3)
        self.assertEqual(repository.monitoring_scheduler_health()["health"], "blocked")

        recovered = repository.retry_monitoring_scheduler_run(third["run"]["id"], "人工核验死信依赖并重新发起恢复运行", "operator", "模型管理员")
        self.assertEqual(recovered["run"]["trigger_type"], "recovery")
        self.assertEqual(recovered["run"]["attempt_number"], 1)
        self.assertEqual(recovered["run"]["status"], "partial_failed")
        health = repository.monitoring_scheduler_health()
        self.assertEqual(health["summary"]["dead_letter"], 0)
        original_dead_letter = next(item for item in health["runs"] if item["id"] == third["run"]["id"])
        self.assertFalse(original_dead_letter["can_recover"])

    def test_monitoring_gate_alert_supports_versioned_disposition(self):
        repository = ScorecardRepository(self.session)
        policy = self._publish_policy()
        training = self._snapshot(code="MON_BLOCK", id_prefix="mon-block")
        plan = repository.create_monitoring_plan(self._monitoring_plan(policy, training, code="DEV_SCORE_BLOCKED"), "maker")
        result = repository.run_monitoring_plan(plan["id"], plan["row_version"], "maker", "模型管理员")
        self.assertEqual(result["plan"]["last_status"], "completed")
        self.assertTrue(result["events"])
        event = next(item for item in result["events"] if item["event_type"] == "gate_failed")
        self.assertEqual(event["run_id"], result["run"]["id"])
        self.assertEqual(event["evidence_hash"], result["run"]["evidence_hash"])
        self.assertEqual(event["assignee"], "model-risk-owner")
        self.assertEqual(event["sla_status"], "normal")
        self.assertGreater(event["sla_due_at"], event["sla_started_at"])
        with self.assertRaisesRegex(Exception, "刷新后重试"):
            repository.action_monitoring_event(event["id"], event["row_version"] + 1, {"action": "acknowledge"}, "maker", "模型管理员")
        acknowledged = repository.action_monitoring_event(event["id"], event["row_version"], {"action": "acknowledge"}, "maker", "模型管理员")
        remediating = repository.action_monitoring_event(acknowledged["id"], acknowledged["row_version"], {"action": "remediate", "assignee": "maker", "remediation_plan": "补充验证集和时间外样本后重新执行"}, "maker", "模型管理员")
        validation = self._snapshot(code="MON_BLOCK_VALID", id_prefix="mon-block-valid")
        oot = self._snapshot(code="MON_BLOCK_OOT", id_prefix="mon-block-oot")
        revalidation_payload = self._payload(training)
        revalidation_payload.update({"validation_snapshot_id": validation["id"], "oot_snapshot_id": oot["id"], "validation_policy_id": policy["id"]})
        revalidation = repository.create_development_run(revalidation_payload, "maker", "模型管理员")
        submitted = repository.action_monitoring_event(remediating["id"], remediating["row_version"], {
            "action": "submit_revalidation", "remediation_result": "补充三套样本后验证门禁已全部通过",
            "revalidation_run_id": revalidation["id"],
        }, "maker", "模型管理员")
        self.assertEqual(submitted["status"], "pending_revalidation")
        with self.assertRaisesRegex(PermissionError, "必须分离"):
            repository.action_monitoring_event(submitted["id"], submitted["row_version"], {
                "action": "review_revalidation", "decision": "pass", "conclusion": "整改人不能复验自己的结果",
            }, "maker", "模型管理员")
        closed = repository.action_monitoring_event(submitted["id"], submitted["row_version"], {
            "action": "review_revalidation", "decision": "pass", "conclusion": "独立复验确认新运行证据完整且门禁通过",
        }, "reviewer", "风控经理")
        self.assertEqual(closed["status"], "closed")
        self.assertEqual(closed["closed_by"], "reviewer")
        self.assertEqual(closed["revalidation_run_id"], revalidation["id"])
        self.assertEqual(closed["revalidation_evidence_hash"], revalidation["evidence_hash"])

    def test_monitoring_sla_policy_is_scoped_versioned_and_frozen_on_event(self):
        repository = ScorecardRepository(self.session)
        validation_policy = self._publish_policy()
        self._publish_sla_policy(code="SCOPED_SLA", critical_hours=12, warning_hours=36, is_default=False, scorecards=["DEV_SCORE"], event_types=["gate_failed"])
        training = self._snapshot(code="SLA_POLICY", id_prefix="sla-policy")
        plan = repository.create_monitoring_plan(self._monitoring_plan(validation_policy, training, code="SLA_POLICY_PLAN"), "maker")
        result = repository.run_monitoring_plan(plan["id"], plan["row_version"], "maker", "模型管理员")
        event = next(item for item in result["events"] if item["event_type"] == "gate_failed")
        self.assertEqual(event["sla_policy_snapshot"]["code"], "SCOPED_SLA")
        self.assertEqual(event["sla_policy_snapshot"]["severity_rules"]["critical"]["response_hours"], 12)
        self.assertTrue(event["sla_policy_integrity_valid"])
        self.assertAlmostEqual((datetime.fromisoformat(event["sla_due_at"]) - datetime.fromisoformat(event["sla_started_at"])).total_seconds(), 12 * 3600, delta=2)

        old_snapshot_hash = event["sla_policy_snapshot_hash"]
        self._publish_sla_policy(code="SCOPED_SLA", critical_hours=6, warning_hours=18, is_default=False, scorecards=["DEV_SCORE"], event_types=["gate_failed"])
        frozen = repository.list_monitoring_events(plan_id=plan["id"])[0]
        self.assertEqual(frozen["sla_policy_snapshot_hash"], old_snapshot_hash)
        self.assertEqual(frozen["sla_policy_snapshot"]["severity_rules"]["critical"]["response_hours"], 12)
        self.assertTrue(frozen["sla_policy_integrity_valid"])

    def test_monitoring_sla_policy_api_enforces_four_eyes_governance(self):
        body = {"policy": {
            "code": "API_SLA", "name": "API 持续验证 SLA", "description": "验证 SLA 策略接口权限与四眼治理",
            "applicable_scorecard_codes": [], "applicable_event_types": [], "is_default": True,
            "severity_rules": {
                "critical": {"response_hours": 18, "due_soon_ratio": 0.25, "escalation_after_hours": 2},
                "warning": {"response_hours": 60, "due_soon_ratio": 0.2, "escalation_after_hours": 6},
            },
        }, "change_reason": "建立接口测试 SLA 策略"}
        client = TestClient(app)
        self.assertEqual(client.post("/api/v1/indicator-center/scorecard-monitoring-sla-policies", json=body, headers={"Authorization": "Bearer dev-manager"}).status_code, 403)
        created = client.post("/api/v1/indicator-center/scorecard-monitoring-sla-policies", json=body, headers={"Authorization": "Bearer dev-model-admin"})
        self.assertEqual(created.status_code, 201, created.text)
        draft = created.json()
        submitted = client.post(f"/api/v1/indicator-center/scorecard-monitoring-sla-policies/{draft['id']}/submit", json={"expected_row_version": draft["row_version"]}, headers={"Authorization": "Bearer dev-model-admin"})
        self.assertEqual(submitted.status_code, 200, submitted.text)
        self.assertEqual(client.post(f"/api/v1/indicator-center/scorecard-monitoring-sla-policies/{draft['id']}/review", json={"expected_row_version": submitted.json()["row_version"], "decision": "publish", "comment": "创建人不能自行发布 SLA 策略"}, headers={"Authorization": "Bearer dev-model-admin"}).status_code, 403)
        reviewed = client.post(f"/api/v1/indicator-center/scorecard-monitoring-sla-policies/{draft['id']}/review", json={"expected_row_version": submitted.json()["row_version"], "decision": "publish", "comment": "独立复核确认 SLA 范围与分级时限"}, headers={"Authorization": "Bearer dev-risk"})
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        self.assertTrue(reviewed.json()["is_active"])

    def test_monitoring_api_enforces_permissions_and_returns_alert_ledger(self):
        policy = self._publish_policy()
        training = self._snapshot(code="MON_API", id_prefix="mon-api")
        body = {"plan": self._monitoring_plan(policy, training, code="DEV_SCORE_API")}
        body["plan"]["next_run_at"] = body["plan"]["next_run_at"].isoformat()
        client = TestClient(app)
        self.assertEqual(client.post("/api/v1/indicator-center/scorecard-monitoring-plans", json=body, headers={"Authorization": "Bearer dev-manager"}).status_code, 403)
        created = client.post("/api/v1/indicator-center/scorecard-monitoring-plans", json=body, headers={"Authorization": "Bearer dev-model-admin"})
        self.assertEqual(created.status_code, 201, created.text)
        run = client.post(f"/api/v1/indicator-center/scorecard-monitoring-plans/{created.json()['id']}/run", json={"expected_row_version": created.json()["row_version"]}, headers={"Authorization": "Bearer dev-model-admin"})
        self.assertEqual(run.status_code, 200, run.text)
        events = client.get("/api/v1/indicator-center/scorecard-monitoring-events?status=open", headers={"Authorization": "Bearer dev-risk"})
        self.assertEqual(events.status_code, 200, events.text)
        self.assertTrue(events.json())
        self.assertEqual(events.json()[0]["run_id"], run.json()["run"]["id"])
        event = events.json()[0]
        forbidden_manage = client.post(
            f"/api/v1/indicator-center/scorecard-monitoring-events/{event['id']}/action",
            json={"expected_row_version": event["row_version"], "action": "acknowledge"},
            headers={"Authorization": "Bearer dev-risk"},
        )
        self.assertEqual(forbidden_manage.status_code, 403)
        forbidden_review = client.post(
            f"/api/v1/indicator-center/scorecard-monitoring-events/{event['id']}/action",
            json={"expected_row_version": event["row_version"], "action": "review_revalidation", "decision": "pass", "conclusion": "模型管理员不能执行独立复验"},
            headers={"Authorization": "Bearer dev-model-admin"},
        )
        self.assertEqual(forbidden_review.status_code, 403)
        health = client.get(
            "/api/v1/indicator-center/scorecard-monitoring-scheduler/health",
            headers={"Authorization": "Bearer dev-risk"},
        )
        self.assertEqual(health.status_code, 200, health.text)
        self.assertIn(health.json()["health"], {"healthy", "degraded", "blocked", "never"})
        forbidden_scheduler = client.post(
            "/api/v1/indicator-center/scorecard-monitoring-plans/run-due",
            json={"max_plans": 20, "run_key": "scorecard-monitoring:api-forbidden", "trigger_type": "manual"},
            headers={"Authorization": "Bearer dev-risk"},
        )
        self.assertEqual(forbidden_scheduler.status_code, 403)
        scheduler = client.post(
            "/api/v1/indicator-center/scorecard-monitoring-plans/run-due",
            json={"max_plans": 20, "run_key": "scorecard-monitoring:api-run", "trigger_type": "manual"},
            headers={"Authorization": "Bearer dev-model-admin"},
        )
        self.assertEqual(scheduler.status_code, 200, scheduler.text)
        self.assertEqual(scheduler.json()["run"]["status"], "completed")

    def test_monitoring_event_filters_and_csv_export_share_scope(self):
        repository, plan, events = self._operational_events()
        first = events[0]
        assigned = repository.action_monitoring_event(first["id"], first["row_version"], {"action": "assign", "assignee": "portfolio-owner"}, "maker", "模型管理员")
        filtered = repository.list_monitoring_events(
            status=assigned["status"], severity=assigned["severity"], event_type=assigned["event_type"],
            assignee="portfolio-owner", plan_id=plan["id"], scorecard_code="DEV_SCORE", sla_status=assigned["sla_status"],
        )
        self.assertEqual([item["id"] for item in filtered], [assigned["id"]])
        csv_content = repository.export_monitoring_events_csv({
            "status": assigned["status"], "plan_id": plan["id"], "severity": assigned["severity"],
            "event_type": assigned["event_type"], "assignee": "portfolio-owner", "scorecard_code": "DEV_SCORE",
            "sla_status": assigned["sla_status"],
        })
        self.assertTrue(csv_content.startswith("\ufeff预警编号"))
        self.assertIn("MON_OPS_PLAN", csv_content)
        self.assertIn("DEV_SCORE@v1", csv_content)
        self.assertEqual(len(csv_content.splitlines()), 2)

    def test_monitoring_bulk_assignment_is_atomic_and_audited(self):
        repository, _, events = self._operational_events()
        targets = events[:2]
        result = repository.bulk_assign_monitoring_events(
            [{"event_id": item["id"], "expected_row_version": item["row_version"]} for item in targets],
            "model-risk-pool", "按严重程度和评分卡组合统一分派", "maker", "模型管理员",
        )
        self.assertEqual(result["assigned_count"], 2)
        self.assertTrue(all(item["assignee"] == "model-risk-pool" for item in result["events"]))
        self.assertEqual(self.session.query(AuditEventRecord).filter_by(aggregate_type="scorecard_monitoring_bulk_assignment", aggregate_id=result["batch_id"]).count(), 1)
        stale_items = [{"event_id": item["id"], "expected_row_version": item["row_version"]} for item in result["events"]]
        stale_items[1]["expected_row_version"] += 1
        with self.assertRaisesRegex(ConcurrentUpdateError, "刷新后重试"):
            repository.bulk_assign_monitoring_events(stale_items, "wrong-owner", "模拟行版本漂移阻断整个批次", "maker", "模型管理员")
        current = {item["id"]: item for item in repository.list_monitoring_events(plan_id=events[0]["plan_id"])}
        self.assertTrue(all(current[item["id"]]["assignee"] == "model-risk-pool" for item in targets))

    def test_monitoring_saved_views_are_private_and_have_one_default(self):
        repository = ScorecardRepository(self.session)
        first = repository.create_monitoring_saved_view({"name": "我的严重预警", "filters": {"severity": "critical"}, "is_default": True}, "maker")
        second = repository.create_monitoring_saved_view({"name": "逾期督办", "filters": {"sla_status": "overdue"}, "is_default": True}, "maker")
        views = repository.list_monitoring_saved_views("maker")
        self.assertEqual([item["id"] for item in views if item["is_default"]], [second["id"]])
        self.assertFalse(next(item for item in views if item["id"] == first["id"])["is_default"])
        self.assertEqual(repository.list_monitoring_saved_views("reviewer"), [])
        with self.assertRaisesRegex(LookupError, "不存在"):
            repository.update_monitoring_saved_view(second["id"], second["row_version"], {"name": "越权修改", "filters": {}, "is_default": False}, "reviewer")

    def test_monitoring_operations_api_permissions_and_csv_bom(self):
        _, _, events = self._operational_events()
        client = TestClient(app)
        exported = client.get("/api/v1/indicator-center/scorecard-monitoring-events/export?scorecard_code=DEV_SCORE", headers={"Authorization": "Bearer dev-risk"})
        self.assertEqual(exported.status_code, 200, exported.text)
        self.assertTrue(exported.content.startswith(b"\xef\xbb\xbf"))
        payload = {"items": [{"event_id": events[0]["id"], "expected_row_version": events[0]["row_version"]}], "assignee": "api-owner", "reason": "接口批量分派测试"}
        self.assertEqual(client.post("/api/v1/indicator-center/scorecard-monitoring-events/bulk-assign", json=payload, headers={"Authorization": "Bearer dev-risk"}).status_code, 403)
        assigned = client.post("/api/v1/indicator-center/scorecard-monitoring-events/bulk-assign", json=payload, headers={"Authorization": "Bearer dev-model-admin"})
        self.assertEqual(assigned.status_code, 200, assigned.text)
        self.assertEqual(assigned.json()["assigned_count"], 1)
        view = client.post("/api/v1/indicator-center/scorecard-monitoring-saved-views", json={"name": "API 严重预警", "filters": {"severity": "critical"}, "is_default": True}, headers={"Authorization": "Bearer dev-risk"})
        self.assertEqual(view.status_code, 201, view.text)
        self.assertEqual(client.get("/api/v1/indicator-center/scorecard-monitoring-saved-views", headers={"Authorization": "Bearer dev-model-admin"}).json(), [])

    def test_monitoring_sla_scan_is_deduplicated_and_enters_personal_tasks(self):
        repository = ScorecardRepository(self.session)
        policy = self._publish_policy()
        training = self._snapshot(code="MON_SLA", id_prefix="mon-sla")
        plan_payload = self._monitoring_plan(policy, training, code="DEV_SCORE_SLA")
        plan_payload["owner"] = "model-demo"
        plan = repository.create_monitoring_plan(plan_payload, "maker")
        event_data = repository.run_monitoring_plan(plan["id"], plan["row_version"], "maker", "模型管理员")["events"][0]
        event = self.session.get(ScorecardValidationMonitoringEvent, event_data["id"])
        now = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
        event.sla_started_at = now - timedelta(hours=19)
        event.sla_due_at = now + timedelta(hours=5)
        self.session.commit()

        due_soon = repository.scan_monitoring_event_sla(now, "sla-monitor")
        self.assertEqual(due_soon["due_soon"], 1)
        self.assertEqual(due_soon["notifications_created"], 1)
        self.assertEqual(repository.scan_monitoring_event_sla(now, "sla-monitor")["notifications_created"], 0)
        queue = build_personal_task_queue(self.session, ("model_admin",), now=now, actor_subject="model-demo")
        self.assertGreaterEqual(queue["summary"]["scorecard_monitoring"], 1)
        task = next(item for item in queue["tasks"] if item["action"].get("monitoring_event_id") == event.id)
        self.assertEqual(task["task_type"], "scorecard_monitoring")
        self.assertEqual(task["action"]["page"], "indicators")

        event = self.session.get(ScorecardValidationMonitoringEvent, event.id)
        event.sla_due_at = now - timedelta(hours=1)
        self.session.commit()
        overdue = repository.scan_monitoring_event_sla(now, "sla-monitor")
        self.assertEqual(overdue["overdue"], 1)
        self.assertEqual(overdue["notifications_created"], 2)
        event = self.session.get(ScorecardValidationMonitoringEvent, event.id)
        event.sla_due_at = now - timedelta(hours=5)
        self.session.commit()
        escalated = repository.scan_monitoring_event_sla(now, "sla-monitor")
        self.assertEqual(escalated["escalated"], 1)
        self.assertEqual(escalated["notifications_created"], 1)
        self.assertEqual(self.session.get(ScorecardValidationMonitoringEvent, event.id).escalation_level, 2)

    def test_governed_default_policy_overrides_inline_thresholds_and_is_frozen(self):
        repository = ScorecardRepository(self.session)
        draft = repository.create_validation_policy(self._policy(), "建立机构统一验证门槛", "maker", "模型管理员")
        submitted = repository.submit_validation_policy(draft["id"], draft["row_version"], "maker", False)
        with self.assertRaisesRegex(PermissionError, "不能复核"):
            repository.review_validation_policy(submitted["id"], submitted["row_version"], "publish", "尝试自行批准策略", "maker", "模型管理员")
        published = repository.review_validation_policy(submitted["id"], submitted["row_version"], "publish", "独立复核确认机构门槛适用", "reviewer", "风控经理")

        payload = self._payload(self._snapshot())
        payload["validation_thresholds"] = {**DEFAULT_VALIDATION_THRESHOLDS, "require_validation_snapshot": False, "require_oot_snapshot": False, "min_auc": 0}
        run = repository.create_development_run(payload, "maker", "模型管理员")

        self.assertEqual(run["validation_policy"]["id"], published["id"])
        self.assertEqual(run["validation_policy"]["config_hash"], published["config_hash"])
        self.assertEqual(run["label_policy"]["validation_thresholds"]["min_auc"], 0.75)
        self.assertTrue(run["label_policy"]["validation_thresholds"]["require_validation_snapshot"])
        self.assertFalse(run["report"]["validation_gate"]["passed"])
        self.assertTrue(run["validation_policy_integrity_valid"])

    def test_explicit_policy_must_be_active_and_applicable(self):
        policy = self._publish_policy(self._policy("OTHER_SCORE_ONLY", is_default=False, applicable=["OTHER_SCORE"]))
        payload = self._payload(self._snapshot())
        payload["validation_policy_id"] = policy["id"]
        with self.assertRaisesRegex(ValueError, "不适用于评分卡"):
            ScorecardRepository(self.session).create_development_run(payload, "maker", "模型管理员")

    def test_new_default_policy_deactivates_previous_default(self):
        first = self._publish_policy()
        second = self._publish_policy(self._policy("INSTITUTION_STANDARD_V2"))
        policies = ScorecardRepository(self.session).list_validation_policies()
        self.assertFalse(next(item for item in policies if item["id"] == first["id"])["is_active"])
        self.assertTrue(next(item for item in policies if item["id"] == second["id"])["is_active"])
        self.assertEqual(sum(item["is_active"] and item["is_default"] for item in policies), 1)

    def test_development_trends_preserve_versions_and_hide_tampered_metrics(self):
        repository = ScorecardRepository(self.session)
        policy = self._publish_policy()
        payload = self._payload(self._snapshot(code="TREND_TRAIN", id_prefix="train"))
        payload.update({
            "validation_policy_id": policy["id"],
            "validation_snapshot_id": self._snapshot(code="TREND_VALIDATION", id_prefix="validation")["id"],
            "oot_snapshot_id": self._snapshot(code="TREND_OOT", id_prefix="oot", shift=True)["id"],
            "predicted_probability_field": "predicted_pd", "segment_fields": ["region"],
            "min_segment_sample_count": 2,
        })
        valid = repository.create_development_run(payload, "maker", "模型管理员")
        invalid = repository.create_development_run({**payload, "dataset_snapshot_id": self._snapshot(code="TREND_TAMPERED", id_prefix="tampered")["id"]}, "maker", "模型管理员")
        invalid_record = self.session.get(ScorecardDevelopmentRun, invalid["id"])
        invalid_record.report_json = {**invalid_record.report_json, "evidence_level": "unlabeled"}
        self.session.commit()

        trends = repository.development_trends("DEV_SCORE", 20)
        self.assertEqual(trends["summary"]["run_count"], 2)
        self.assertEqual(trends["summary"]["invalid_count"], 1)
        self.assertEqual(trends["series"][0]["scorecard_versions"], [1])
        points = {point["run_id"]: point for point in trends["series"][0]["points"]}
        self.assertEqual(points[valid["id"]]["validation_policy"]["version"], 1)
        self.assertEqual(points[valid["id"]]["metrics"]["validation_auc"], 1.0)
        self.assertIsNotNone(points[valid["id"]]["metrics"]["max_group_score_psi"])
        self.assertEqual(points[invalid["id"]]["status"], "invalid")
        self.assertTrue(all(value is None for value in points[invalid["id"]]["metrics"].values()))

        client = TestClient(app)
        forbidden = client.get("/api/v1/indicator-center/scorecard-development-trends", headers={"Authorization": "Bearer dev-client"})
        self.assertEqual(forbidden.status_code, 403)
        response = client.get("/api/v1/indicator-center/scorecard-development-trends?scorecard_code=DEV_SCORE&max_runs=20", headers={"Authorization": "Bearer dev-risk"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["summary"]["run_count"], 2)

    def test_portfolio_stability_combines_latest_run_plan_events_and_integrity(self):
        repository = ScorecardRepository(self.session)
        empty = repository.portfolio_stability()
        self.assertEqual(empty["summary"]["scorecard_count"], 1)
        self.assertEqual(empty["rows"][0]["status"], "unmonitored")

        policy = self._publish_policy()
        training = self._snapshot(code="PORTFOLIO_TRAIN", id_prefix="portfolio-train")
        validation = self._snapshot(code="PORTFOLIO_VALID", id_prefix="portfolio-valid")
        oot = self._snapshot(code="PORTFOLIO_OOT", id_prefix="portfolio-oot")
        plan = repository.create_monitoring_plan(
            self._monitoring_plan(policy, training, validation, oot, code="PORTFOLIO_MONTHLY"),
            "maker",
        )
        execution = repository.run_monitoring_plan(
            plan["id"], plan["row_version"], "maker", "模型管理员"
        )

        portfolio = repository.portfolio_stability()
        row = portfolio["rows"][0]
        self.assertEqual(row["latest_run_id"], execution["run"]["id"])
        self.assertEqual(row["status"], "healthy")
        self.assertEqual(row["monitoring"]["enabled_plan_count"], 1)
        self.assertEqual(row["open_events"]["total"], 0)
        self.assertEqual(row["metrics"]["validation_auc"], 1.0)
        self.assertEqual(row["metric_health"]["validation_auc"]["status"], "healthy")

        record = self.session.get(ScorecardDevelopmentRun, execution["run"]["id"])
        record.report_json = {**record.report_json, "evidence_level": "unlabeled"}
        self.session.commit()
        invalid = repository.portfolio_stability()
        self.assertEqual(invalid["summary"]["invalid_count"], 1)
        self.assertEqual(invalid["rows"][0]["status"], "invalid")
        self.assertTrue(all(value is None for value in invalid["rows"][0]["metrics"].values()))

        client = TestClient(app)
        forbidden = client.get(
            "/api/v1/indicator-center/scorecard-portfolio-stability",
            headers={"Authorization": "Bearer dev-client"},
        )
        self.assertEqual(forbidden.status_code, 403)
        response = client.get(
            "/api/v1/indicator-center/scorecard-portfolio-stability",
            headers={"Authorization": "Bearer dev-risk"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["summary"]["invalid_count"], 1)

    def test_validation_policy_api_enforces_manage_review_and_lists_versions(self):
        client = TestClient(app)
        body = {"policy": self._policy("API_STANDARD"), "change_reason": "通过 API 建立机构验证策略"}
        forbidden = client.post("/api/v1/indicator-center/validation-policies", json=body, headers={"Authorization": "Bearer dev-manager"})
        self.assertEqual(forbidden.status_code, 403)
        created = client.post("/api/v1/indicator-center/validation-policies", json=body, headers={"Authorization": "Bearer dev-model-admin"})
        self.assertEqual(created.status_code, 201, created.text)
        draft = created.json()
        updated_policy = self._policy("API_STANDARD")
        updated_policy["name"] = "机构标准验证策略（修订）"
        updated_policy["thresholds"]["min_auc"] = 0.8
        updated = client.put(
            f"/api/v1/indicator-center/validation-policies/{draft['id']}",
            json={"expected_row_version": draft["row_version"], "policy": updated_policy, "change_reason": "调整最低 AUC 后提交独立复核"},
            headers={"Authorization": "Bearer dev-model-admin"},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        draft = updated.json()
        self.assertEqual(draft["thresholds"]["min_auc"], 0.8)
        self.assertGreater(draft["row_version"], created.json()["row_version"])
        submitted = client.post(
            f"/api/v1/indicator-center/validation-policies/{draft['id']}/submit",
            json={"expected_row_version": draft["row_version"]}, headers={"Authorization": "Bearer dev-model-admin"},
        )
        self.assertEqual(submitted.status_code, 200, submitted.text)
        published = client.post(
            f"/api/v1/indicator-center/validation-policies/{draft['id']}/review",
            json={"expected_row_version": submitted.json()["row_version"], "decision": "publish", "comment": "风控独立复核确认策略适用"},
            headers={"Authorization": "Bearer dev-risk"},
        )
        self.assertEqual(published.status_code, 200, published.text)
        listed = client.get("/api/v1/indicator-center/validation-policies", headers={"Authorization": "Bearer dev-risk"})
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()[0]["status"], "published")
        self.assertTrue(listed.json()[0]["is_active"])

    def test_labeled_snapshot_generates_bin_woe_iv_and_frozen_evidence(self):
        run = ScorecardRepository(self.session).create_development_run(self._payload(self._snapshot()), "maker", "模型管理员")
        report = run["report"]
        indicator = report["indicators"][0]
        self.assertEqual(run["evidence_level"], "labeled")
        self.assertTrue(run["integrity_valid"])
        self.assertEqual(report["summary"]["eligible_sample_count"], 8)
        self.assertEqual(report["summary"]["event_count"], 4)
        self.assertGreater(indicator["information_value"], 0)
        self.assertEqual(indicator["bins"][0]["woe_source"], "sample_calculated")
        self.assertEqual(indicator["bins"][0]["configured_woe"], 0.4)
        self.assertNotEqual(indicator["bins"][0]["calculated_woe"], indicator["bins"][0]["configured_woe"])

    def test_unlabeled_snapshot_is_explicitly_degraded(self):
        run = ScorecardRepository(self.session).create_development_run(self._payload(self._snapshot(labeled=False)), "maker", "模型管理员")
        self.assertEqual(run["evidence_level"], "unlabeled")
        self.assertEqual(run["report"]["summary"]["eligible_sample_count"], 0)
        self.assertIsNone(run["report"]["indicators"][0]["bins"][0]["calculated_woe"])
        self.assertIn("没有可用标签", run["report"]["warnings"][0])

    def test_tampered_report_fails_integrity_check(self):
        created = ScorecardRepository(self.session).create_development_run(self._payload(self._snapshot()), "maker", "模型管理员")
        record = self.session.get(ScorecardDevelopmentRun, created["id"])
        record.report_json = {**record.report_json, "evidence_level": "unlabeled"}
        self.session.commit()
        listed = ScorecardRepository(self.session).list_development_runs()[0]
        self.assertFalse(listed["integrity_valid"])

    def test_api_creates_lists_and_enforces_manage_permission(self):
        snapshot = self._snapshot()
        payload = self._payload(snapshot)
        payload["observation_start"] = payload["observation_start"].isoformat()
        payload["observation_end"] = payload["observation_end"].isoformat()
        client = TestClient(app)
        forbidden = client.post("/api/v1/indicator-center/scorecard-development-runs", json=payload, headers={"Authorization": "Bearer dev-manager"})
        self.assertEqual(forbidden.status_code, 403)
        created = client.post("/api/v1/indicator-center/scorecard-development-runs", json=payload, headers={"Authorization": "Bearer dev-model-admin"})
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(client.post(f"/api/v1/indicator-center/scorecard-development-runs/{created.json()['id']}/review", json={"expected_row_version": created.json()["row_version"], "decision": "reject", "comment": "权限不足不能审核"}, headers={"Authorization": "Bearer dev-model-admin"}).status_code, 403)
        blocked = client.post(f"/api/v1/indicator-center/scorecard-development-runs/{created.json()['id']}/review", json={"expected_row_version": created.json()["row_version"], "decision": "approve", "comment": "尝试批准缺少验证集的运行"}, headers={"Authorization": "Bearer dev-risk"})
        self.assertEqual(blocked.status_code, 422, blocked.text)
        reviewed = client.post(f"/api/v1/indicator-center/scorecard-development-runs/{created.json()['id']}/review", json={"expected_row_version": created.json()["row_version"], "decision": "reject", "comment": "缺少验证集和时间外样本"}, headers={"Authorization": "Bearer dev-risk"})
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        self.assertEqual(reviewed.json()["review_status"], "rejected")
        listed = client.get("/api/v1/indicator-center/scorecard-development-runs", headers={"Authorization": "Bearer dev-risk"})
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()[0]["evidence_hash"], created.json()["evidence_hash"])

    def test_three_way_validation_generates_performance_stability_and_calibration(self):
        training = self._snapshot(code="SC_TRAIN", id_prefix="train")
        validation = self._snapshot(code="SC_VALID", id_prefix="valid")
        oot = self._snapshot(code="SC_OOT", id_prefix="oot", shift=True)
        payload = self._payload(training)
        payload.update({"validation_snapshot_id": validation["id"], "oot_snapshot_id": oot["id"], "subject_id_field": "id", "predicted_probability_field": "predicted_pd"})

        run = ScorecardRepository(self.session).create_development_run(payload, "maker", "模型管理员")
        performance = run["report"]["performance"]
        self.assertEqual(run["report"]["schema_version"], "scorecard-development-report-v4")
        self.assertEqual(performance["training"]["auc"], 1.0)
        self.assertEqual(performance["validation"]["ks"], 1.0)
        self.assertAlmostEqual(performance["training"]["brier"], 0.04)
        self.assertEqual(performance["validation"]["score_psi"], 0.0)
        self.assertGreater(performance["oot"]["score_psi"], 0)
        self.assertTrue(run["report"]["split_evidence"]["leakage_passed"])
        self.assertTrue(run["integrity_valid"])
        self.assertEqual(run["validation_snapshot_id"], validation["id"])
        self.assertEqual(run["oot_snapshot_id"], oot["id"])

    def test_subject_leakage_across_snapshots_is_blocked(self):
        training = self._snapshot(code="SC_TRAIN", id_prefix="shared")
        validation = self._snapshot(code="SC_VALID", id_prefix="shared")
        payload = self._payload(training)
        payload["validation_snapshot_id"] = validation["id"]
        with self.assertRaisesRegex(ValueError, "主体泄漏"):
            ScorecardRepository(self.session).create_development_run(payload, "maker", "模型管理员")

    def test_segment_fairness_reports_coverage_disparities_and_missing_sensitive_attribute(self):
        training = self._snapshot(code="SC_FAIR_TRAIN", id_prefix="fair-train")
        validation = self._snapshot(code="SC_FAIR_VALID", id_prefix="fair-valid", shift=True)
        payload = self._payload(training)
        payload.update({
            "validation_snapshot_id": validation["id"],
            "predicted_probability_field": "predicted_pd",
            "segment_fields": ["region", "protected_group"],
            "sensitive_attribute_fields": ["protected_group"],
            "min_segment_sample_count": 2,
            "classification_threshold": 0.5,
        })

        run = ScorecardRepository(self.session).create_development_run(payload, "maker", "模型管理员")
        fairness = run["report"]["fairness"]
        region = fairness["splits"]["training"]["region"]
        self.assertEqual(run["report"]["schema_version"], "scorecard-development-report-v4")
        self.assertEqual(region["coverage_rate"], 1.0)
        self.assertEqual(region["group_count"], 2)
        self.assertTrue(all(group["sample_sufficient"] for group in region["groups"]))
        self.assertTrue(all(group["false_positive_rate"] == 0 for group in region["groups"]))
        self.assertEqual(fairness["splits"]["training"]["protected_group"]["status"], "untestable")
        self.assertIsNone(fairness["splits"]["training"]["protected_group"]["population_psi"])
        self.assertIsNone(fairness["splits"]["validation"]["protected_group"]["population_psi"])
        self.assertGreater(fairness["splits"]["validation"]["region"]["population_psi"], -0.000001)
        self.assertGreater(fairness["splits"]["validation"]["region"]["disparities"]["average_score_gap"], 0)
        self.assertTrue(any("敏感属性 protected_group 无有效值" in warning for warning in fairness["warnings"]))
        self.assertTrue(run["integrity_valid"])

    def test_sensitive_attribute_must_be_a_configured_segment(self):
        payload = self._payload(self._snapshot(code="SC_FAIR_POLICY", id_prefix="fair-policy"))
        payload["sensitive_attribute_fields"] = ["region"]
        with self.assertRaisesRegex(ValueError, "必须同时包含在分群字段"):
            ScorecardRepository(self.session).create_development_run(payload, "maker", "模型管理员")

    def test_validation_gate_generates_structured_violations(self):
        training = self._snapshot(code="SC_GATE_TRAIN", id_prefix="gate-train")
        validation = self._snapshot(code="SC_GATE_VALID", id_prefix="gate-valid")
        oot = self._snapshot(code="SC_GATE_OOT", id_prefix="gate-oot", shift=True)
        payload = self._payload(training)
        payload.update({"validation_snapshot_id": validation["id"], "oot_snapshot_id": oot["id"], "predicted_probability_field": "predicted_pd"})

        run = ScorecardRepository(self.session).create_development_run(payload, "maker", "模型管理员")
        gate = run["report"]["validation_gate"]
        self.assertFalse(gate["passed"])
        self.assertEqual(gate["summary"], "1 项验证门槛未通过")
        self.assertEqual(gate["violations"][0]["key"], "oot.score_psi")
        self.assertEqual(gate["violations"][0]["operator"], "<=")
        self.assertEqual(run["review_status"], "pending_review")

    def test_independent_review_approves_passed_gate_and_rejects_failed_gate(self):
        training = self._snapshot(code="SC_REVIEW_TRAIN", id_prefix="review-train")
        validation = self._snapshot(code="SC_REVIEW_VALID", id_prefix="review-valid")
        oot = self._snapshot(code="SC_REVIEW_OOT", id_prefix="review-oot")
        payload = self._payload(training)
        payload.update({"validation_snapshot_id": validation["id"], "oot_snapshot_id": oot["id"], "predicted_probability_field": "predicted_pd"})
        repository = ScorecardRepository(self.session)
        run = repository.create_development_run(payload, "maker", "模型管理员")
        self.assertTrue(run["report"]["validation_gate"]["passed"])
        with self.assertRaisesRegex(PermissionError, "不能复核自己的证据"):
            repository.review_development_run(run["id"], run["row_version"], "approve", "本人尝试批准验证", "maker", "模型管理员")
        approved = repository.review_development_run(run["id"], run["row_version"], "approve", "独立复核确认全部门槛通过", "reviewer", "风控经理")
        self.assertEqual(approved["review_status"], "approved")
        self.assertTrue(approved["review_integrity_valid"])
        self.assertTrue(approved["review_hash"])

        failed_payload = self._payload(self._snapshot(code="SC_REJECT_TRAIN", id_prefix="reject-train"))
        failed = repository.create_development_run(failed_payload, "maker", "模型管理员")
        with self.assertRaisesRegex(ValueError, "门禁未通过"):
            repository.review_development_run(failed["id"], failed["row_version"], "approve", "尝试批准失败门禁证据", "reviewer", "风控经理")
        rejected = repository.review_development_run(failed["id"], failed["row_version"], "reject", "缺少独立验证和时间外证据", "reviewer", "风控经理")
        self.assertEqual(rejected["review_status"], "rejected")


if __name__ == "__main__":
    unittest.main()
