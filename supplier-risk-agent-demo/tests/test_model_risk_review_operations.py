from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import backend.database as database
from backend.db_models import AuditEventRecord, ModelRiskReviewAssignmentRecord, ModelRiskReviewDelegationRecord, ModelRiskReviewSavedViewRecord, NotificationRecord, TenantMembershipRecord, TenantMonitoringDiffCaseRecord, TenantRecord
from backend.main import app
from backend.model_risk_policy_repository import ModelRiskPolicyError, ModelRiskPolicyRepository
from tests.database_support import IsolatedTestDatabase
from fastapi.testclient import TestClient


TENANT_ID = "tenant-demo-hengxin"


class TestModelRiskReviewOperations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = IsolatedTestDatabase()
        cls.db.start()

    @classmethod
    def tearDownClass(cls):
        cls.db.stop()

    def setUp(self):
        with database.SessionLocal() as session:
            session.query(ModelRiskReviewDelegationRecord).filter(ModelRiskReviewDelegationRecord.tenant_id == TENANT_ID).delete()
            session.query(ModelRiskReviewAssignmentRecord).filter(ModelRiskReviewAssignmentRecord.tenant_id == TENANT_ID).delete()
            session.query(ModelRiskReviewSavedViewRecord).delete()
            session.query(AuditEventRecord).filter(AuditEventRecord.aggregate_type.like("model_risk_review%" )).delete()
            session.query(NotificationRecord).filter(NotificationRecord.tenant_id == TENANT_ID).delete()
            session.query(TenantMembershipRecord).filter(TenantMembershipRecord.tenant_id == TENANT_ID).delete()
            session.query(TenantRecord).filter(TenantRecord.id == TENANT_ID).delete()
            session.add(TenantRecord(id=TENANT_ID, name="运营测试租户", deployment_mode="saas", status="active", data_region="cn"))
            session.add_all([
                TenantMembershipRecord(id=str(uuid4()), tenant_id=TENANT_ID, subject="risk-demo", display_name="风控经理", roles_json=["risk_manager"], status="active"),
                TenantMembershipRecord(id=str(uuid4()), tenant_id=TENANT_ID, subject="risk-owner", display_name="风险经理甲", roles_json=["risk_manager"], status="active"),
                TenantMembershipRecord(id=str(uuid4()), tenant_id=TENANT_ID, subject="risk-delegate", display_name="风险经理乙", roles_json=["risk_manager"], status="active"),
                TenantMembershipRecord(id=str(uuid4()), tenant_id=TENANT_ID, subject="model-owner", display_name="模型管理员", roles_json=["model_admin"], status="active"),
                TenantMembershipRecord(id=str(uuid4()), tenant_id=TENANT_ID, subject="expired-risk", display_name="已过期成员", roles_json=["risk_manager"], status="active", expires_at=datetime.now(timezone.utc) - timedelta(days=1)),
                TenantMembershipRecord(id=str(uuid4()), tenant_id=TENANT_ID, subject="suspended-risk", display_name="停用成员", roles_json=["risk_manager"], status="suspended"),
            ])
            session.commit()

    @staticmethod
    def _queue_item(item_id: str = "monitoring_gate:run-1", subject: str | None = None, role: str = "risk_manager") -> dict:
        return {
            "id": item_id, "source": "monitoring_gate", "priority": "P1", "priority_reason": "监控异常",
            "state": "blocked", "title": "监控门禁阻断", "summary": "测试复核事项",
            "due_at": None, "days_remaining": None, "model_key": "general", "model_version": "v1",
            "model_change_id": None, "model_release_id": None, "policy_id": "policy-1",
            "monitoring_run_id": "run-1", "diff_case_id": None, "evidence_level": "non_supervised",
            "responsible": [{"subject": subject, "role": role, "name": subject or role}],
            "action": {"target": "tenant-rollout-governance", "label": "复核监控快照"},
        }

    def test_saved_views_are_tenant_and_owner_scoped_with_single_default(self):
        with database.SessionLocal() as session:
            repository = ModelRiskPolicyRepository(session)
            first = repository.create_review_saved_view(TENANT_ID, "risk-user", {"name": "我的 P0", "filters": {"priority": "P0"}, "is_default": True})
            second = repository.create_review_saved_view(TENANT_ID, "risk-user", {"name": "我的全部", "filters": {}, "is_default": True})
            self.assertEqual(repository.list_review_saved_views(TENANT_ID, "risk-user")[0]["id"], second["id"])
            self.assertFalse(session.get(ModelRiskReviewSavedViewRecord, first["id"]).is_default)
            self.assertEqual(repository.list_review_saved_views("tenant-other", "risk-user"), [])
            with self.assertRaises(ModelRiskPolicyError):
                repository.update_review_saved_view(TENANT_ID, "other-user", second["id"], second["row_version"], {"name": "越权", "filters": {}, "is_default": False})

    def test_empty_workbench_snapshot_is_idempotent_and_trend_is_stable(self):
        with database.SessionLocal() as session:
            repository = ModelRiskPolicyRepository(session)
            workbench = repository.review_queue_workbench(TENANT_ID, ownership="unassigned")
            self.assertEqual(workbench["counts"]["total"], 0)
            first = repository.create_review_sla_snapshot(TENANT_ID)
            second = repository.create_review_sla_snapshot(TENANT_ID)
            self.assertEqual(first["id"], second["id"])
            trend = repository.list_review_sla_trends(TENANT_ID, days=7)
            self.assertEqual([item["snapshot_date"] for item in trend["items"]], [first["snapshot_date"]])

    def test_invalid_ownership_filter_is_rejected(self):
        with database.SessionLocal() as session:
            with self.assertRaisesRegex(ModelRiskPolicyError, "责任范围"):
                ModelRiskPolicyRepository(session).review_queue_workbench(TENANT_ID, ownership="team")

    def test_workbench_endpoint_returns_v2_envelope_and_tenant_scope(self):
        with TestClient(app) as client:
            response = client.get("/api/v1/model-governance/risk-review-queue/workbench", headers={"Authorization": "Bearer dev-risk"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["schema_version"], "model-risk-review-queue-v2")
            self.assertEqual(response.json()["filters"]["ownership"], "all")

    def test_member_directory_only_returns_current_active_tenant_members(self):
        with database.SessionLocal() as session:
            members = ModelRiskPolicyRepository(session).list_review_members(TENANT_ID)
            self.assertEqual({item["subject"] for item in members}, {"risk-demo", "risk-owner", "risk-delegate", "model-owner"})
            self.assertEqual(ModelRiskPolicyRepository(session).list_review_members("tenant-demo-alt"), [])

    def test_assignment_handoff_and_unassign_use_member_identity_and_tenant_audit(self):
        queue_item = self._queue_item()
        with database.SessionLocal() as session:
            repository = ModelRiskPolicyRepository(session)
            with patch.object(repository, "unified_review_queue", return_value=[queue_item]):
                repository.bulk_assign_review_items(
                    TENANT_ID, [{"item_id": queue_item["id"], "expected_assignment_version": 0}],
                    "risk-owner", "伪造名称", "risk_manager", "首次分派测试", "risk-demo", "风控经理",
                )
                assignment = session.query(ModelRiskReviewAssignmentRecord).filter_by(tenant_id=TENANT_ID, item_id=queue_item["id"]).one()
                self.assertEqual(assignment.assigned_to_name, "风险经理甲")
                first_version = assignment.row_version
                repository.bulk_assign_review_items(
                    TENANT_ID, [{"item_id": queue_item["id"], "expected_assignment_version": first_version}],
                    "risk-delegate", None, "risk_manager", "班次责任交接", "risk-demo", "风控经理",
                )
                assignment = session.query(ModelRiskReviewAssignmentRecord).filter_by(tenant_id=TENANT_ID, item_id=queue_item["id"]).one()
                repository.bulk_assign_review_items(
                    TENANT_ID, [{"item_id": queue_item["id"], "expected_assignment_version": assignment.row_version}],
                    None, None, "risk_manager", "撤回运营分派", "risk-demo", "风控经理",
                )
            self.assertIsNone(session.query(ModelRiskReviewAssignmentRecord).filter_by(tenant_id=TENANT_ID, item_id=queue_item["id"]).first())
            history = repository.review_assignment_history(TENANT_ID, queue_item["id"])
            self.assertEqual([item["action"] for item in history["items"]], ["assign", "handoff", "unassign"])
            self.assertEqual(history["items"][1]["previous"]["subject"], "risk-owner")
            self.assertEqual(history["items"][1]["next"]["subject"], "risk-delegate")
            self.assertTrue(all(row.tenant_id == TENANT_ID for row in session.query(AuditEventRecord).filter_by(aggregate_type="model_risk_review_assignment").all()))

    def test_assignment_rejects_role_mismatch_cross_tenant_and_stale_version(self):
        queue_item = self._queue_item()
        with database.SessionLocal() as session:
            repository = ModelRiskPolicyRepository(session)
            with patch.object(repository, "unified_review_queue", return_value=[queue_item]):
                with self.assertRaisesRegex(ModelRiskPolicyError, "责任角色"):
                    repository.bulk_assign_review_items(TENANT_ID, [{"item_id": queue_item["id"], "expected_assignment_version": 0}], "model-owner", None, "risk_manager", "角色不匹配测试", "risk-demo", "风控经理")
                with self.assertRaisesRegex(ModelRiskPolicyError, "当前租户"):
                    repository.bulk_assign_review_items(TENANT_ID, [{"item_id": queue_item["id"], "expected_assignment_version": 0}], "integration-alt-demo", None, "risk_manager", "跨租户分派测试", "risk-demo", "风控经理")
                repository.bulk_assign_review_items(TENANT_ID, [{"item_id": queue_item["id"], "expected_assignment_version": 0}], "risk-owner", None, "risk_manager", "正常分派测试", "risk-demo", "风控经理")
                with self.assertRaisesRegex(ModelRiskPolicyError, "已变化"):
                    repository.bulk_assign_review_items(TENANT_ID, [{"item_id": queue_item["id"], "expected_assignment_version": 0}], "risk-delegate", None, "risk_manager", "陈旧版本交接", "risk-demo", "风控经理")

    def test_diff_case_unassign_updates_native_owner_and_restores_open_state(self):
        case = TenantMonitoringDiffCaseRecord(
            id="case-native-owner", tenant_id=TENANT_ID, policy_id="policy-native", base_run_id="run-base",
            against_run_id="run-against", base_evidence_hash="a" * 64, against_evidence_hash="b" * 64,
            diff_hash="c" * 64, comparison_json={}, status="assigned", severity="warning", reason="差异责任撤回测试",
            assigned_role="risk_manager", assigned_to="risk-owner", assigned_to_name="风险经理甲",
            due_at=datetime.now(timezone.utc) + timedelta(days=2), recompute_status="not_started",
            created_by="risk-demo", created_by_name="风控经理",
        )
        queue_item = {**self._queue_item("monitoring_diff_case:case-native-owner", subject="risk-owner"), "source": "monitoring_diff_case", "diff_case_id": case.id}
        with database.SessionLocal() as session:
            session.add(case)
            session.commit()
            repository = ModelRiskPolicyRepository(session)
            with patch.object(repository, "unified_review_queue", return_value=[queue_item]):
                repository.bulk_assign_review_items(
                    TENANT_ID,
                    [{"item_id": queue_item["id"], "expected_assignment_version": 0, "expected_source_version": case.row_version}],
                    None, None, "risk_manager", "撤回差异工单分派", "risk-demo", "风控经理",
                )
            session.refresh(case)
            self.assertIsNone(case.assigned_to)
            self.assertIsNone(case.assigned_to_name)
            self.assertEqual(case.assigned_role, "risk_manager")
            self.assertEqual(case.status, "open")
            self.assertIsNone(session.query(ModelRiskReviewAssignmentRecord).filter_by(item_id=queue_item["id"]).first())

    def test_active_delegation_adds_proxy_items_to_my_workbench_and_revoke_removes_them(self):
        now = datetime.now(timezone.utc)
        queue_item = self._queue_item(subject="risk-owner")
        with database.SessionLocal() as session:
            repository = ModelRiskPolicyRepository(session)
            delegation = repository.create_review_delegation(TENANT_ID, {
                "principal_subject": "risk-owner", "delegate_subject": "risk-delegate", "assigned_role": "risk_manager",
                "starts_at": now - timedelta(minutes=5), "ends_at": now + timedelta(days=7), "reason": "休假期间代理复核",
            }, "risk-demo", "风控经理")
            with patch.object(repository, "unified_review_queue", return_value=[queue_item]):
                workbench = repository.review_queue_workbench(
                    TENANT_ID, ownership="mine", owner_subject="risk-delegate", viewer_subject="risk-delegate", now=now,
                )
                self.assertEqual(len(workbench["items"]), 1)
                self.assertTrue(workbench["items"][0]["delegated"])
                self.assertEqual(workbench["items"][0]["delegated_from"]["subject"], "risk-owner")
                expired = repository.review_queue_workbench(
                    TENANT_ID, ownership="mine", owner_subject="risk-delegate", viewer_subject="risk-delegate", now=now + timedelta(days=8),
                )
                self.assertEqual(expired["items"], [])
                repository.revoke_review_delegation(TENANT_ID, delegation["id"], delegation["row_version"], "原责任人提前返岗", "risk-demo", "风控经理")
                refreshed = repository.review_queue_workbench(
                    TENANT_ID, ownership="mine", owner_subject="risk-delegate", viewer_subject="risk-delegate", now=now,
                )
                self.assertEqual(refreshed["items"], [])

    def test_delegation_validates_members_roles_windows_overlap_and_tenant_scope(self):
        now = datetime.now(timezone.utc)
        payload = {
            "principal_subject": "risk-owner", "delegate_subject": "risk-delegate", "assigned_role": "risk_manager",
            "starts_at": now, "ends_at": now + timedelta(days=10), "reason": "运营班次代理安排",
        }
        with database.SessionLocal() as session:
            repository = ModelRiskPolicyRepository(session)
            created = repository.create_review_delegation(TENANT_ID, payload, "risk-demo", "风控经理")
            with self.assertRaisesRegex(ModelRiskPolicyError, "重叠"):
                repository.create_review_delegation(TENANT_ID, {**payload, "starts_at": now + timedelta(days=1)}, "risk-demo", "风控经理")
            with self.assertRaisesRegex(ModelRiskPolicyError, "不能是同一成员"):
                repository.create_review_delegation(TENANT_ID, {**payload, "principal_subject": "risk-owner", "delegate_subject": "risk-owner", "starts_at": now + timedelta(days=20), "ends_at": now + timedelta(days=21)}, "risk-demo", "风控经理")
            with self.assertRaisesRegex(ModelRiskPolicyError, "都必须具备"):
                repository.create_review_delegation(TENANT_ID, {**payload, "delegate_subject": "model-owner", "starts_at": now + timedelta(days=20), "ends_at": now + timedelta(days=21)}, "risk-demo", "风控经理")
            self.assertEqual(repository.list_review_delegations("tenant-demo-alt"), [])
            with self.assertRaisesRegex(ModelRiskPolicyError, "不存在"):
                repository.revoke_review_delegation("tenant-demo-alt", created["id"], created["row_version"], "跨租户撤销测试", "integration-alt-demo", "另一租户")

    def test_delegation_endpoints_enforce_review_permission(self):
        now = datetime.now(timezone.utc)
        payload = {
            "principal_subject": "risk-owner", "delegate_subject": "risk-delegate", "assigned_role": "risk_manager",
            "starts_at": now.isoformat(), "ends_at": (now + timedelta(days=1)).isoformat(), "reason": "接口权限校验代理",
        }
        with TestClient(app) as client:
            blocked = client.post("/api/v1/model-governance/risk-review-queue/delegations", json=payload, headers={"Authorization": "Bearer dev-client"})
            self.assertEqual(blocked.status_code, 403)
            created = client.post("/api/v1/model-governance/risk-review-queue/delegations", json=payload, headers={"Authorization": "Bearer dev-risk"})
            self.assertEqual(created.status_code, 201)
            self.assertEqual(created.json()["effective_status"], "active")


if __name__ == "__main__":
    unittest.main()
