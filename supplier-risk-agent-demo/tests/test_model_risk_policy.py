from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from uuid import uuid4
from unittest.mock import patch

import backend.database as database
from fastapi.testclient import TestClient
from backend.database import Base
from backend.db_models import AuditEventRecord, ModelChangeRecord, ModelMonitoringRunRecord, ModelReleaseRecord, ModelRiskAcceptanceRecord, ModelRiskReacceptanceRecord, ModelValidationReportIssuanceRecord, NotificationRecord, TenantModelRiskPolicyRecord, TenantRecord
from backend.model_risk_catalog import risk_catalog
from backend.model_risk_policy_repository import ModelRiskPolicyError, ModelRiskPolicyRepository
from backend.model_validation_issuance_repository import ModelValidationIssuanceRepository
from backend.main import app
from backend.repository import ModelGovernanceRepository, content_hash
from backend.storage import LocalObjectStorage
from scripts.verify_model_risk_reacceptance_regulatory_report import verify_regulatory_report
from tests.database_support import IsolatedTestDatabase


TENANT_ID = "tenant-demo-hengxin"


class TestModelRiskPolicy(unittest.TestCase):
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
            session.query(ModelValidationReportIssuanceRecord).delete()
            session.query(ModelRiskAcceptanceRecord).delete()
            session.query(ModelRiskReacceptanceRecord).delete()
            session.query(ModelMonitoringRunRecord).delete()
            session.query(ModelReleaseRecord).delete()
            session.query(NotificationRecord).filter(NotificationRecord.category.in_(["model_risk_review", "model_risk_reacceptance_review"])).delete()
            session.query(TenantModelRiskPolicyRecord).delete()
            session.query(ModelChangeRecord).delete()
            session.query(AuditEventRecord).delete()
            session.query(TenantRecord).filter(TenantRecord.id == TENANT_ID).delete()
            session.add(TenantRecord(id=TENANT_ID, name="衡信演示租户", deployment_mode="saas", status="active", data_region="cn"))
            session.commit()

    def test_policy_four_eyes_acceptance_roles_and_release_gate(self):
        with TemporaryDirectory() as directory, database.SessionLocal() as session:
            repository = ModelRiskPolicyRepository(session)
            policy = repository.create_policy(TENANT_ID, {
                "name": "企业信用模型风险政策", "description": "用于企业评级、授信和账期模型的分级治理政策。",
                "levels": risk_catalog(), "reason": "建立租户模型风险治理基线",
            }, "model-admin", "模型管理员")
            submitted = repository.submit_policy(TENANT_ID, policy["id"], policy["row_version"], "提交独立风险复核", "model-admin")
            with self.assertRaisesRegex(ModelRiskPolicyError, "不同人员"):
                repository.review_policy(TENANT_ID, policy["id"], submitted["row_version"], "publish", "批准发布该风险政策", "model-admin", "模型管理员")
            published = repository.review_policy(TENANT_ID, policy["id"], submitted["row_version"], "publish", "批准发布该风险政策", "risk-reviewer", "风控复核人")
            self.assertTrue(published["is_active"])
            self.assertEqual(repository.current_catalog(TENANT_ID)["version"], "tenant-v1")
            self.assertEqual(repository.current_catalog("tenant-demo-alt")["source"], "platform_default")
            self.assertEqual(repository.list_policies("tenant-demo-alt"), [])

            change = self._change(session, "high")
            storage = LocalObjectStorage(directory)
            with self.assertRaisesRegex(ValueError, "风险接受"):
                ModelValidationIssuanceRepository(session, storage).issue(TENANT_ID, change.id, "validator", "独立验证人")

            acceptance = repository.create_acceptance(TENANT_ID, change.id, "高风险自动授信模型需完成三席风险接受", "model-admin", "模型管理员")
            self.assertEqual(acceptance["required_roles"], ["model_owner", "risk_manager", "model_risk_committee"])
            self.assertEqual(repository.list_acceptances("tenant-demo-alt"), [])
            with self.assertRaisesRegex(ModelRiskPolicyError, "不存在"):
                repository.accept("tenant-demo-alt", acceptance["id"], acceptance["row_version"], "model_owner", "不应跨租户签署", "other", "其他租户", ("model_admin",))
            with self.assertRaisesRegex(ModelRiskPolicyError, "不具备"):
                repository.accept(TENANT_ID, acceptance["id"], acceptance["row_version"], "model_owner", "角色不匹配拒绝", "risk", "风控经理", ("risk_manager",))
            acceptance = repository.accept(TENANT_ID, acceptance["id"], acceptance["row_version"], "model_owner", "确认模型所有权及使用边界", "owner", "模型所有者", ("model_admin",))
            acceptance = repository.accept(TENANT_ID, acceptance["id"], acceptance["row_version"], "risk_manager", "确认验证证据和风险缓释措施", "risk", "风控经理", ("risk_manager",))
            acceptance = repository.accept(TENANT_ID, acceptance["id"], acceptance["row_version"], "model_risk_committee", "委员会确认剩余风险可以接受", "committee", "模型风险委员会", ("approver",))
            self.assertEqual(acceptance["effective_status"], "accepted")
            self.assertIsNotNone(acceptance["review_due_at"])

            issued = ModelValidationIssuanceRepository(session, storage).issue(TENANT_ID, change.id, "validator", "独立验证人")
            self.assertTrue(issued["trust_eligible"])
            classification = issued["package"]["risk_classification"]
            self.assertEqual(classification["catalog_source"], "tenant_policy")
            self.assertEqual(classification["catalog_version"], "tenant-v1")
            self.assertEqual(classification["risk_acceptance"]["id"], acceptance["id"])
            self.assertEqual(ModelGovernanceRepository(session)._assert_supervised_validation_evidence(change)["report_hash"], "r" * 64)

            revised_levels = risk_catalog()
            next(item for item in revised_levels if item["level"] == "high")["acceptance_roles"] = ["model_owner"]
            policy_v2 = repository.create_policy(TENANT_ID, {
                "name": "企业信用模型风险政策修订版", "description": "调整高风险模型接受席位并保留版本化治理证据。",
                "levels": revised_levels, "reason": "根据年度治理评估调整接受席位",
            }, "policy-maker-2", "政策制作者乙")
            policy_v2 = repository.submit_policy(TENANT_ID, policy_v2["id"], policy_v2["row_version"], "提交第二版政策独立复核", "policy-maker-2")
            repository.review_policy(TENANT_ID, policy_v2["id"], policy_v2["row_version"], "publish", "批准第二版政策生效", "policy-reviewer-2", "政策复核人乙")
            replacement_acceptance = repository.create_acceptance(TENANT_ID, change.id, "按新政策重新确认高风险模型剩余风险", "model-admin-2", "模型管理员乙")
            replacement_acceptance = repository.accept(TENANT_ID, replacement_acceptance["id"], replacement_acceptance["row_version"], "model_owner", "确认新版政策下的使用边界", "owner-2", "模型所有者乙", ("model_admin",))
            self.assertEqual(replacement_acceptance["effective_status"], "accepted")
            with self.assertRaisesRegex(ValueError, "未冻结当前模型风险政策"):
                ModelGovernanceRepository(session)._assert_supervised_validation_evidence(change)

    def test_overdue_acceptance_blocks_dashboard_and_policy_upgrade_revokes_it(self):
        with database.SessionLocal() as session:
            repository = ModelRiskPolicyRepository(session)
            policy = repository.create_policy(TENANT_ID, {
                "name": "模型风险政策", "description": "用于验证风险接受复核周期和政策升级失效行为。",
                "levels": risk_catalog(), "reason": "建立首版风险政策",
            }, "maker", "政策制作者")
            policy = repository.submit_policy(TENANT_ID, policy["id"], policy["row_version"], "提交首版政策复核", "maker")
            repository.review_policy(TENANT_ID, policy["id"], policy["row_version"], "publish", "同意首版政策发布", "reviewer", "政策复核人")
            change = self._change(session, "low")
            acceptance = repository.create_acceptance(TENANT_ID, change.id, "低风险辅助模型由模型所有者接受", "maker", "政策制作者")
            acceptance = repository.accept(TENANT_ID, acceptance["id"], acceptance["row_version"], "model_owner", "确认仅用于辅助预警排序", "owner", "模型所有者", ("model_admin",))
            row = session.get(ModelRiskAcceptanceRecord, acceptance["id"])
            row.review_due_at = datetime.now(timezone.utc) - timedelta(days=1)
            session.commit()
            self.assertEqual(repository.current_acceptance_snapshot(TENANT_ID, change.id, required=False)["effective_status"], "overdue")

            next_policy = repository.create_policy(TENANT_ID, {
                "name": "模型风险政策修订版", "description": "调整后继续保持三级风险目录及风险接受治理要求。",
                "levels": risk_catalog(), "reason": "启动年度政策修订",
            }, "maker-2", "政策制作者乙")
            next_policy = repository.submit_policy(TENANT_ID, next_policy["id"], next_policy["row_version"], "提交年度政策复核", "maker-2")
            repository.review_policy(TENANT_ID, next_policy["id"], next_policy["row_version"], "publish", "批准年度政策更新", "reviewer-2", "政策复核人乙")
            session.refresh(row)
            self.assertEqual(row.status, "revoked")
            self.assertIn("政策已更新", row.revocation_reason)

    def test_policy_api_enforces_tenant_and_review_permissions(self):
        with TestClient(app) as client:
            catalog = client.get("/api/v1/model-governance/risk-catalog", headers={"Authorization": "Bearer dev-model-admin"})
            self.assertEqual(catalog.status_code, 200, catalog.text)
            self.assertEqual(catalog.json()["source"], "platform_default")
            payload = {
                "name": "企业信用模型风险政策", "description": "租户模型验证、风险接受和定期复核治理政策。",
                "levels": risk_catalog(), "reason": "建立租户模型风险政策基线",
            }
            blocked = client.post("/api/v1/model-governance/risk-policies", json=payload, headers={"Authorization": "Bearer dev-risk"})
            self.assertEqual(blocked.status_code, 403)
            created = client.post("/api/v1/model-governance/risk-policies", json=payload, headers={"Authorization": "Bearer dev-model-admin"})
            self.assertEqual(created.status_code, 201, created.text)
            item = created.json()
            other_tenant = client.get("/api/v1/model-governance/risk-policies", headers={"Authorization": "Bearer dev-integration-alt"})
            self.assertEqual(other_tenant.status_code, 200, other_tenant.text)
            self.assertEqual(other_tenant.json(), [])
            submitted = client.post(f"/api/v1/model-governance/risk-policies/{item['id']}/submit", json={"expected_row_version": item["row_version"], "reason": "提交政策独立复核"}, headers={"Authorization": "Bearer dev-model-admin"})
            self.assertEqual(submitted.status_code, 200, submitted.text)
            self_review = client.post(f"/api/v1/model-governance/risk-policies/{item['id']}/review", json={"expected_row_version": submitted.json()["row_version"], "decision": "publish", "comment": "批准发布政策版本"}, headers={"Authorization": "Bearer dev-model-admin"})
            self.assertEqual(self_review.status_code, 403)
            reviewed = client.post(f"/api/v1/model-governance/risk-policies/{item['id']}/review", json={"expected_row_version": submitted.json()["row_version"], "decision": "publish", "comment": "批准发布政策版本"}, headers={"Authorization": "Bearer dev-risk"})
            self.assertEqual(reviewed.status_code, 200, reviewed.text)
            self.assertEqual(reviewed.json()["status"], "published")

    def test_review_queue_scan_deduplicates_and_preserves_acceptance(self):
        with database.SessionLocal() as session:
            repository = ModelRiskPolicyRepository(session)
            policy = repository.create_policy(TENANT_ID, {
                "name": "定期复核测试政策", "description": "期限扫描测试", "levels": risk_catalog(),
                "reason": "验证模型风险定期复核提醒",
            }, "maker", "政策制作者")
            submitted = repository.submit_policy(TENANT_ID, policy["id"], policy["row_version"], "提交独立政策复核", "maker")
            repository.review_policy(TENANT_ID, policy["id"], submitted["row_version"], "publish", "批准复核政策发布", "reviewer", "政策复核人")
            change = self._change(session, "low")
            acceptance = repository.create_acceptance(TENANT_ID, change.id, "低风险模型所有者承担定期复核责任", "creator", "台账发起人")
            acceptance = repository.accept(TENANT_ID, acceptance["id"], acceptance["row_version"], "model_owner", "确认到期后重新验证", "owner", "模型所有者", ("model_admin",))
            now = datetime(2026, 9, 22, tzinfo=timezone.utc)
            row = session.get(ModelRiskAcceptanceRecord, acceptance["id"])
            row.review_due_at = now + timedelta(days=6)
            session.commit()

            queue = repository.review_queue(TENANT_ID, now)
            self.assertEqual(len(queue), 1)
            self.assertEqual(queue[0]["level"], "due_soon")
            self.assertEqual({person["subject"] for person in queue[0]["responsible"]}, {"creator", "owner"})
            unified = repository.unified_review_queue(TENANT_ID, template_key="general", now=now)
            self.assertEqual([(item["source"], item["priority"]) for item in unified], [("risk_acceptance", "P3")])
            self.assertEqual(repository.unified_review_queue(TENANT_ID, template_key="other", now=now), [])
            self.assertEqual(repository.review_queue("tenant-demo-alt", now), [])
            first = repository.scan_reviews(TENANT_ID, "scheduler", now)
            self.assertEqual(first["notifications_created"], 2)
            self.assertEqual(repository.scan_reviews(TENANT_ID, "scheduler", now)["notifications_created"], 0)
            self.assertEqual(session.get(ModelRiskAcceptanceRecord, acceptance["id"]).status, "accepted")
            overdue = repository.scan_reviews(TENANT_ID, "scheduler", now + timedelta(days=7))
            self.assertEqual(overdue["overdue"], 1)
            self.assertEqual(overdue["notifications_created"], 2)
            self.assertEqual(overdue["notifications_resolved"], 2)
            self.assertEqual(repository.current_acceptance_snapshot(TENANT_ID, change.id, required=False)["effective_status"], "accepted")
            self.assertEqual(len(session.query(NotificationRecord).filter(NotificationRecord.category == "model_risk_review").all()), 4)
            repository.revoke_acceptance(TENANT_ID, acceptance["id"], session.get(ModelRiskAcceptanceRecord, acceptance["id"]).row_version, "复核证据需重新采集", "reviewer", "政策复核人")
            after_revoke = repository.scan_reviews(TENANT_ID, "scheduler", now + timedelta(days=8))
            self.assertEqual(after_revoke["items_scanned"], 0)
            self.assertEqual(after_revoke["notifications_resolved"], 2)

    def test_review_scan_api_permissions_and_tenant_queue(self):
        with TestClient(app) as client:
            denied = client.post("/api/v1/model-governance/risk-acceptances/review-scan", headers={"Authorization": "Bearer dev-model-admin"})
            self.assertEqual(denied.status_code, 403)
            queue = client.get("/api/v1/model-governance/risk-acceptances/review-queue", headers={"Authorization": "Bearer dev-model-admin"})
            self.assertEqual(queue.status_code, 200, queue.text)
            self.assertEqual(queue.json(), [])
            invalid = client.get("/api/v1/model-governance/risk-acceptances/review-queue?horizon_days=91", headers={"Authorization": "Bearer dev-model-admin"})
            self.assertEqual(invalid.status_code, 422)
            unified = client.get("/api/v1/model-governance/risk-review-queue?template_key=general", headers={"Authorization": "Bearer dev-model-admin"})
            self.assertEqual(unified.status_code, 200, unified.text)
            self.assertEqual(unified.json(), [])
            invalid_unified = client.get("/api/v1/model-governance/risk-review-queue?horizon_days=91", headers={"Authorization": "Bearer dev-model-admin"})
            self.assertEqual(invalid_unified.status_code, 422)
            other = client.post("/api/v1/model-governance/risk-acceptances/review-scan", headers={"Authorization": "Bearer dev-risk"})
            self.assertEqual(other.status_code, 200, other.text)
            self.assertEqual(other.json()["items_scanned"], 0)

    def test_in_service_reacceptance_freezes_runtime_evidence_and_gates_overdue_release(self):
        with database.SessionLocal() as session:
            repository = ModelRiskPolicyRepository(session)
            policy = repository.create_policy(TENANT_ID, {
                "name": "在役再接受政策", "description": "用于验证已发布模型运行期的独立再接受流程。", "levels": risk_catalog(),
                "reason": "建立运行期模型风险复核基线",
            }, "maker", "政策制作者")
            policy = repository.submit_policy(TENANT_ID, policy["id"], policy["row_version"], "提交运行期政策复核", "maker")
            repository.review_policy(TENANT_ID, policy["id"], policy["row_version"], "publish", "批准运行期政策", "reviewer", "政策复核人")
            change = self._change(session, "low")
            acceptance = repository.create_acceptance(TENANT_ID, change.id, "低风险已发布模型进入运行期治理", "creator", "台账发起人")
            acceptance = repository.accept(TENANT_ID, acceptance["id"], acceptance["row_version"], "model_owner", "确认初始发布风险", "owner", "模型所有者", ("model_admin",))
            change.status = "published"
            change.published_at = datetime.now(timezone.utc)
            release = ModelReleaseRecord(id=str(uuid4()), template_key=change.template_key, model_version=change.candidate_version,
                                         config_json={"version": change.candidate_version}, config_hash="c" * 64,
                                         source_change_id=change.id, is_active=True, published_by="reviewer")
            session.add(release)
            session.commit()
            prior = session.get(ModelRiskAcceptanceRecord, acceptance["id"])
            prior.review_due_at = datetime.now(timezone.utc) - timedelta(days=1)
            session.commit()

            blocked = repository.in_service_release_status(TENANT_ID, release.id)
            self.assertEqual(blocked["effective_status"], "required")
            created = repository.create_reacceptance(TENANT_ID, release.id, {
                "rationale": "已发布模型完成运行窗口复核，继续接受其低风险用途。",
                "observed_from": date(2026, 8, 1), "observed_to": date(2026, 9, 22),
                "evidence_reference": "monitoring-run:general:2026-09",
                "evidence_summary": "运行期监控窗口内数据完整性、稳定性和人工复核闭环均已由模型验证组核验。",
            }, "creator-2", "再接受发起人")
            self.assertEqual(created["effective_status"], "pending")
            self.assertEqual(repository.in_service_release_status(TENANT_ID, release.id)["effective_status"], "pending")
            with self.assertRaisesRegex(ModelRiskPolicyError, "非监督"):
                repository.accept_reacceptance(TENANT_ID, created["id"], created["row_version"], "model_owner", "手工证据不得正式签署", "owner-2", "模型所有者乙", ("model_admin",))
            repository.revoke_reacceptance(TENANT_ID, created["id"], created["row_version"], "绑定真实结果运行证据后重新发起", "reviewer", "政策复核人")
            run = self._monitoring_run(session, "general", "v2", "first-in-service")
            created = repository.create_reacceptance(TENANT_ID, release.id, {
                "rationale": "已发布模型绑定真实结果监控，继续接受低风险用途。",
                "observed_from": date(2026, 8, 1), "observed_to": date(2026, 9, 22),
                "evidence_reference": "monitoring-run:general:2026-09",
                "evidence_summary": "运行期真实结果满足监督回溯样本门槛，模型验证组已核验稳定性与区分度。",
                "monitoring_run_id": run.id, "monitoring_evidence_hash": repository._monitoring_evidence_hash(run),
            }, "creator-3", "再接受发起人乙")
            with self.assertRaisesRegex(ModelRiskPolicyError, "共享监控"):
                repository.accept_reacceptance(TENANT_ID, created["id"], created["row_version"], "model_owner", "共享监控不能签署", "owner-2", "模型所有者乙", ("model_admin",))
            # Historic signed records remain readable and gated by their original expiry.
            record = session.get(ModelRiskReacceptanceRecord, created["id"])
            record.status = "accepted"
            record.accepted_at = datetime.now(timezone.utc)
            record.review_due_at = datetime.now(timezone.utc) + timedelta(days=30)
            session.commit()
            created = repository._reacceptance_view(record)
            self.assertEqual(created["effective_status"], "accepted")
            status = repository.in_service_release_status(TENANT_ID, release.id, required=True)
            self.assertEqual(status["effective_status"], "accepted")
            self.assertEqual(status["reacceptance"]["operational_evidence"]["evidence_reference"], "monitoring-run:general:2026-09")

            record = session.get(ModelRiskReacceptanceRecord, created["id"])
            record.release_config_hash = "d" * 64
            session.commit()
            self.assertEqual(repository.in_service_release_status(TENANT_ID, release.id)["effective_status"], "release_stale")
            with self.assertRaisesRegex(ModelRiskPolicyError, "发布配置"):
                repository.in_service_release_status(TENANT_ID, release.id, required=True)

    def test_monitoring_binding_requires_hash_and_supervised_labels_and_exports_audit_package(self):
        with database.SessionLocal() as session:
            repository = ModelRiskPolicyRepository(session)
            policy = repository.create_policy(TENANT_ID, {
                "name": "监控绑定政策", "description": "验证在役再接受绑定模型监控运行和监督标签。", "levels": risk_catalog(),
                "reason": "建立监控证据强绑定规则",
            }, "maker", "政策制作者")
            policy = repository.submit_policy(TENANT_ID, policy["id"], policy["row_version"], "提交监控绑定政策复核", "maker")
            repository.review_policy(TENANT_ID, policy["id"], policy["row_version"], "publish", "批准监控绑定政策", "reviewer", "政策复核人")
            change = self._change(session, "low")
            acceptance = repository.create_acceptance(TENANT_ID, change.id, "低风险模型完成初始风险接受并准备运行监控。", "maker", "制作者")
            acceptance = repository.accept(TENANT_ID, acceptance["id"], acceptance["row_version"], "model_owner", "确认初始模型边界", "owner", "模型所有者", ("model_admin",))
            change.status = "published"
            change.published_at = datetime.now(timezone.utc)
            release = ModelReleaseRecord(id=str(uuid4()), template_key=change.template_key, model_version=change.candidate_version,
                                         config_json={"version": change.candidate_version}, config_hash="c" * 64,
                                         source_change_id=change.id, is_active=True, published_by="reviewer")
            session.add(release)
            run = ModelMonitoringRunRecord(
                id=str(uuid4()), run_key="run-binding-test", template_key="general", model_version="v2", as_of_period="2026Q3",
                trigger_type="manual", status="completed", effective_source="observed_outcome", evidence_level="observed_outcome",
                dataset_id="observed-general-2026Q2-2026Q3", readiness_json={"formal_backtest_ready": True},
                monitoring_json={"population_stability": {"value": 0.08}, "backtesting": {"status": "ready", "event_count": 8, "non_event_count": 24},
                                 "performance_metrics": [{"key": "ks", "value": 0.31}, {"key": "auc", "value": 0.74}, {"key": "brier", "value": 0.12}]},
                issue_ids=[], actor="monitoring", completed_at=datetime.now(timezone.utc),
            )
            session.add(run)
            session.commit()
            run_hash = repository._monitoring_evidence_hash(run)
            created = repository.create_reacceptance(TENANT_ID, release.id, {
                "rationale": "运行窗口达到监督回溯门槛，绑定监控结果完成在役再接受。", "observed_from": date(2026, 8, 1), "observed_to": date(2026, 9, 22),
                "evidence_reference": "monitoring-run:run-binding-test", "evidence_summary": "监控运行包含足量事件和非事件标签，并已完成 PSI、KS、AUC 与 Brier 复核。",
                "monitoring_run_id": run.id, "monitoring_evidence_hash": run_hash, "label_evidence_id": "label-definition-q3",
            }, "creator", "再接受发起人")
            self.assertEqual(created["operational_evidence"]["monitoring_binding"]["evidence_level"], "supervised")
            with self.assertRaisesRegex(ModelRiskPolicyError, "共享监控"):
                repository.accept_reacceptance(TENANT_ID, created["id"], created["row_version"], "model_owner", "共享批次不能签署", "owner", "模型所有者", ("model_admin",))
            package = repository.audit_package(TENANT_ID, created["id"])
            self.assertEqual(package["monitoring_run"]["evidence_hash"], run_hash)
            self.assertEqual(len(package["package_hash"]), 64)
            regulatory = repository.audit_package(TENANT_ID, created["id"], "regulatory")
            self.assertEqual(regulatory["schema_version"], "model-risk-reacceptance-regulatory-report-v1")
            self.assertEqual(regulatory["integrity"]["package_hash"], package["package_hash"])
            self.assertEqual(regulatory["evidence"]["downgrade"]["status"], "non_supervised")
            self.assertEqual(regulatory["runtime_impact"]["status"], "at_risk")
            self.assertTrue(regulatory["signing"]["signature_valid"])
            self.assertTrue(verify_regulatory_report(regulatory, regulatory["report_hash"], package["package_hash"])["verified"])
            tampered_regulatory = dict(regulatory, model={**regulatory["model"], "model_version": "tampered"})
            self.assertFalse(verify_regulatory_report(tampered_regulatory)["verified"])
            with self.assertRaisesRegex(ModelRiskPolicyError, "仅支持"):
                repository.audit_package(TENANT_ID, created["id"], "csv")
            repository.record_audit_package_download(TENANT_ID, created["id"], package["package_hash"], "full", "auditor", "审计人员")
            package_after_download = repository.audit_package(TENANT_ID, created["id"])
            self.assertEqual(package_after_download["package_hash"], package["package_hash"])
            download_event = session.query(AuditEventRecord).filter(
                AuditEventRecord.aggregate_id == created["id"],
                AuditEventRecord.event_type == "model_risk_reacceptance_audit_package_downloaded",
            ).one()
            self.assertEqual(download_event.payload["format"], "full")

            revoked = repository.revoke_reacceptance(TENANT_ID, created["id"], created["row_version"], "切换到无标签代理运行验证", "reviewer", "政策复核人")
            run.evidence_level = "simulation_proxy"
            session.commit()
            created = repository.create_reacceptance(TENANT_ID, release.id, {
                "rationale": "验证无标签运行被明确降级，不能作为正式监督再接受。", "observed_from": date(2026, 8, 1), "observed_to": date(2026, 9, 22),
                "evidence_reference": "monitoring-run:run-binding-test-proxy", "evidence_summary": "该监控运行只有模拟代理数据，没有足量真实结果标签，因此仅用于非监督稳定性观察。",
                "monitoring_run_id": run.id, "monitoring_evidence_hash": repository._monitoring_evidence_hash(run),
            }, "creator-2", "再接受发起人乙")
            with self.assertRaisesRegex(ModelRiskPolicyError, "非监督"):
                repository.accept_reacceptance(TENANT_ID, created["id"], created["row_version"], "model_owner", "拒绝无标签监督签署", "owner-2", "模型所有者乙", ("model_admin",))

    def test_reacceptance_renews_without_downtime_and_review_reminders_deduplicate(self):
        with database.SessionLocal() as session:
            repository = ModelRiskPolicyRepository(session)
            policy = repository.create_policy(TENANT_ID, {
                "name": "在役续期政策", "description": "验证提前续期与到期提醒。", "levels": risk_catalog(),
                "reason": "建立在役续期责任队列",
            }, "maker", "政策制作者")
            policy = repository.submit_policy(TENANT_ID, policy["id"], policy["row_version"], "提交在役续期复核", "maker")
            repository.review_policy(TENANT_ID, policy["id"], policy["row_version"], "publish", "批准在役续期政策", "reviewer", "政策复核人")
            change = self._change(session, "low")
            acceptance = repository.create_acceptance(TENANT_ID, change.id, "初始模型风险接受用于在役续期测试。", "maker", "制作者")
            repository.accept(TENANT_ID, acceptance["id"], acceptance["row_version"], "model_owner", "确认初始使用边界", "owner", "模型所有者", ("model_admin",))
            change.status = "published"
            change.published_at = datetime.now(timezone.utc)
            release = ModelReleaseRecord(id=str(uuid4()), template_key="general", model_version="v2",
                                         config_json={"version": "v2"}, config_hash="c" * 64,
                                         source_change_id=change.id, is_active=True, published_by="reviewer")
            session.add(release)
            session.commit()
            session.get(ModelRiskAcceptanceRecord, acceptance["id"]).review_due_at = datetime.now(timezone.utc) - timedelta(days=1)
            session.commit()
            payload = {"rationale": "运行监控结果已复核，按政策完成周期再接受。", "observed_from": date(2026, 8, 1),
                       "observed_to": date(2026, 9, 22), "evidence_reference": "monitoring:period-one",
                       "evidence_summary": "第一期运行稳定性与独立人工复核完成，作为历史兼容快照。"}
            first_run = self._monitoring_run(session, "general", "v2", "renewal-period-one")
            payload.update(monitoring_run_id=first_run.id, monitoring_evidence_hash=repository._monitoring_evidence_hash(first_run))
            binding = {"evidence_level": "supervised", "evaluation_id": "test-evaluation", "evidence_hash": "e" * 64}
            with patch.object(repository, "_supervised_binding", return_value=binding):
                payload.update(supervised_evaluation_id="test-evaluation", supervised_evidence_hash="e" * 64)
                first = repository.create_reacceptance(TENANT_ID, release.id, payload, "creator", "发起人")
                first = repository.accept_reacceptance(TENANT_ID, first["id"], first["row_version"], "model_owner", "确认首次运行边界", "owner-2", "所有者乙", ("model_admin",))
            now = datetime.now(timezone.utc)
            session.get(ModelRiskReacceptanceRecord, first["id"]).review_due_at = now + timedelta(days=6)
            session.commit()

            # This test isolates renewal transitions; tenant evidence validation is covered by outcome integration tests.
            with patch.object(repository, "_supervised_binding", return_value=binding):
                self._assert_renewal_flow(repository, session, release, first, payload, now)

    def _assert_renewal_flow(self, repository, session, release, first, payload, now):
        queue = repository.reacceptance_review_queue(TENANT_ID, now)
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["level"], "due_soon")
        self.assertEqual(queue[0]["runtime_impact"], "at_risk")
        unified = repository.unified_review_queue(TENANT_ID, template_key="general", now=now)
        renewal_item = next(item for item in unified if item["source"] == "risk_reacceptance")
        self.assertEqual((renewal_item["priority"], renewal_item["model_version"]), ("P3", "v2"))
        self.assertEqual(repository.reacceptance_review_queue("tenant-demo-alt", now), [])
        scan = repository.scan_reacceptance_reviews(TENANT_ID, "scheduler", now)
        self.assertEqual(scan["notifications_created"], 2)
        self.assertEqual(session.query(AuditEventRecord).filter(
            AuditEventRecord.aggregate_type == "tenant_model_risk_reacceptance_review_scan").first().tenant_id, TENANT_ID)
        self.assertEqual(repository.scan_reacceptance_reviews(TENANT_ID, "scheduler", now)["notifications_created"], 0)
        self.assertNotIn("非监督", session.query(NotificationRecord).filter(NotificationRecord.category == "model_risk_reacceptance_review").first().message)

        second_run = self._monitoring_run(session, "general", "v2", "renewal-period-two")
        renewed_payload = {**payload, "evidence_reference": "monitoring:period-two",
                           "evidence_summary": "第二期独立运行复核完成，提前续期并保持旧结论有效。",
                           "monitoring_run_id": second_run.id,
                           "monitoring_evidence_hash": repository._monitoring_evidence_hash(second_run)}
        renewal = repository.create_reacceptance(TENANT_ID, release.id, renewed_payload, "creator-2", "发起人乙")
        self.assertEqual(repository.create_reacceptance(TENANT_ID, release.id, renewed_payload, "creator-2", "发起人乙")["id"], renewal["id"])
        with self.assertRaisesRegex(ModelRiskPolicyError, "待签续期"):
            repository.create_reacceptance(TENANT_ID, release.id, {**renewed_payload, "evidence_reference": "another"}, "creator-3", "发起人丙")
        self.assertEqual(repository.in_service_release_status(TENANT_ID, release.id, required=True)["reacceptance"]["id"], first["id"])
        self.assertEqual(repository.in_service_release_status(TENANT_ID, release.id)["pending_renewal"]["id"], renewal["id"])
        self.assertEqual(repository.reacceptance_review_queue(TENANT_ID, now)[0]["pending_renewal_id"], renewal["id"])
        renewal = repository.accept_reacceptance(TENANT_ID, renewal["id"], renewal["row_version"], "model_owner", "确认续期运行边界", "owner-3", "所有者丙", ("model_admin",))
        self.assertEqual(renewal["status"], "accepted")
        self.assertEqual(session.get(ModelRiskReacceptanceRecord, first["id"]).status, "revoked")
        self.assertEqual(repository.in_service_release_status(TENANT_ID, release.id, required=True)["reacceptance"]["id"], renewal["id"])
        self.assertEqual(repository.scan_reacceptance_reviews(TENANT_ID, "scheduler", now)["notifications_resolved"], 2)

        session.get(ModelRiskReacceptanceRecord, renewal["id"]).review_due_at = now - timedelta(days=1)
        session.commit()
        self.assertEqual(repository.reacceptance_review_queue(TENANT_ID, now)[0]["runtime_impact"], "blocked")
        overdue_item = next(item for item in repository.unified_review_queue(TENANT_ID, template_key="general", now=now) if item["source"] == "risk_reacceptance")
        self.assertEqual(overdue_item["priority"], "P2")
        self.assertEqual(repository.scan_reacceptance_reviews(TENANT_ID, "scheduler", now)["notifications_created"], 2)
        with self.assertRaisesRegex(ModelRiskPolicyError, "超过复核期限"):
            repository.in_service_release_status(TENANT_ID, release.id, required=True)

    def test_reacceptance_review_api_permissions(self):
        with TestClient(app) as client:
            queue = client.get("/api/v1/model-governance/risk-reacceptances/review-queue", headers={"Authorization": "Bearer dev-model-admin"})
            self.assertEqual(queue.status_code, 200, queue.text)
            self.assertEqual(queue.json(), [])
            invalid = client.get("/api/v1/model-governance/risk-reacceptances/review-queue?horizon_days=91", headers={"Authorization": "Bearer dev-model-admin"})
            self.assertEqual(invalid.status_code, 422)
            denied = client.post("/api/v1/model-governance/risk-reacceptances/review-scan", headers={"Authorization": "Bearer dev-model-admin"})
            self.assertEqual(denied.status_code, 403)
            self.assertEqual(client.post("/api/v1/model-governance/risk-reacceptances/review-scan", headers={"Authorization": "Bearer dev-risk"}).status_code, 200)

    @staticmethod
    def _change(session, risk_level: str) -> ModelChangeRecord:
        evidence = {
            "tenant_id": TENANT_ID, "evaluation_id": str(uuid4()), "report_hash": "r" * 64,
            "report_template_version": "supervised-model-validation-v2", "evidence_level": "supervised",
            "independent_validation": {"status": "approved", "risk_level": risk_level, "attachments": []},
        }
        change = ModelChangeRecord(
            id=str(uuid4()), template_key="general", base_version="v1", candidate_version="v2",
            status="draft", config_json={"version": "v2"}, validation_json={"config_hash": "c" * 64},
            impact_json={}, comparison_evidence_json={}, change_reason="模型风险政策测试",
            created_by="maker", created_by_name="制作者", entity_type="model",
            supervised_validation_evidence_json=evidence, supervised_validation_binding_hash=content_hash(evidence),
        )
        session.add(change)
        session.commit()
        session.refresh(change)
        return change

    @staticmethod
    def _monitoring_run(session, template_key: str, model_version: str, run_key: str) -> ModelMonitoringRunRecord:
        run = ModelMonitoringRunRecord(
            id=str(uuid4()), run_key=run_key, template_key=template_key, model_version=model_version, as_of_period="2026Q3",
            trigger_type="manual", status="completed", effective_source="observed_outcome", evidence_level="observed_outcome",
            dataset_id=f"observed-{run_key}", readiness_json={"formal_backtest_ready": True},
            monitoring_json={"population_stability": {"value": 0.08},
                             "backtesting": {"status": "ready", "event_count": 8, "non_event_count": 24},
                             "performance_metrics": [{"key": "ks", "value": 0.31}, {"key": "auc", "value": 0.74}, {"key": "brier", "value": 0.12}]},
            issue_ids=[], actor="monitoring", completed_at=datetime.now(timezone.utc),
        )
        session.add(run)
        session.commit()
        return run


if __name__ == "__main__":
    unittest.main()
