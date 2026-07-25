from __future__ import annotations

import unittest
import hashlib
import io
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from unittest.mock import patch
import zipfile

from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

import backend.database as database
from backend.db_models import ApprovalCaseRecord, CreditFacilityRecord, CreditReportRecord, ModelReleaseRecord, RatingRunRecord
from backend.dependencies import demo_repository, get_object_storage
from backend.main import app
from backend.repository import ModelMonitoringRepository, RatingRunRepository, clear_persistent_data, content_hash
from backend.storage import LocalObjectStorage
from rating.scorecard import rate_counterparty
from tests.database_support import IsolatedTestDatabase


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.test_database = IsolatedTestDatabase()
        cls.test_database.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.test_database.stop()

    def setUp(self) -> None:
        with database.SessionLocal() as session:
            clear_persistent_data(session)
        self.temp_storage = TemporaryDirectory()
        app.dependency_overrides[get_object_storage] = lambda: LocalObjectStorage(self.temp_storage.name)
        self.client = TestClient(app)
        self.counterparty = demo_repository.list_counterparties()[0]
        self.headers = {"Authorization": "Bearer dev-admin"}

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.temp_storage.cleanup()

    def _review_document(self, document: dict, decision: str = "verify") -> dict:
        labels = {
            "integrity": "文件格式与指纹完整",
            "entity_match": "企业名称及统一信用代码一致",
            "validity": "证照、报告或证明仍在有效期",
            "completeness": "关键页、签章和附件完整",
            "legibility": "内容清晰可读且不存在明显涂改",
        }
        checks = [
            {"key": key, "label": label, "status": "pass", "note": "自动化测试核验通过"}
            for key, label in labels.items()
        ]
        response = self.client.post(
            f"/api/v1/documents/{document['id']}/review",
            json={"decision": decision, "comment": "逐项检查完成", "checks": checks, "expected_row_version": document["row_version"]},
            headers={"Authorization": "Bearer dev-risk"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _seed_completed_report_case(self, case_id: str = "CASE-CREDIT-REPORT-001") -> dict:
        config = demo_repository.get_template("general")
        result = rate_counterparty(self.counterparty, config)
        approved_limit = min(float(result["suggested_limit"]), 100000.0)
        with database.SessionLocal() as session:
            record = ApprovalCaseRecord(
                case_id=case_id,
                counterparty_id=self.counterparty["id"],
                counterparty_name=self.counterparty["name"],
                current_stage="final_strategy",
                status="已完成",
                completed_stages=["registration", "document_upload", "supplement", "approval_submit", "model_selection", "scoring", "credit_proposal", "final_strategy"],
                case_data={},
                timeline=[
                    {"环节": "客户注册", "处理人": "客户经理", "处理时间": "2026-07-16 09:00:00", "处理结果": "企业主体注册完成"},
                    {"环节": "形成评分", "处理人": "风控经理", "处理时间": "2026-07-16 10:00:00", "处理结果": f"形成 {result['rating']} 级可信评分"},
                    {"环节": "最终策略", "处理人": "授信审批人", "处理时间": "2026-07-16 11:00:00", "处理结果": "最终授信策略审批通过"},
                ],
            )
            session.add(record)
            session.commit()
            run = RatingRunRepository(session).save_run(self.counterparty, "general", config, result, actor="风控经理", case_id=case_id)
            record = session.get(ApprovalCaseRecord, case_id)
            record.case_data = {
                "registration": {"registered_name": self.counterparty["name"], "unified_social_credit_code": self.counterparty["credit_code"]},
                "approval_submit": {"business_type": "供应链赊销", "requested_limit": self.counterparty["requested_limit"], "requested_term_days": 30},
                "model_selection": {"template_key": "general", "model_name": config["name"], "model_version": config["version"]},
                "scoring": {"total_score": result["total_score"], "rating": result["rating"], "rating_run_id": run["id"], "model_snapshot_id": run["model_snapshot_id"], "result_hash": run["result_hash"]},
                "credit_proposal": {"suggested_limit": result["suggested_limit"], "suggested_payment_term_days": result["suggested_payment_term_days"], "rating_run_id": run["id"], "access_strategy": result["access_strategy"], "monitoring_frequency": result["monitoring_frequency"]},
                "final_strategy": {"decision": "通过", "access_strategy": result["access_strategy"], "approved_limit": approved_limit, "approved_payment_term_days": result["suggested_payment_term_days"], "monitoring_frequency": result["monitoring_frequency"], "facility_validity_days": 365},
            }
            session.commit()
        return {"case_id": case_id, "result": result, "approved_limit": approved_limit}

    def test_health_and_counterparty_endpoints(self) -> None:
        health = self.client.get("/api/v1/health")
        counterparties = self.client.get("/api/v1/counterparties", headers=self.headers)

        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")
        self.assertEqual(counterparties.status_code, 200)
        self.assertGreaterEqual(len(counterparties.json()), 1)

    def test_enterprise_indicator_pool_and_tech_model_are_exposed(self) -> None:
        model_admin = {"Authorization": "Bearer dev-model-admin"}
        pool = self.client.get("/api/v1/indicator-pool", headers=model_admin)
        searched = self.client.get("/api/v1/indicator-pool?q=股东变更", headers=model_admin)
        tech = self.client.get("/api/v1/models/tech_enterprise_basic", headers=model_admin)

        self.assertEqual(pool.status_code, 200)
        self.assertEqual(pool.json()["result_count"], 185)
        self.assertEqual(pool.json()["summary"]["indicator_count"], 185)
        self.assertTrue(any(item["name"] == "股东变更" for item in searched.json()["indicators"]))
        self.assertGreaterEqual(len(tech.json()["editable_indicators"]), 19)
        self.assertGreaterEqual(len(tech.json()["indicator_selection"]), 3)

    def test_portfolio_rating_batch_is_traceable_filterable_and_idempotent(self) -> None:
        manager = {"Authorization": "Bearer dev-manager"}
        auditor = {"Authorization": "Bearer dev-auditor"}
        approver = {"Authorization": "Bearer dev-approver"}
        payload = {"batch_key": "PORTFOLIO-TEST-001", "template_key": "general", "counterparty_type": "all"}

        forbidden = self.client.post("/api/v1/ratings/batches", json={**payload, "batch_key": "PORTFOLIO-FORBIDDEN"}, headers=approver)
        created = self.client.post("/api/v1/ratings/batches", json=payload, headers=manager)

        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(created.status_code, 201, created.text)
        batch = created.json()
        self.assertFalse(batch["idempotent"])
        self.assertEqual(batch["candidate_count"], len(demo_repository.list_counterparties()))
        self.assertEqual(batch["success_count"], batch["summary"]["success_count"])
        self.assertEqual(len(batch["results"]), batch["success_count"])
        self.assertTrue(batch["model_snapshot_id"])
        self.assertTrue(batch["result_hash"])
        self.assertTrue(all(item["rating_run_id"] for item in batch["results"]))
        self.assertIn("rating_distribution", batch["summary"])
        self.assertIn("watchlist", batch["summary"])

        runs_before = self.client.get("/api/v1/ratings/runs", headers=auditor).json()
        repeated = self.client.post("/api/v1/ratings/batches", json=payload, headers=manager)
        runs_after = self.client.get("/api/v1/ratings/runs", headers=auditor).json()
        self.assertEqual(repeated.status_code, 201)
        self.assertTrue(repeated.json()["idempotent"])
        self.assertEqual(len(runs_after), len(runs_before))

        changed_request = self.client.post(
            "/api/v1/ratings/batches",
            json={**payload, "counterparty_type": "supplier"},
            headers=manager,
        )
        self.assertEqual(changed_request.status_code, 409)

        listed = self.client.get("/api/v1/ratings/batches?template_key=general", headers=auditor)
        detail = self.client.get(f"/api/v1/ratings/batches/{batch['id']}", headers=auditor)
        audit = self.client.get(f"/api/v1/audit-events?aggregate_id={batch['id']}", headers=auditor)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()[0]["id"], batch["id"])
        self.assertEqual(detail.json()["request_hash"], batch["request_hash"])
        self.assertEqual(audit.json()[0]["event_type"], "portfolio_rating_completed")

    def test_indicator_observation_requires_four_eye_review_and_updates_screening(self) -> None:
        manager = {"Authorization": "Bearer dev-manager"}
        risk = {"Authorization": "Bearer dev-risk"}
        auditor = {"Authorization": "Bearer dev-auditor"}
        pool = self.client.get("/api/v1/indicator-pool?q=股东变更", headers=risk).json()
        indicator = next(item for item in pool["indicators"] if item["name"] == "股东变更")
        payload = {
            "counterparty_id": self.counterparty["id"],
            "indicator_id": indicator["id"],
            "values": {indicator["field_path"]: 3},
            "evidence_reference": "国家企业信用信息公示系统变更记录第1页",
            "as_of_date": datetime.now(timezone.utc).date().isoformat(),
        }

        forbidden = self.client.post("/api/v1/indicator-observations", json=payload, headers=auditor)
        created = self.client.post("/api/v1/indicator-observations", json=payload, headers=manager)
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["status"], "pending_review")

        before = self.client.post(
            "/api/v1/ratings/trace",
            json={"counterparty_id": self.counterparty["id"], "template_key": "general"},
            headers=risk,
        )
        self.assertEqual(before.status_code, 200, before.text)
        before_detail = next(item for item in before.json()["enterprise_risk_screening"]["details"] if item["indicator_id"] == indicator["id"])
        self.assertEqual(before_detail["data_status"], "待补充")
        self.assertIn("RSP-DATA-GAP", [item["id"] for item in before.json()["result"]["risk_screening_policy"]["hits"]])

        reviewed = self.client.post(
            f"/api/v1/indicator-observations/{created.json()['id']}/review",
            json={"expected_row_version": created.json()["row_version"], "decision": "verify", "comment": "已与工商变更记录逐项核对"},
            headers=risk,
        )
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        self.assertEqual(reviewed.json()["status"], "verified")

        after = self.client.post(
            "/api/v1/ratings/trace",
            json={"counterparty_id": self.counterparty["id"], "template_key": "general"},
            headers=risk,
        )
        self.assertEqual(after.status_code, 200, after.text)
        after_detail = next(item for item in after.json()["enterprise_risk_screening"]["details"] if item["indicator_id"] == indicator["id"])
        self.assertEqual(after_detail["actual_value"], 3)
        self.assertEqual(after_detail["score"], 1)
        self.assertEqual(after_detail["data_status"], "已取得")
        self.assertEqual(after_detail["evidence_reference"], payload["evidence_reference"])
        self.assertGreater(after.json()["input_readiness"]["indicator_observation_count"], 0)
        self.assertIn("RSP-CRITICAL", [item["id"] for item in after.json()["result"]["risk_screening_policy"]["hits"]])
        self.assertNotEqual(after.json()["result"]["rating"], before.json()["result"]["rating"])
        self.assertLess(after.json()["result"]["suggested_limit"], before.json()["result"]["suggested_limit"])

        listed = self.client.get(
            f"/api/v1/indicator-observations?counterparty_id={self.counterparty['id']}",
            headers=risk,
        )
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()[0]["id"], created.json()["id"])

    def test_enterprise_data_import_idempotency_conflicts_lineage_and_permissions(self) -> None:
        manager = {"Authorization": "Bearer dev-manager"}
        auditor = {"Authorization": "Bearer dev-auditor"}
        model_admin = {"Authorization": "Bearer dev-model-admin"}
        client = {"Authorization": "Bearer dev-client"}
        today = datetime.now(timezone.utc).date().isoformat()
        base = {
            "import_key": "DATA-IMPORT-OFFICIAL-001",
            "counterparty_id": self.counterparty["id"],
            "source_type": "official_registry",
            "source_name": "国家企业信用信息公示系统",
            "schema_version": "enterprise-data-v1",
            "as_of_date": today,
            "evidence_reference": "工商登记查询回执 2026-07-17",
            "payload": {
                "entity": {
                    "name_cn": self.counterparty["name"],
                    "unified_social_credit_code": self.counterparty["credit_code"],
                    "registration_status": "存续",
                    "legal_representative": "张三",
                    "industry": {"name": self.counterparty["industry"]},
                }
            },
            "field_evidence": {"entity.legal_representative": {"locator": "登记信息第 1 页"}},
        }
        created = self.client.post("/api/v1/data-governance/imports", json=base, headers=manager)
        repeated = self.client.post("/api/v1/data-governance/imports", json=base, headers=manager)
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["status"], "accepted")
        self.assertFalse(created.json()["idempotent"])
        self.assertTrue(repeated.json()["idempotent"])
        self.assertEqual(repeated.json()["id"], created.json()["id"])

        conflicting_payload = {
            **base,
            "import_key": "DATA-IMPORT-MANAGEMENT-001",
            "source_type": "management_submission",
            "source_name": "企业管理层填报",
            "evidence_reference": "企业信息确认表",
            "payload": {**base["payload"], "entity": {**base["payload"]["entity"], "legal_representative": "李四"}},
            "field_evidence": {},
        }
        conflicting = self.client.post("/api/v1/data-governance/imports", json=conflicting_payload, headers=manager)
        self.assertEqual(conflicting.status_code, 201, conflicting.text)
        self.assertEqual(conflicting.json()["status"], "accepted_with_conflicts")
        self.assertEqual(conflicting.json()["conflict_count"], 1)

        profile = self.client.get(f"/api/v1/data-governance/counterparties/{self.counterparty['id']}/profile", headers=auditor)
        lineage = self.client.get(f"/api/v1/data-governance/counterparties/{self.counterparty['id']}/lineage?field_path=entity.legal_representative", headers=auditor)
        self.assertEqual(profile.status_code, 200)
        self.assertEqual(profile.json()["profile"]["entity"]["legal_representative"], "张三")
        self.assertEqual(profile.json()["summary"]["import_count"], 2)
        self.assertEqual(profile.json()["conflict_paths"], ["entity.legal_representative"])
        self.assertEqual(len(lineage.json()["candidates"]), 2)
        self.assertEqual(sum(item["is_effective"] for item in lineage.json()["candidates"]), 1)
        self.assertEqual(next(item for item in lineage.json()["candidates"] if item["is_effective"])["source_type"], "official_registry")

        changed_same_key = {**base, "payload": {**base["payload"], "entity": {**base["payload"]["entity"], "registration_status": "注销"}}}
        self.assertEqual(self.client.post("/api/v1/data-governance/imports", json=changed_same_key, headers=manager).status_code, 409)
        wrong_anchor = {**base, "import_key": "DATA-IMPORT-WRONG-ANCHOR", "payload": {**base["payload"], "entity": {**base["payload"]["entity"], "unified_social_credit_code": "WRONG-CODE"}}}
        self.assertEqual(self.client.post("/api/v1/data-governance/imports", json=wrong_anchor, headers=manager).status_code, 422)
        self.assertEqual(self.client.post("/api/v1/data-governance/imports", json={**base, "import_key": "DATA-MODEL-ADMIN-001"}, headers=model_admin).status_code, 403)
        self.assertEqual(self.client.get(f"/api/v1/data-governance/counterparties/{self.counterparty['id']}/profile", headers=client).status_code, 403)

        audit = self.client.get(f"/api/v1/audit-events?aggregate_id={created.json()['id']}", headers=auditor)
        self.assertIn("enterprise_data_imported", [item["event_type"] for item in audit.json()])

    def test_enterprise_data_conflict_resolution_separation_reopen_and_snapshot_guard(self) -> None:
        manager = {"Authorization": "Bearer dev-manager"}
        risk = {"Authorization": "Bearer dev-risk"}
        approver = {"Authorization": "Bearer dev-approver"}
        auditor = {"Authorization": "Bearer dev-auditor"}
        today = datetime.now(timezone.utc).date().isoformat()

        def import_legal_representative(import_key: str, source_type: str, source_name: str, value: str) -> None:
            response = self.client.post(
                "/api/v1/data-governance/imports",
                json={
                    "import_key": import_key,
                    "counterparty_id": self.counterparty["id"],
                    "source_type": source_type,
                    "source_name": source_name,
                    "schema_version": "enterprise-data-v1",
                    "as_of_date": today,
                    "evidence_reference": f"evidence://{import_key}",
                    "payload": {
                        "entity": {
                            "unified_social_credit_code": self.counterparty["credit_code"],
                            "legal_representative": value,
                        }
                    },
                },
                headers=manager,
            )
            self.assertEqual(response.status_code, 201, response.text)

        import_legal_representative("CONFLICT-OFFICIAL-001", "official_registry", "官方工商", "张三")
        import_legal_representative("CONFLICT-MANAGEMENT-001", "management_submission", "企业填报", "李四")
        conflicts = self.client.get(
            f"/api/v1/data-governance/counterparties/{self.counterparty['id']}/conflicts",
            headers=auditor,
        ).json()
        conflict = next(item for item in conflicts if item["field_path"] == "entity.legal_representative")
        self.assertEqual(conflict["status"], "unresolved")
        selected = next(item for item in conflict["candidates"] if item["value"] == "李四")
        readiness_before = self.client.get(
            f"/api/v1/data-governance/counterparties/{self.counterparty['id']}/rating-readiness?template_key=corporate_credit_v2",
            headers=risk,
        ).json()

        proposal_payload = {
            "counterparty_id": self.counterparty["id"],
            "field_path": conflict["field_path"],
            "selected_field_id": selected["id"],
            "reason_category": "document_verification",
            "rationale": "已核验法定代表人变更文件及企业盖章说明，选择企业填报候选值。",
        }
        proposed = self.client.post("/api/v1/data-governance/resolutions", json=proposal_payload, headers=manager)
        repeated = self.client.post("/api/v1/data-governance/resolutions", json=proposal_payload, headers=manager)
        forbidden = self.client.post("/api/v1/data-governance/resolutions", json=proposal_payload, headers=auditor)
        self.assertEqual(proposed.status_code, 201, proposed.text)
        self.assertEqual(proposed.json()["status"], "pending_review")
        self.assertTrue(repeated.json()["idempotent"])
        self.assertEqual(forbidden.status_code, 403)

        approved = self.client.post(
            f"/api/v1/data-governance/resolutions/{proposed.json()['id']}/review",
            json={"expected_row_version": proposed.json()["row_version"], "decision": "approve", "comment": "已复核变更材料与工商受理凭证，同意采用所选候选值。"},
            headers=risk,
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(approved.json()["status"], "approved")
        profile = self.client.get(
            f"/api/v1/data-governance/counterparties/{self.counterparty['id']}/profile",
            headers=auditor,
        ).json()
        self.assertEqual(profile["profile"]["entity"]["legal_representative"], "李四")
        self.assertEqual(profile["summary"]["conflict_count"], 0)
        self.assertEqual(profile["summary"]["total_conflict_count"], 1)
        self.assertEqual(profile["summary"]["resolved_conflict_count"], 1)
        resolved_field = next(item for item in profile["effective_fields"] if item["field_path"] == "entity.legal_representative")
        self.assertEqual(resolved_field["selection_method"], "approved_resolution")
        readiness_after = self.client.get(
            f"/api/v1/data-governance/counterparties/{self.counterparty['id']}/rating-readiness?template_key=corporate_credit_v2",
            headers=risk,
        ).json()
        self.assertNotEqual(readiness_before["data_snapshot_hash"], readiness_after["data_snapshot_hash"])

        import_legal_representative("CONFLICT-NEW-EVIDENCE-001", "management_submission", "补充调查", "王五")
        reopened = self.client.get(
            f"/api/v1/data-governance/counterparties/{self.counterparty['id']}/conflicts",
            headers=risk,
        ).json()[0]
        self.assertEqual(reopened["status"], "reopened")
        self.assertFalse(reopened["resolution"]["is_current_snapshot"])
        new_selected = next(item for item in reopened["candidates"] if item["value"] == "王五")
        risk_proposal = self.client.post(
            "/api/v1/data-governance/resolutions",
            json={**proposal_payload, "selected_field_id": new_selected["id"], "reason_category": "manual_investigation", "rationale": "现场调查取得新的法定代表人任职文件，申请重新裁决当前候选集合。"},
            headers=risk,
        )
        self.assertEqual(risk_proposal.status_code, 201, risk_proposal.text)
        self_review = self.client.post(
            f"/api/v1/data-governance/resolutions/{risk_proposal.json()['id']}/review",
            json={"expected_row_version": risk_proposal.json()["row_version"], "decision": "approve", "comment": "尝试由提议人自行完成审核。"},
            headers=risk,
        )
        self.assertEqual(self_review.status_code, 403)

        import_legal_representative("CONFLICT-NEW-EVIDENCE-002", "management_submission", "最新补充调查", "赵六")
        stale_review = self.client.post(
            f"/api/v1/data-governance/resolutions/{risk_proposal.json()['id']}/review",
            json={"expected_row_version": risk_proposal.json()["row_version"], "decision": "approve", "comment": "审核最新字段冲突候选值与证据材料。"},
            headers=approver,
        )
        self.assertEqual(stale_review.status_code, 409)
        self.assertIn("候选值集合已发生变化", stale_review.json()["detail"])

        latest_conflict = self.client.get(
            f"/api/v1/data-governance/counterparties/{self.counterparty['id']}/conflicts",
            headers=manager,
        ).json()[0]
        latest_selected = next(item for item in latest_conflict["candidates"] if item["value"] == "赵六")
        replacement = self.client.post(
            "/api/v1/data-governance/resolutions",
            json={**proposal_payload, "selected_field_id": latest_selected["id"], "reason_category": "source_confirmation", "rationale": "新增证据已经由信息来源方再次确认，按最新候选集合重新提交裁决。"},
            headers=manager,
        )
        self.assertEqual(replacement.status_code, 201, replacement.text)
        resolutions = self.client.get(
            f"/api/v1/data-governance/resolutions?counterparty_id={self.counterparty['id']}",
            headers=auditor,
        ).json()
        self.assertEqual(next(item for item in resolutions if item["id"] == risk_proposal.json()["id"])["status"], "superseded")
        self.assertEqual(replacement.json()["status"], "pending_review")

        audit = self.client.get(f"/api/v1/audit-events?aggregate_id={proposed.json()['id']}", headers=auditor).json()
        self.assertEqual([item["event_type"] for item in audit], ["enterprise_data_resolution_submitted", "enterprise_data_resolution_approved"])

    def test_governed_rating_readiness_mapping_gate_and_input_snapshot(self) -> None:
        manager = {"Authorization": "Bearer dev-manager"}
        risk = {"Authorization": "Bearer dev-risk"}
        client = {"Authorization": "Bearer dev-client"}
        counterparties = self.client.get("/api/v1/counterparties", headers=manager).json()
        inalfa = next(item for item in counterparties if item["id"] == "cp_inalfa_guangzhou_001")
        raw_profile = self.client.get(f"/api/v1/counterparties/{inalfa['id']}/raw-profile", headers=manager).json()
        imported = self.client.post(
            "/api/v1/data-governance/imports",
            json={
                "import_key": "DATA-RATING-MAP-001", "counterparty_id": inalfa["id"],
                "source_type": "credit_report", "source_name": "材料信用报告", "schema_version": "1.0",
                "as_of_date": "2024-08-15", "evidence_reference": "report://rating-map-001", "payload": raw_profile,
            },
            headers=manager,
        )
        self.assertEqual(imported.status_code, 201, imported.text)

        readiness_response = self.client.get(
            f"/api/v1/data-governance/counterparties/{inalfa['id']}/rating-readiness?template_key=corporate_credit_v2",
            headers=risk,
        )
        self.assertEqual(readiness_response.status_code, 200)
        readiness = readiness_response.json()
        self.assertEqual(readiness["source_mode"], "governed")
        self.assertEqual(readiness["gate_status"], "review")
        self.assertTrue(readiness["ready_for_scoring"])
        self.assertFalse(readiness["auto_approval_ready"])
        assets_mapping = next(item for item in readiness["mappings"] if item["target_path"] == "corporate_profile.business.total_assets_yi")
        self.assertAlmostEqual(assets_mapping["value"], 2.6015)
        self.assertIn(assets_mapping["status"], {"stale", "mapped"})

        rating = self.client.post(
            "/api/v1/ratings/run",
            json={"counterparty_id": inalfa["id"], "template_key": "corporate_credit_v2"},
            headers=risk,
        )
        self.assertEqual(rating.status_code, 200, rating.text)
        self.assertEqual(rating.json()["input_readiness"]["source_mode"], "governed")
        run = self.client.get(f"/api/v1/ratings/runs/{rating.json()['rating_run_id']}", headers=risk).json()
        self.assertEqual(run["input"]["_data_governance"]["mapping_version"], "corporate-governed-input-v1")
        self.assertIsNone(run["input"]["financial"]["overdue_rate"])
        self.assertEqual(run["input"]["_data_governance"]["data_snapshot_hash"], readiness["data_snapshot_hash"])
        self.assertEqual(run["input_hash"], content_hash(run["input"]))

        minimal_import = self.client.post(
            "/api/v1/data-governance/imports",
            json={
                "import_key": "DATA-RATING-MAP-BLOCK-001", "counterparty_id": self.counterparty["id"],
                "source_type": "official_registry", "source_name": "工商最小数据", "schema_version": "1.0",
                "as_of_date": datetime.now(timezone.utc).date().isoformat(), "evidence_reference": "registry://minimal",
                "payload": {"entity": {"unified_social_credit_code": self.counterparty["credit_code"], "registration_status": "存续"}},
            },
            headers=manager,
        )
        self.assertEqual(minimal_import.status_code, 201)
        blocked_rating = self.client.post(
            "/api/v1/ratings/run",
            json={"counterparty_id": self.counterparty["id"], "template_key": "corporate_credit_v2"},
            headers=risk,
        )
        self.assertEqual(blocked_rating.status_code, 422)
        self.assertIn("治理数据未达到模型计算门槛", blocked_rating.json()["detail"])
        self.assertEqual(
            self.client.get(f"/api/v1/data-governance/counterparties/{inalfa['id']}/rating-readiness", headers=client).status_code,
            403,
        )

    def test_credit_report_sealing_idempotency_integrity_and_permissions(self) -> None:
        seeded = self._seed_completed_report_case()
        manager = {"Authorization": "Bearer dev-manager"}
        approver = {"Authorization": "Bearer dev-approver"}
        auditor = {"Authorization": "Bearer dev-auditor"}
        for index, document_type in enumerate(["营业执照", "财务报表", "征信授权书"]):
            uploaded = self.client.post(
                "/api/v1/documents",
                data={"counterparty_id": self.counterparty["id"], "case_id": seeded["case_id"], "document_type": document_type},
                files={"file": (f"report-evidence-{index}.pdf", f"%PDF-1.7\nreport-evidence-{index}".encode(), "application/pdf")},
                headers=manager,
            )
            self.assertEqual(uploaded.status_code, 201)

        created = self.client.post("/api/v1/credit-reports", json={"case_id": seeded["case_id"]}, headers=approver)
        repeated = self.client.post("/api/v1/credit-reports", json={"case_id": seeded["case_id"]}, headers=approver)
        forbidden = self.client.get(f"/api/v1/credit-reports?case_id={seeded['case_id']}", headers={"Authorization": "Bearer dev-model-admin"})

        self.assertEqual(created.status_code, 201, created.text)
        report = created.json()
        self.assertFalse(report["idempotent"])
        self.assertEqual(report["status"], "sealed")
        self.assertEqual(report["report_version"], 1)
        self.assertEqual(report["preview"]["decision"]["approved_limit"], seeded["approved_limit"])
        self.assertEqual(report["preview"]["document_count"], 3)
        self.assertEqual(len(report["snapshot_hash"]), 64)
        self.assertEqual(len(report["pdf_sha256"]), 64)
        self.assertGreater(report["size_bytes"], 1000)
        self.assertEqual(repeated.status_code, 201)
        self.assertTrue(repeated.json()["idempotent"])
        self.assertEqual(repeated.json()["id"], report["id"])
        self.assertEqual(forbidden.status_code, 403)

        listed = self.client.get(f"/api/v1/credit-reports?case_id={seeded['case_id']}", headers=auditor)
        detail = self.client.get(f"/api/v1/credit-reports/{report['id']}", headers=auditor)
        integrity = self.client.get(f"/api/v1/credit-reports/{report['id']}/integrity", headers=auditor)
        downloaded = self.client.get(f"/api/v1/credit-reports/{report['id']}/download", headers=auditor)
        self.assertEqual(len(listed.json()), 1)
        self.assertEqual(detail.status_code, 200)
        self.assertIn("snapshot", detail.json())
        self.assertTrue(integrity.json()["valid"])
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(downloaded.headers["content-type"], "application/pdf")
        self.assertEqual(downloaded.headers["x-report-pdf-sha256"], report["pdf_sha256"])
        self.assertTrue(downloaded.content.startswith(b"%PDF-"))

        object_key = f"reports/{self.counterparty['id']}/{seeded['case_id']}/{report['snapshot_hash']}.pdf"
        LocalObjectStorage(self.temp_storage.name).put(object_key, b"tampered-report", "application/pdf")
        failed_integrity = self.client.get(f"/api/v1/credit-reports/{report['id']}/integrity", headers=auditor)
        blocked_download = self.client.get(f"/api/v1/credit-reports/{report['id']}/download", headers=auditor)
        self.assertFalse(failed_integrity.json()["valid"])
        self.assertFalse(failed_integrity.json()["pdf"]["valid"])
        self.assertEqual(blocked_download.status_code, 409)
        self.assertIn("PDF 文件指纹校验失败", blocked_download.json()["detail"])

        LocalObjectStorage(self.temp_storage.name).put(object_key, downloaded.content, "application/pdf")
        with database.SessionLocal() as session:
            record = session.get(CreditReportRecord, report["id"])
            tampered_snapshot = dict(record.snapshot_json)
            tampered_snapshot["case"] = {**tampered_snapshot["case"], "status": "已篡改"}
            record.snapshot_json = tampered_snapshot
            session.commit()
        snapshot_integrity = self.client.get(f"/api/v1/credit-reports/{report['id']}/integrity", headers=auditor)
        snapshot_blocked_download = self.client.get(f"/api/v1/credit-reports/{report['id']}/download", headers=auditor)
        self.assertFalse(snapshot_integrity.json()["valid"])
        self.assertFalse(snapshot_integrity.json()["snapshot"]["valid"])
        self.assertEqual(snapshot_blocked_download.status_code, 409)
        self.assertIn("业务快照完整性校验失败", snapshot_blocked_download.json()["detail"])

        audits = self.client.get(f"/api/v1/audit-events?aggregate_id={seeded['case_id']}", headers={"Authorization": "Bearer dev-risk"})
        self.assertIn("credit_report_generated", [item["event_type"] for item in audits.json()])

    def test_credit_report_requires_completed_approval(self) -> None:
        pending = self.client.post("/api/v1/approval-cases", json={"counterparty_id": self.counterparty["id"]}, headers={"Authorization": "Bearer dev-manager"}).json()
        response = self.client.post("/api/v1/credit-reports", json={"case_id": pending["case_id"]}, headers={"Authorization": "Bearer dev-risk"})
        self.assertEqual(response.status_code, 409)
        self.assertIn("完成最终审批", response.json()["detail"])

    def test_credit_report_rejects_tampered_rating_input(self) -> None:
        seeded = self._seed_completed_report_case("CASE-TAMPERED-RATING-INPUT")
        with database.SessionLocal() as session:
            run = session.query(RatingRunRecord).filter_by(case_id=seeded["case_id"]).one()
            run.input_json = {**run.input_json, "name": "已被静默替换的评级输入"}
            session.commit()

        response = self.client.post(
            "/api/v1/credit-reports",
            json={"case_id": seeded["case_id"]},
            headers={"Authorization": "Bearer dev-approver"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("评级运行输入或结果完整性校验失败", response.json()["detail"])

    def test_material_raw_profile_access_lineage_and_missing_data(self) -> None:
        counterparties = self.client.get("/api/v1/counterparties", headers=self.headers).json()
        material_sample = next(item for item in counterparties if item["id"] == "cp_inalfa_guangzhou_001")
        ordinary_sample = next(item for item in counterparties if not item.get("data_quality", {}).get("raw_profile_id"))

        response = self.client.get(
            f"/api/v1/counterparties/{material_sample['id']}/raw-profile",
            headers=self.headers,
        )
        unavailable = self.client.get(
            f"/api/v1/counterparties/{ordinary_sample['id']}/raw-profile",
            headers=self.headers,
        )
        forbidden = self.client.get(
            f"/api/v1/counterparties/{material_sample['id']}/raw-profile",
            headers={"Authorization": "Bearer dev-operations"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["profile_id"], "raw-inalfa-guangzhou-20240815")
        self.assertEqual(payload["recommended_model"], "corporate_credit_v2")
        self.assertEqual(material_sample["industry"], "汽车零部件及配件制造")
        self.assertAlmostEqual(payload["external_benchmark"]["report_score"], 49.58)
        self.assertEqual(len(payload["financial_statements"]["periods"]), 3)
        self.assertGreaterEqual(len(payload["source_lineage"]), 5)
        self.assertIn("申请额度", payload["missing_critical_fields"])
        self.assertEqual(payload["internal_transaction_data"]["status"], "not_provided_in_source_materials")
        self.assertEqual(unavailable.status_code, 404)
        self.assertEqual(forbidden.status_code, 403)

    def test_rating_trace_and_model_impact(self) -> None:
        request = {"counterparty_id": self.counterparty["id"], "template_key": "general"}
        rating = self.client.post("/api/v1/ratings/run", json=request, headers=self.headers)
        trace = self.client.post("/api/v1/ratings/trace", json=request, headers=self.headers)
        impact = self.client.post(
            "/api/v1/models/impact",
            json={**request, "field_path": "financial.overdue_rate", "new_value": 0.5},
            headers=self.headers,
        )

        self.assertEqual(rating.status_code, 200)
        self.assertIn("suggested_limit", rating.json())
        self.assertIn("rating_run_id", rating.json())
        saved_run = self.client.get(f"/api/v1/ratings/runs/{rating.json()['rating_run_id']}", headers=self.headers)
        self.assertEqual(saved_run.status_code, 200)
        self.assertEqual(saved_run.json()["result_hash"], rating.json()["result_hash"])
        self.assertEqual(trace.status_code, 200)
        self.assertIn("dimension_contributions", trace.json())
        self.assertEqual(impact.status_code, 200)
        self.assertIn("impact", impact.json())

        model = self.client.get("/api/v1/models/general", headers=self.headers)
        self.assertEqual(model.status_code, 200)
        self.assertIn("weights", model.json())
        self.assertGreater(len(model.json()["editable_indicators"]), 5)

        unknown_indicator = self.client.post(
            "/api/v1/models/impact",
            json={**request, "field_path": "requested_limit", "new_value": 1},
            headers=self.headers,
        )
        invalid_rate = self.client.post(
            "/api/v1/models/impact",
            json={**request, "field_path": "financial.overdue_rate", "new_value": 1.5},
            headers=self.headers,
        )
        self.assertEqual(unknown_indicator.status_code, 422)
        self.assertEqual(invalid_rate.status_code, 422)

    def test_model_validation_dashboard_and_release_gate(self) -> None:
        general = self.client.get("/api/v1/model-governance/validation?template_key=general", headers=self.headers)
        corporate = self.client.get("/api/v1/model-governance/validation?template_key=corporate_credit_v2", headers=self.headers)
        forbidden = self.client.get(
            "/api/v1/model-governance/validation?template_key=general",
            headers={"Authorization": "Bearer dev-client"},
        )

        self.assertEqual(general.status_code, 200)
        self.assertTrue(general.json()["release_gate"]["passed"])
        self.assertEqual(general.json()["sample_profile"]["total_count"], 6)
        self.assertGreaterEqual(len(general.json()["metrics"]), 6)
        monitoring = general.json()["monitoring"]
        self.assertEqual(monitoring["dataset"]["evidence_level"], "simulation_proxy")
        self.assertEqual(monitoring["population_stability"]["status"], "pass")
        self.assertAlmostEqual(monitoring["population_stability"]["value"], 0.0188)
        performance = {item["key"]: item for item in monitoring["performance_metrics"]}
        self.assertGreater(performance["auc"]["value"], 0.8)
        self.assertGreater(performance["ks"]["value"], 0.5)
        self.assertLess(performance["brier"]["value"], 0.2)
        self.assertEqual(performance["calibration_gap"]["status"], "fail")
        self.assertIn("不可作为正式违约回溯证据", monitoring["dataset"]["label_definition"])

        self.assertEqual(corporate.status_code, 200)
        self.assertFalse(corporate.json()["release_gate"]["passed"])
        self.assertEqual(corporate.json()["sample_profile"]["total_count"], 1)
        self.assertIn("适用验证样本", corporate.json()["release_gate"]["summary"])
        self.assertIsNone(corporate.json()["monitoring"]["dataset"])
        self.assertEqual(corporate.json()["monitoring"]["population_stability"]["status"], "not_testable")
        completeness = next(item for item in corporate.json()["metrics"] if item["key"] == "data_completeness")
        self.assertAlmostEqual(completeness["value"], 0.695)
        self.assertEqual(forbidden.status_code, 403)

        active = self.client.get("/api/v1/models/corporate_credit_v2", headers=self.headers).json()
        created = self.client.post(
            "/api/v1/model-governance/changes",
            headers={"Authorization": "Bearer dev-model-admin"},
            json={
                "template_key": "corporate_credit_v2",
                "candidate_version": f"{active['version']}-VALIDATION-BLOCK",
                "change_reason": "验证小样本模型发布门槛",
                "weights": active["weights"],
                "thresholds": active["thresholds"],
                "strong_rules": active["strong_rules"],
                "strategy_mapping": active["strategy_mapping"],
            },
        )
        self.assertEqual(created.status_code, 201)
        self.assertTrue(created.json()["validation"]["valid"])
        self.assertFalse(created.json()["validation"]["model_risk"]["release_gate"]["passed"])
        blocked_submit = self.client.post(
            f"/api/v1/model-governance/changes/{created.json()['id']}/submit",
            headers={"Authorization": "Bearer dev-model-admin"},
            json={"expected_row_version": created.json()["row_version"]},
        )
        self.assertEqual(blocked_submit.status_code, 422)
        self.assertIn("模型验证发布门槛未通过", blocked_submit.json()["detail"])

    def test_observed_outcome_ingestion_and_monitoring_issue_closure(self) -> None:
        model_admin = {"Authorization": "Bearer dev-model-admin"}
        risk = {"Authorization": "Bearer dev-risk"}
        model = self.client.get("/api/v1/models/general", headers=model_admin).json()
        now = datetime.now(timezone.utc)
        outcome_payload = {
            "external_observation_id": "ERP-OUTCOME-2026Q2-001",
            "source": "ERP应收台账",
            "template_key": "general",
            "model_version": model["version"],
            "counterparty_id": self.counterparty["id"],
            "population_period": "2026Q2",
            "predicted_score": 82.5,
            "predicted_pd": 0.03,
            "observed_event": False,
            "prediction_at": (now - timedelta(days=120)).isoformat(),
            "observation_end": (now - timedelta(days=1)).isoformat(),
            "evidence_reference": "ERP应收台账/2026Q2/结清状态",
        }

        created = self.client.post("/api/v1/model-governance/outcomes", headers=model_admin, json=outcome_payload)
        duplicate = self.client.post("/api/v1/model-governance/outcomes", headers=model_admin, json=outcome_payload)
        invalid_version = self.client.post("/api/v1/model-governance/outcomes", headers=model_admin, json={**outcome_payload, "external_observation_id": "ERP-INVALID-VERSION", "model_version": "UNKNOWN"})
        pending_summary = self.client.get("/api/v1/model-governance/monitoring-summary?template_key=general", headers=risk)

        self.assertEqual(created.status_code, 201)
        self.assertFalse(created.json()["idempotent"])
        self.assertEqual(duplicate.status_code, 201)
        self.assertTrue(duplicate.json()["idempotent"])
        self.assertEqual(invalid_version.status_code, 422)
        self.assertIn("模型版本不存在", invalid_version.json()["detail"])
        self.assertEqual(created.json()["verification_status"], "pending_verification")
        self.assertEqual(pending_summary.status_code, 200)
        self.assertEqual(pending_summary.json()["readiness"]["submitted_count"], 1)
        self.assertEqual(pending_summary.json()["readiness"]["pending_verification_count"], 1)
        self.assertEqual(pending_summary.json()["readiness"]["observation_count"], 0)

        verified = self.client.post(
            f"/api/v1/model-governance/outcomes/{created.json()['id']}/verify",
            headers=risk,
            json={"expected_row_version": created.json()["row_version"], "decision": "verify", "note": "已核对 ERP 到期结算状态与证据引用，确认标签口径一致"},
        )
        summary = self.client.get("/api/v1/model-governance/monitoring-summary?template_key=general", headers=risk)
        self.assertEqual(verified.status_code, 200)
        self.assertEqual(verified.json()["verification_status"], "verified")
        self.assertEqual(summary.json()["readiness"]["observation_count"], 1)
        self.assertEqual(summary.json()["readiness"]["pending_verification_count"], 0)
        self.assertFalse(summary.json()["readiness"]["formal_backtest_ready"])
        self.assertEqual(summary.json()["effective_source"], "simulation_proxy")

        scan = self.client.post("/api/v1/model-governance/issues/scan?template_key=general", headers=risk)
        self.assertEqual(scan.status_code, 200)
        issues = {item["metric_key"]: item for item in scan.json()}
        self.assertIn("calibration_gap", issues)
        self.assertIn("data_readiness", issues)
        issue = issues["calibration_gap"]

        remediation = self.client.post(
            f"/api/v1/model-governance/issues/{issue['id']}/remediation",
            headers=model_admin,
            json={"expected_row_version": issue["row_version"], "owner": "模型验证组", "plan": "补充真实结果样本并重新校准等级 PD 映射", "due_days": 30},
        )
        self.assertEqual(remediation.status_code, 200)
        self.assertEqual(remediation.json()["status"], "in_remediation")

        submitted = self.client.post(
            f"/api/v1/model-governance/issues/{issue['id']}/submit-revalidation",
            headers=model_admin,
            json={"expected_row_version": remediation.json()["row_version"], "result": "已完成样本核对和校准方案评估，提交独立复验"},
        )
        self.assertEqual(submitted.status_code, 200)
        self.assertEqual(submitted.json()["status"], "pending_revalidation")

        reviewed = self.client.post(
            f"/api/v1/model-governance/issues/{issue['id']}/review",
            headers=risk,
            json={"expected_row_version": submitted.json()["row_version"], "decision": "pass", "conclusion": "整改证据与重算结果已独立复核，同意关闭本轮问题"},
        )
        self.assertEqual(reviewed.status_code, 200)
        self.assertEqual(reviewed.json()["status"], "closed")
        self.assertEqual(reviewed.json()["revalidated_by"], "risk-demo")

        rescanned = self.client.post("/api/v1/model-governance/issues/scan?template_key=general", headers=risk)
        rescanned_issue = next(item for item in rescanned.json() if item["metric_key"] == "calibration_gap")
        self.assertEqual(rescanned_issue["status"], "open")

        audit = self.client.get(f"/api/v1/audit-events?aggregate_id={issue['id']}", headers=risk)
        self.assertEqual(audit.status_code, 200)
        self.assertEqual(
            [event["event_type"] for event in audit.json()],
            ["monitoring_issue_opened", "monitoring_remediation_started", "monitoring_revalidation_submitted", "monitoring_revalidation_passed", "monitoring_issue_reopened"],
        )

    def test_batch_outcomes_monitoring_run_notifications_and_change_link(self) -> None:
        model_admin = {"Authorization": "Bearer dev-model-admin"}
        risk = {"Authorization": "Bearer dev-risk"}
        manager = {"Authorization": "Bearer dev-manager"}
        model = self.client.get("/api/v1/models/general", headers=model_admin).json()
        now = datetime.now(timezone.utc)
        base_outcome = {
            "external_observation_id": "BATCH-OUTCOME-001",
            "source": "ERP批量回传",
            "template_key": "general",
            "model_version": model["version"],
            "counterparty_id": self.counterparty["id"],
            "population_period": "2026Q2",
            "predicted_score": 77.5,
            "predicted_pd": 0.08,
            "observed_event": False,
            "prediction_at": (now - timedelta(days=120)).isoformat(),
            "observation_end": (now - timedelta(days=1)).isoformat(),
            "evidence_reference": "ERP批量回传文件第 1 行",
        }
        batch = self.client.post(
            "/api/v1/model-governance/outcomes/batch",
            headers=model_admin,
            json={"outcomes": [base_outcome, base_outcome, {**base_outcome, "external_observation_id": "BATCH-INVALID", "model_version": "UNKNOWN"}]},
        )
        self.assertEqual(batch.status_code, 200)
        self.assertEqual(batch.json()["created"], 1)
        self.assertEqual(batch.json()["idempotent"], 1)
        self.assertEqual(batch.json()["rejected"], 1)

        outcome_id = batch.json()["results"][0]["outcome_id"]
        outcome = next(item for item in self.client.get("/api/v1/model-governance/outcomes?template_key=general", headers=risk).json() if item["id"] == outcome_id)
        verified = self.client.post(
            f"/api/v1/model-governance/outcomes/{outcome_id}/verify",
            headers=risk,
            json={"expected_row_version": outcome["row_version"], "decision": "verify", "note": "已核对批量文件签名、字段映射和业务系统结清状态"},
        )
        self.assertEqual(verified.status_code, 200)

        run_payload = {"run_key": "GENERAL-2026Q2-SCHEDULED-001", "template_key": "general", "as_of_period": "2026Q2", "trigger_type": "scheduled"}
        run = self.client.post("/api/v1/model-governance/runs", headers=risk, json=run_payload)
        duplicate_run = self.client.post("/api/v1/model-governance/runs", headers=risk, json=run_payload)
        self.assertEqual(run.status_code, 200)
        self.assertEqual(run.json()["status"], "completed")
        self.assertFalse(run.json()["idempotent"])
        self.assertEqual(len(run.json()["issue_ids"]), 2)
        self.assertTrue(duplicate_run.json()["idempotent"])
        self.assertEqual(duplicate_run.json()["id"], run.json()["id"])
        runs = self.client.get("/api/v1/model-governance/runs?template_key=general", headers=risk)
        self.assertEqual(runs.status_code, 200)
        self.assertEqual(len(runs.json()), 1)
        self.assertEqual(runs.json()[0]["id"], run.json()["id"])
        self.assertEqual(runs.json()[0]["status"], "completed")
        conflicting_run = self.client.post(
            "/api/v1/model-governance/runs",
            headers=risk,
            json={**run_payload, "as_of_period": "2026Q3"},
        )
        self.assertEqual(conflicting_run.status_code, 422)

        risk_notifications = self.client.get("/api/v1/model-governance/governance-notifications?unread_only=true", headers=risk)
        admin_notifications = self.client.get("/api/v1/model-governance/governance-notifications?unread_only=true", headers=model_admin)
        manager_notifications = self.client.get("/api/v1/model-governance/governance-notifications?unread_only=true", headers=manager)
        self.assertEqual(len(risk_notifications.json()), 2)
        self.assertEqual(len(admin_notifications.json()), 2)
        self.assertEqual(manager_notifications.json(), [])
        read = self.client.post(f"/api/v1/model-governance/governance-notifications/{risk_notifications.json()[0]['id']}/read", headers=risk)
        self.assertEqual(read.status_code, 200)
        self.assertEqual(read.json()["status"], "read")

        draft = self.client.post(
            "/api/v1/model-governance/changes",
            headers=model_admin,
            json={
                "template_key": "general", "candidate_version": f"{model['version']}-RECAL-01",
                "change_reason": "关联监控事件率偏差并启动模型重校准",
                "weights": model["weights"], "thresholds": model["thresholds"],
                "strong_rules": model["strong_rules"], "strategy_mapping": model["strategy_mapping"],
            },
        )
        self.assertEqual(draft.status_code, 201)
        issues = self.client.get("/api/v1/model-governance/issues?template_key=general", headers=model_admin).json()
        issue = next(item for item in issues if item["metric_key"] == "calibration_gap")
        linked = self.client.post(
            f"/api/v1/model-governance/issues/{issue['id']}/link-change",
            headers=model_admin,
            json={"expected_row_version": issue["row_version"], "change_id": draft.json()["id"]},
        )
        self.assertEqual(linked.status_code, 200)
        self.assertEqual(linked.json()["linked_change_id"], draft.json()["id"])

    def test_monitoring_run_failure_is_persisted(self) -> None:
        risk = {"Authorization": "Bearer dev-risk"}
        payload = {"run_key": "GENERAL-2026Q3-FAILED-001", "template_key": "general", "as_of_period": "2026Q3", "trigger_type": "scheduled"}
        with patch.object(ModelMonitoringRepository, "sync_issues", side_effect=ValueError("模拟监控问题同步失败")):
            response = self.client.post("/api/v1/model-governance/runs", headers=risk, json=payload)
        self.assertEqual(response.status_code, 422)
        runs = self.client.get("/api/v1/model-governance/runs?template_key=general", headers=risk)
        self.assertEqual(runs.status_code, 200)
        self.assertEqual(len(runs.json()), 1)
        self.assertEqual(runs.json()[0]["status"], "failed")
        self.assertEqual(runs.json()[0]["error_message"], "模拟监控问题同步失败")

    def test_outcome_import_reconciliation_and_idempotency(self) -> None:
        model_admin = {"Authorization": "Bearer dev-model-admin"}
        manager = {"Authorization": "Bearer dev-manager"}
        model = self.client.get("/api/v1/models/general", headers=model_admin).json()
        now = datetime.now(timezone.utc)
        base_outcome = {
            "external_observation_id": "IMPORT-OUTCOME-001",
            "source": "ERP结果仓",
            "template_key": "general",
            "model_version": model["version"],
            "counterparty_id": self.counterparty["id"],
            "population_period": "2026Q2",
            "predicted_score": 76.0,
            "predicted_pd": 0.09,
            "observed_event": False,
            "prediction_at": (now - timedelta(days=120)).isoformat(),
            "observation_end": (now - timedelta(days=1)).isoformat(),
            "evidence_reference": "ERP结果仓批次 2026Q2 第 1 行",
        }
        payload = {
            "import_key": "ERP-2026Q2-RECON-001",
            "source": "ERP结果仓",
            "template_key": "general",
            "population_period": "2026Q2",
            "expected_count": 3,
            "outcomes": [base_outcome, {**base_outcome, "external_observation_id": "IMPORT-OUTCOME-002", "source": "错误来源"}],
        }
        denied = self.client.post("/api/v1/model-governance/outcome-imports", headers=manager, json=payload)
        created = self.client.post("/api/v1/model-governance/outcome-imports", headers=model_admin, json=payload)
        retried = self.client.post("/api/v1/model-governance/outcome-imports", headers=model_admin, json=payload)
        conflict = self.client.post("/api/v1/model-governance/outcome-imports", headers=model_admin, json={**payload, "expected_count": 2})
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["status"], "completed_with_exceptions")
        self.assertEqual(created.json()["expected_count"], 3)
        self.assertEqual(created.json()["received_count"], 2)
        self.assertEqual(created.json()["count_variance"], -1)
        self.assertEqual(created.json()["created_count"], 1)
        self.assertEqual(created.json()["rejected_count"], 1)
        self.assertIn("与导入任务不一致", created.json()["results"][1]["error"])
        self.assertTrue(retried.json()["idempotent"])
        self.assertEqual(retried.json()["id"], created.json()["id"])
        self.assertEqual(conflict.status_code, 422)
        imports = self.client.get("/api/v1/model-governance/outcome-imports?template_key=general", headers=manager)
        self.assertEqual(imports.status_code, 200)
        self.assertEqual(len(imports.json()), 1)

    def test_failed_outcome_import_can_resume_with_same_key(self) -> None:
        model_admin = {"Authorization": "Bearer dev-model-admin"}
        model = self.client.get("/api/v1/models/general", headers=model_admin).json()
        now = datetime.now(timezone.utc)
        outcome = {
            "external_observation_id": "IMPORT-RESUME-001", "source": "ERP结果仓", "template_key": "general", "model_version": model["version"],
            "counterparty_id": self.counterparty["id"], "population_period": "2026Q2", "predicted_score": 75.0, "predicted_pd": 0.1,
            "observed_event": False, "prediction_at": (now - timedelta(days=120)).isoformat(), "observation_end": (now - timedelta(days=1)).isoformat(),
            "evidence_reference": "导入中断恢复测试",
        }
        payload = {"import_key": "ERP-2026Q2-RESUME-001", "source": "ERP结果仓", "template_key": "general", "population_period": "2026Q2", "expected_count": 1, "outcomes": [outcome]}
        with patch.object(ModelMonitoringRepository, "complete_outcome_import", side_effect=ValueError("模拟导入任务完成失败")):
            failed = self.client.post("/api/v1/model-governance/outcome-imports", headers=model_admin, json=payload)
        resumed = self.client.post("/api/v1/model-governance/outcome-imports", headers=model_admin, json=payload)
        self.assertEqual(failed.status_code, 422)
        self.assertEqual(resumed.status_code, 201)
        self.assertTrue(resumed.json()["idempotent"])
        self.assertEqual(resumed.json()["status"], "completed")
        self.assertEqual(resumed.json()["created_count"], 0)
        self.assertEqual(resumed.json()["idempotent_count"], 1)

    def test_monitoring_schedule_due_execution_and_versioning(self) -> None:
        model_admin = {"Authorization": "Bearer dev-model-admin"}
        risk = {"Authorization": "Bearer dev-risk"}
        now = datetime.now(timezone.utc)
        payload = {
            "template_key": "general",
            "cadence": "monthly",
            "timezone_name": "Asia/Shanghai",
            "enabled": True,
            "next_run_at": (now - timedelta(days=1)).isoformat(),
        }
        denied_create = self.client.post("/api/v1/model-governance/schedules", headers=risk, json=payload)
        created = self.client.post("/api/v1/model-governance/schedules", headers=model_admin, json=payload)
        duplicate = self.client.post("/api/v1/model-governance/schedules", headers=model_admin, json=payload)
        denied_tick = self.client.post("/api/v1/model-governance/schedules/run-due", headers=model_admin, json={"as_of": now.isoformat()})
        tick = self.client.post("/api/v1/model-governance/schedules/run-due", headers=risk, json={"as_of": now.isoformat()})
        second_tick = self.client.post("/api/v1/model-governance/schedules/run-due", headers=risk, json={"as_of": now.isoformat()})
        self.assertEqual(denied_create.status_code, 403)
        self.assertEqual(created.status_code, 201)
        self.assertEqual(duplicate.status_code, 422)
        self.assertEqual(denied_tick.status_code, 403)
        self.assertEqual(tick.status_code, 200)
        self.assertEqual(tick.json()["due_count"], 1)
        self.assertEqual(tick.json()["completed"], 1)
        self.assertEqual(second_tick.json()["due_count"], 0)
        schedules = self.client.get("/api/v1/model-governance/schedules?template_key=general", headers=risk).json()
        self.assertEqual(len(schedules), 1)
        schedule = schedules[0]
        self.assertEqual(schedule["last_status"], "completed")
        self.assertIsNotNone(schedule["last_run_id"])
        self.assertGreater(datetime.fromisoformat(schedule["next_run_at"]).replace(tzinfo=timezone.utc), now)
        runs = self.client.get("/api/v1/model-governance/runs?template_key=general", headers=risk).json()
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["trigger_type"], "scheduled")
        stale = self.client.put(
            f"/api/v1/model-governance/schedules/{schedule['id']}",
            headers=model_admin,
            json={"expected_row_version": 1, "cadence": "quarterly", "timezone_name": "UTC", "enabled": False, "next_run_at": (now + timedelta(days=90)).isoformat()},
        )
        updated = self.client.put(
            f"/api/v1/model-governance/schedules/{schedule['id']}",
            headers=model_admin,
            json={"expected_row_version": schedule["row_version"], "cadence": "quarterly", "timezone_name": "UTC", "enabled": False, "next_run_at": (now + timedelta(days=90)).isoformat()},
        )
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["cadence"], "quarterly")
        self.assertFalse(updated.json()["enabled"])

    def test_failed_schedule_stays_due_and_retries_same_run(self) -> None:
        model_admin = {"Authorization": "Bearer dev-model-admin"}
        risk = {"Authorization": "Bearer dev-risk"}
        now = datetime.now(timezone.utc)
        scheduled_for = now - timedelta(days=1)
        created = self.client.post(
            "/api/v1/model-governance/schedules",
            headers=model_admin,
            json={"template_key": "general", "cadence": "monthly", "timezone_name": "Asia/Shanghai", "enabled": True, "next_run_at": scheduled_for.isoformat()},
        )
        self.assertEqual(created.status_code, 201)
        with patch.object(ModelMonitoringRepository, "sync_issues", side_effect=ValueError("模拟定时监控失败")):
            failed_tick = self.client.post("/api/v1/model-governance/schedules/run-due", headers=risk, json={"as_of": now.isoformat()})
        failed_schedule = self.client.get("/api/v1/model-governance/schedules?template_key=general", headers=risk).json()[0]
        failed_run = self.client.get("/api/v1/model-governance/runs?template_key=general", headers=risk).json()[0]
        self.assertEqual(failed_tick.status_code, 200)
        self.assertEqual(failed_tick.json()["failed"], 1)
        self.assertEqual(failed_schedule["last_status"], "failed")
        self.assertEqual(failed_run["status"], "failed")
        retried_tick = self.client.post("/api/v1/model-governance/schedules/run-due", headers=risk, json={"as_of": now.isoformat()})
        retried_schedule = self.client.get("/api/v1/model-governance/schedules?template_key=general", headers=risk).json()[0]
        retried_runs = self.client.get("/api/v1/model-governance/runs?template_key=general", headers=risk).json()
        self.assertEqual(retried_tick.status_code, 200)
        self.assertEqual(retried_tick.json()["completed"], 1)
        self.assertEqual(retried_schedule["last_status"], "completed")
        self.assertEqual(len(retried_runs), 1)
        self.assertEqual(retried_runs[0]["id"], failed_run["id"])
        self.assertEqual(retried_runs[0]["status"], "completed")

    def test_model_governance_publish_separation_impact_and_rollback(self) -> None:
        model_admin = {"Authorization": "Bearer dev-model-admin"}
        risk = {"Authorization": "Bearer dev-risk"}
        manager = {"Authorization": "Bearer dev-manager"}
        active = self.client.get("/api/v1/models/general", headers=model_admin).json()
        candidate_version = f"{active['version']}-GOV-01"
        payload = {
            "template_key": "general",
            "candidate_version": candidate_version,
            "change_reason": "降低重大诉讼阈值并验证组合评级影响",
            "weights": active["weights"],
            "thresholds": {**active["thresholds"], "major_litigation_amount": 1000},
            "strong_rules": active["strong_rules"],
            "strategy_mapping": active["strategy_mapping"],
        }

        denied = self.client.post("/api/v1/model-governance/changes", json=payload, headers=manager)
        invalid = self.client.post(
            "/api/v1/model-governance/changes",
            json={**payload, "candidate_version": f"{active['version']}-BAD", "weights": {**active["weights"], "external_risk": 0.9}},
            headers=model_admin,
        )
        created = self.client.post("/api/v1/model-governance/changes", json=payload, headers=model_admin)
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(created.status_code, 201)
        self.assertTrue(created.json()["validation"]["valid"])
        self.assertGreater(created.json()["impact"]["sample_count"], 0)

        updated = self.client.put(
            f"/api/v1/model-governance/changes/{created.json()['id']}",
            json={
                "expected_row_version": created.json()["row_version"],
                "change_reason": "降低重大诉讼阈值并复核更新后的组合评级影响",
                "weights": active["weights"],
                "thresholds": {**active["thresholds"], "major_litigation_amount": 2000},
                "strong_rules": active["strong_rules"],
                "strategy_mapping": active["strategy_mapping"],
            },
            headers=model_admin,
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["row_version"], created.json()["row_version"] + 1)

        submitted = self.client.post(
            f"/api/v1/model-governance/changes/{created.json()['id']}/submit",
            json={"expected_row_version": updated.json()["row_version"]},
            headers=model_admin,
        )
        self.assertEqual(submitted.status_code, 200)
        self.assertEqual(submitted.json()["status"], "pending_review")
        maker_cannot_review = self.client.post(
            f"/api/v1/model-governance/changes/{created.json()['id']}/review",
            json={"expected_row_version": submitted.json()["row_version"], "decision": "publish", "comment": "自行审批"},
            headers=model_admin,
        )
        self.assertEqual(maker_cannot_review.status_code, 403)

        published = self.client.post(
            f"/api/v1/model-governance/changes/{created.json()['id']}/review",
            json={"expected_row_version": submitted.json()["row_version"], "decision": "publish", "comment": "组合影响可接受，同意发布"},
            headers=risk,
        )
        self.assertEqual(published.status_code, 200)
        self.assertEqual(published.json()["status"], "published")
        effective = self.client.get("/api/v1/models/general", headers=risk)
        self.assertEqual(effective.json()["version"], candidate_version)
        rating = self.client.post("/api/v1/ratings/run", json={"counterparty_id": self.counterparty["id"], "template_key": "general"}, headers=risk)
        self.assertEqual(rating.json()["model_version"], candidate_version)

        releases = self.client.get("/api/v1/model-governance/releases?template_key=general", headers=risk).json()
        self.assertEqual(len(releases), 2)
        self.assertEqual(sum(item["is_active"] for item in releases), 1)
        with database.SessionLocal() as session:
            session.add(ModelReleaseRecord(id="concurrent-active-release", template_key="general", model_version="CONCURRENT-ACTIVE", config_json={}, config_hash="0" * 64, source_change_id=None, is_active=True, published_by="test"))
            with self.assertRaises(IntegrityError):
                session.commit()
            session.rollback()
        baseline = next(item for item in releases if item["model_version"] == active["version"])
        rolled_back = self.client.post(
            f"/api/v1/model-governance/releases/{baseline['id']}/rollback",
            json={"comment": "回滚验证：恢复基线版本"},
            headers=risk,
        )
        self.assertEqual(rolled_back.status_code, 200)
        self.assertTrue(rolled_back.json()["is_active"])
        self.assertEqual(self.client.get("/api/v1/models/general", headers=risk).json()["version"], active["version"])

        audit = self.client.get(f"/api/v1/audit-events?aggregate_id={created.json()['id']}", headers=risk)
        self.assertEqual([item["event_type"] for item in audit.json()], ["model_change_created", "model_change_updated", "model_change_submitted", "model_change_published"])

        tech = self.client.get("/api/v1/models/tech_enterprise_basic", headers=model_admin).json()
        chosen_indicators = [
            {"indicator_id": item["id"], "weight": index + 1, "enabled": True}
            for index, item in enumerate(tech["indicator_selection"][:3])
        ]
        tech_draft = self.client.post(
            "/api/v1/model-governance/changes",
            json={
                "template_key": "tech_enterprise_basic",
                "candidate_version": f"{tech['version']}-GOV",
                "change_reason": "验证科创模型扩展分数区间可进入治理流程",
                "weights": tech["weights"],
                "thresholds": tech["thresholds"],
                "strong_rules": tech["strong_rules"],
                "strategy_mapping": tech["strategy_mapping"],
                "indicator_selection": chosen_indicators,
            },
            headers=model_admin,
        )
        self.assertEqual(tech_draft.status_code, 201)
        self.assertEqual(tech_draft.json()["config"]["indicator_selection"], chosen_indicators)
        self.assertTrue(tech_draft.json()["impact"]["indicator_selection_changed"])
        self.assertIn("risk_screening_impacted_count", tech_draft.json()["impact"])

        admin = {"Authorization": "Bearer dev-admin"}
        self_draft = self.client.post(
            "/api/v1/model-governance/changes",
            json={**payload, "candidate_version": f"{active['version']}-SELF-REVIEW", "change_reason": "验证管理员也不能绕过模型审批职责分离"},
            headers=admin,
        ).json()
        self_submitted = self.client.post(
            f"/api/v1/model-governance/changes/{self_draft['id']}/submit",
            json={"expected_row_version": self_draft["row_version"]},
            headers=admin,
        ).json()
        self_review = self.client.post(
            f"/api/v1/model-governance/changes/{self_draft['id']}/review",
            json={"expected_row_version": self_submitted["row_version"], "decision": "publish", "comment": "尝试自行审批"},
            headers=admin,
        )
        self.assertEqual(self_review.status_code, 403)

    def test_approval_scoring_uses_version_frozen_at_model_selection(self) -> None:
        model_admin = {"Authorization": "Bearer dev-model-admin"}
        risk = {"Authorization": "Bearer dev-risk"}
        manager = {"Authorization": "Bearer dev-manager"}
        active = self.client.get("/api/v1/models/general", headers=risk).json()
        created_case = self.client.post("/api/v1/approval-cases", json={"counterparty_id": self.counterparty["id"]}, headers=manager).json()
        with database.SessionLocal() as session:
            record = session.get(ApprovalCaseRecord, created_case["case_id"])
            record.current_stage = "scoring"
            record.status = "处理中"
            record.completed_stages = ["registration", "document_upload", "supplement", "approval_submit", "model_selection"]
            record.case_data = {"model_selection": {"template_key": "general", "model_name": active["name"], "model_version": active["version"]}}
            session.commit()
            session.refresh(record)
            scoring_row_version = record.row_version

        candidate_version = f"{active['version']}-AFTER-SELECTION"
        change = self.client.post(
            "/api/v1/model-governance/changes",
            json={
                "template_key": "general",
                "candidate_version": candidate_version,
                "change_reason": "验证审批选模后发布新版本不会污染在途评分",
                "weights": active["weights"],
                "thresholds": {**active["thresholds"], "overdue_rate": 0.05},
                "strong_rules": active["strong_rules"],
                "strategy_mapping": active["strategy_mapping"],
            },
            headers=model_admin,
        ).json()
        submitted = self.client.post(
            f"/api/v1/model-governance/changes/{change['id']}/submit",
            json={"expected_row_version": change["row_version"]},
            headers=model_admin,
        ).json()
        published = self.client.post(
            f"/api/v1/model-governance/changes/{change['id']}/review",
            json={"expected_row_version": submitted["row_version"], "decision": "publish", "comment": "同意发布，用于版本冻结验证"},
            headers=risk,
        )
        self.assertEqual(published.status_code, 200)
        self.assertEqual(self.client.get("/api/v1/models/general", headers=risk).json()["version"], candidate_version)

        scored = self.client.post(
            f"/api/v1/approval-cases/{created_case['case_id']}/automate",
            json={"expected_row_version": scoring_row_version},
            headers=risk,
        )
        self.assertEqual(scored.status_code, 200)
        run_id = scored.json()["data"]["scoring"]["rating_run_id"]
        run = self.client.get(f"/api/v1/ratings/runs/{run_id}", headers=risk)
        self.assertEqual(run.json()["result"]["model_version"], active["version"])

    def test_approval_scoring_rejects_governed_data_changed_after_model_selection(self) -> None:
        manager = {"Authorization": "Bearer dev-manager"}
        risk = {"Authorization": "Bearer dev-risk"}
        counterparties = self.client.get("/api/v1/counterparties", headers=manager).json()
        inalfa = next(item for item in counterparties if item["id"] == "cp_inalfa_guangzhou_001")
        raw_profile = self.client.get(f"/api/v1/counterparties/{inalfa['id']}/raw-profile", headers=manager).json()
        imported = self.client.post(
            "/api/v1/data-governance/imports",
            json={
                "import_key": "DATA-APPROVAL-SNAPSHOT-BASE", "counterparty_id": inalfa["id"],
                "source_type": "credit_report", "source_name": "选模时信用报告", "schema_version": "1.0",
                "as_of_date": "2024-08-15", "evidence_reference": "report://approval-snapshot-base", "payload": raw_profile,
            },
            headers=manager,
        )
        self.assertEqual(imported.status_code, 201, imported.text)
        readiness = self.client.get(
            f"/api/v1/data-governance/counterparties/{inalfa['id']}/rating-readiness?template_key=corporate_credit_v2",
            headers=risk,
        ).json()
        active = self.client.get("/api/v1/models/corporate_credit_v2", headers=risk).json()
        created_case = self.client.post("/api/v1/approval-cases", json={"counterparty_id": inalfa["id"]}, headers=manager).json()
        with database.SessionLocal() as session:
            record = session.get(ApprovalCaseRecord, created_case["case_id"])
            record.current_stage = "scoring"
            record.status = "处理中"
            record.completed_stages = ["registration", "document_upload", "supplement", "approval_submit", "model_selection"]
            record.case_data = {
                "model_selection": {
                    "template_key": "corporate_credit_v2",
                    "model_name": active["name"],
                    "model_version": active["version"],
                    "input_readiness": {"data_snapshot_hash": readiness["data_snapshot_hash"]},
                }
            }
            session.commit()
            session.refresh(record)
            scoring_row_version = record.row_version

        changed = self.client.post(
            "/api/v1/data-governance/imports",
            json={
                "import_key": "DATA-APPROVAL-SNAPSHOT-CHANGED", "counterparty_id": inalfa["id"],
                "source_type": "audited_financial", "source_name": "选模后审计财务", "schema_version": "1.0",
                "as_of_date": datetime.now(timezone.utc).date().isoformat(), "evidence_reference": "audit://approval-snapshot-changed",
                "payload": {
                    "entity": {"unified_social_credit_code": inalfa["credit_code"]},
                    "financial_statements": {"derived_features": {"weighted_debt_to_assets_pct": 99.9}},
                },
            },
            headers=manager,
        )
        self.assertEqual(changed.status_code, 201, changed.text)
        scored = self.client.post(
            f"/api/v1/approval-cases/{created_case['case_id']}/automate",
            json={"expected_row_version": scoring_row_version},
            headers=risk,
        )
        self.assertEqual(scored.status_code, 409)
        self.assertIn("选模后发生变化", scored.json()["detail"])

    def test_approval_case_validates_and_advances(self) -> None:
        created = self.client.post("/api/v1/approval-cases", json={"counterparty_id": self.counterparty["id"]}, headers=self.headers)
        self.assertEqual(created.status_code, 201)
        case_id = created.json()["case_id"]

        invalid = self.client.post(f"/api/v1/approval-cases/{case_id}/advance", json={"actor": "客户经理", "payload": {}}, headers=self.headers)
        self.assertEqual(invalid.status_code, 422)

        valid = self.client.post(
            f"/api/v1/approval-cases/{case_id}/advance",
            json={
                "actor": "客户经理",
                "expected_row_version": created.json()["row_version"],
                "payload": {
                    "registered_name": self.counterparty["name"],
                    "unified_social_credit_code": self.counterparty["credit_code"],
                    "contact_name": "业务联系人",
                },
            },
            headers=self.headers,
        )
        self.assertEqual(valid.status_code, 200)
        self.assertEqual(valid.json()["current_stage"], "document_upload")
        audit = self.client.get(f"/api/v1/audit-events?aggregate_id={case_id}", headers=self.headers)
        self.assertEqual(audit.status_code, 200)
        self.assertEqual(len(audit.json()), 2)
        self.assertEqual(audit.json()[1]["previous_hash"], audit.json()[0]["event_hash"])

        stale = self.client.post(
            f"/api/v1/approval-cases/{case_id}/advance",
            json={"expected_row_version": 1, "payload": {"documents": ["营业执照", "财务报表"]}},
            headers=self.headers,
        )
        self.assertEqual(stale.status_code, 409)

    def test_credit_facility_lifecycle_transactions_reviews_and_alerts(self) -> None:
        manager = {"Authorization": "Bearer dev-manager"}
        approver = {"Authorization": "Bearer dev-approver"}
        risk = {"Authorization": "Bearer dev-risk"}
        client = {"Authorization": "Bearer dev-client"}
        created = self.client.post("/api/v1/approval-cases", json={"counterparty_id": self.counterparty["id"]}, headers=manager).json()
        with database.SessionLocal() as session:
            record = session.get(ApprovalCaseRecord, created["case_id"])
            record.current_stage = "final_strategy"
            record.status = "处理中"
            record.completed_stages = ["registration", "document_upload", "supplement", "approval_submit", "model_selection", "scoring", "credit_proposal"]
            record.case_data = {
                "scoring": {"rating": "A"},
                "credit_proposal": {"suggested_limit": 100000, "suggested_payment_term_days": 30, "access_strategy": "准入", "monitoring_frequency": "月度"},
            }
            session.commit()
            session.refresh(record)
            row_version = record.row_version

        completed = self.client.post(
            f"/api/v1/approval-cases/{created['case_id']}/advance",
            json={"expected_row_version": row_version, "payload": {"decision": "通过", "access_strategy": "准入", "approved_limit": 100000, "approved_payment_term_days": 30, "monitoring_frequency": "月度", "facility_validity_days": 365}},
            headers=approver,
        )
        self.assertEqual(completed.status_code, 200)
        self.assertEqual(completed.json()["status"], "已完成")
        facility = completed.json()["credit_facility"]
        variance = completed.json()["decision_variance_record"]
        self.assertEqual(facility["approved_limit"], 100000)
        self.assertEqual(facility["available_limit"], 100000)
        self.assertEqual(variance["direction"], "aligned")
        self.assertEqual(variance["materiality"], "none")
        listed_variance = self.client.get(f"/api/v1/decision-governance/variances?case_id={created['case_id']}", headers=risk)
        self.assertEqual(listed_variance.status_code, 200)
        self.assertEqual(listed_variance.json()[0]["id"], variance["id"])
        self.assertEqual(self.client.get("/api/v1/decision-governance/summary", headers=risk).json()["aligned_count"], 1)
        self.assertEqual(self.client.get("/api/v1/decision-governance/summary", headers=manager).status_code, 403)

        client_facilities = self.client.get("/api/v1/credit-facilities", headers=client)
        self.assertEqual(len(client_facilities.json()), 1)
        client_transaction = self.client.post(
            f"/api/v1/credit-facilities/{facility['id']}/transactions",
            json={"transaction_ref": "CLIENT-DENIED", "transaction_type": "drawdown", "amount": 1, "expected_row_version": facility["row_version"], "reason": "客户不能直接操作额度"},
            headers=client,
        )
        self.assertEqual(client_transaction.status_code, 403)

        draw = self.client.post(
            f"/api/v1/credit-facilities/{facility['id']}/transactions",
            json={"transaction_ref": "ORDER-001", "transaction_type": "drawdown", "amount": 90000, "expected_row_version": facility["row_version"], "reason": "订单发货占用额度"},
            headers=manager,
        )
        self.assertEqual(draw.status_code, 200)
        self.assertEqual(draw.json()["facility"]["used_limit"], 90000)
        duplicate = self.client.post(
            f"/api/v1/credit-facilities/{facility['id']}/transactions",
            json={"transaction_ref": "ORDER-001", "transaction_type": "drawdown", "amount": 90000, "expected_row_version": facility["row_version"], "reason": "网络重试"},
            headers=manager,
        )
        self.assertTrue(duplicate.json()["idempotent"])
        overdraw = self.client.post(
            f"/api/v1/credit-facilities/{facility['id']}/transactions",
            json={"transaction_ref": "ORDER-OVER", "transaction_type": "drawdown", "amount": 20000, "expected_row_version": draw.json()["facility"]["row_version"], "reason": "超额用信测试"},
            headers=manager,
        )
        self.assertEqual(overdraw.status_code, 422)

        alerts = self.client.get("/api/v1/credit-facilities/alerts", headers=risk).json()
        utilization_alert = next(item for item in alerts if item["alert_type"] == "high_utilization")
        acknowledged = self.client.post(f"/api/v1/credit-facilities/alerts/{utilization_alert['id']}/acknowledge", headers=risk)
        self.assertEqual(acknowledged.json()["status"], "acknowledged")
        repay = self.client.post(
            f"/api/v1/credit-facilities/{facility['id']}/transactions",
            json={"transaction_ref": "RECEIPT-001", "transaction_type": "repayment", "amount": 50000, "expected_row_version": draw.json()["facility"]["row_version"], "reason": "客户回款释放额度"},
            headers=manager,
        )
        self.assertEqual(repay.status_code, 200)
        self.assertEqual(repay.json()["facility"]["used_limit"], 40000)
        resolved_alerts = self.client.get("/api/v1/credit-facilities/alerts", headers=risk).json()
        self.assertEqual(next(item for item in resolved_alerts if item["id"] == utilization_alert["id"])["status"], "resolved")

        with database.SessionLocal() as session:
            record = session.get(CreditFacilityRecord, facility["id"])
            record.next_review_at = datetime.now(timezone.utc) - timedelta(days=1)
            session.commit()
        scan = self.client.post("/api/v1/credit-facilities/scan", headers=risk)
        self.assertGreaterEqual(scan.json()["alerts_opened"], 1)
        current = self.client.get(f"/api/v1/credit-facilities/{facility['id']}", headers=risk).json()
        reviewed = self.client.post(
            f"/api/v1/credit-facilities/{facility['id']}/reviews",
            json={"expected_row_version": current["row_version"], "rating": "A", "next_review_days": 30, "conclusion": "经营稳定，维持当前额度"},
            headers=risk,
        )
        self.assertEqual(reviewed.status_code, 200)

        with database.SessionLocal() as session:
            record = session.get(CreditFacilityRecord, facility["id"])
            record.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            session.commit()
        expiry_scan = self.client.post("/api/v1/credit-facilities/scan", headers=risk)
        self.assertEqual(expiry_scan.json()["facilities_expired"], 1)
        self.assertEqual(expiry_scan.json()["alerts_opened"], 1)
        expired = self.client.get(f"/api/v1/credit-facilities/{facility['id']}", headers=risk).json()
        self.assertEqual(expired["status"], "expired")
        blocked = self.client.post(
            f"/api/v1/credit-facilities/{facility['id']}/transactions",
            json={"transaction_ref": "ORDER-AFTER-EXPIRY", "transaction_type": "drawdown", "amount": 1, "expected_row_version": expired["row_version"], "reason": "到期后用信测试"},
            headers=manager,
        )
        self.assertEqual(blocked.status_code, 422)
        summary = self.client.get("/api/v1/credit-facilities/summary", headers=risk)
        self.assertEqual(summary.json()["active_facilities"], 0)
        facility_audit = self.client.get(f"/api/v1/audit-events?aggregate_id={facility['id']}", headers=risk).json()
        self.assertIn("credit_facility_activated", [item["event_type"] for item in facility_audit])
        self.assertIn("post_credit_review_completed", [item["event_type"] for item in facility_audit])

    def test_final_approval_and_facility_activation_are_atomic(self) -> None:
        manager = {"Authorization": "Bearer dev-manager"}
        approver = {"Authorization": "Bearer dev-approver"}
        risk = {"Authorization": "Bearer dev-risk"}
        created = self.client.post("/api/v1/approval-cases", json={"counterparty_id": self.counterparty["id"]}, headers=manager).json()
        with database.SessionLocal() as session:
            record = session.get(ApprovalCaseRecord, created["case_id"])
            record.current_stage = "final_strategy"
            record.status = "处理中"
            record.completed_stages = ["registration", "document_upload", "supplement", "approval_submit", "model_selection", "scoring", "credit_proposal"]
            record.case_data = {
                "scoring": {"rating": "A"},
                "credit_proposal": {"suggested_limit": 100000, "suggested_payment_term_days": 30, "access_strategy": "准入"},
            }
            session.commit()
            session.refresh(record)
            row_version = record.row_version

        rejected_activation = self.client.post(
            f"/api/v1/approval-cases/{created['case_id']}/advance",
            json={"expected_row_version": row_version, "payload": {"decision": "通过", "access_strategy": "准入", "approved_limit": 120000, "approved_payment_term_days": 30, "monitoring_frequency": "月度", "facility_validity_days": 365}},
            headers=approver,
        )
        self.assertEqual(rejected_activation.status_code, 422)
        self.assertIn("不能高于模型建议额度", rejected_activation.json()["detail"])

        unchanged_case = self.client.get(f"/api/v1/approval-cases/{created['case_id']}", headers=approver).json()
        self.assertEqual(unchanged_case["current_stage"], "final_strategy")
        self.assertEqual(unchanged_case["status"], "处理中")
        self.assertNotIn("final_strategy", unchanged_case["data"])
        self.assertEqual(self.client.get("/api/v1/credit-facilities", headers=risk).json(), [])

        missing_reason = self.client.post(
            f"/api/v1/approval-cases/{created['case_id']}/advance",
            json={"expected_row_version": unchanged_case["row_version"], "payload": {"decision": "拒绝", "access_strategy": "禁入", "monitoring_frequency": "月度", "facility_validity_days": 365}},
            headers=approver,
        )
        self.assertEqual(missing_reason.status_code, 422)
        self.assertIn("偏差原因类别", missing_reason.json()["detail"])

        rejected_case = self.client.post(
            f"/api/v1/approval-cases/{created['case_id']}/advance",
            json={"expected_row_version": unchanged_case["row_version"], "payload": {"decision": "拒绝", "access_strategy": "禁入", "monitoring_frequency": "月度", "facility_validity_days": 365, "adjustment_reason_category": "新增风险信号", "adjustment_reason": "审批复核发现重大未决诉讼，风险超出当前政策容忍度"}},
            headers=approver,
        )
        self.assertEqual(rejected_case.status_code, 200)
        self.assertEqual(rejected_case.json()["status"], "已完成")
        self.assertIsNone(rejected_case.json()["credit_facility"])
        self.assertEqual(rejected_case.json()["decision_variance_record"]["direction"], "rejected")
        self.assertEqual(rejected_case.json()["decision_variance_record"]["materiality"], "material")
        self.assertEqual(self.client.get("/api/v1/credit-facilities", headers=risk).json(), [])

    def test_risk_event_disposition_and_facility_controls(self) -> None:
        manager = {"Authorization": "Bearer dev-manager"}
        approver = {"Authorization": "Bearer dev-approver"}
        risk = {"Authorization": "Bearer dev-risk"}
        operations = {"Authorization": "Bearer dev-operations"}
        client = {"Authorization": "Bearer dev-client"}
        created = self.client.post("/api/v1/approval-cases", json={"counterparty_id": self.counterparty["id"]}, headers=manager).json()
        with database.SessionLocal() as session:
            record = session.get(ApprovalCaseRecord, created["case_id"])
            record.current_stage = "final_strategy"
            record.status = "处理中"
            record.completed_stages = ["registration", "document_upload", "supplement", "approval_submit", "model_selection", "scoring", "credit_proposal"]
            record.case_data = {"scoring": {"rating": "A"}, "credit_proposal": {"suggested_limit": 100000, "suggested_payment_term_days": 30, "access_strategy": "准入"}}
            session.commit()
            session.refresh(record)
            row_version = record.row_version
        completed = self.client.post(
            f"/api/v1/approval-cases/{created['case_id']}/advance",
            json={"expected_row_version": row_version, "payload": {"decision": "通过", "access_strategy": "准入", "approved_limit": 100000, "approved_payment_term_days": 30, "monitoring_frequency": "月度", "facility_validity_days": 365}},
            headers=approver,
        ).json()
        facility = completed["credit_facility"]
        event_payload = {
            "external_event_id": "QCC-LAWSUIT-20260714-001",
            "event_type": "litigation",
            "source": "企查查风险监控",
            "severity": "critical",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "title": "新增重大诉讼",
            "description": "新增买卖合同纠纷，涉案金额较高。",
            "payload": {"case_no": "（2026）沪01民初100号", "amount": 800000},
        }
        ingested = self.client.post(f"/api/v1/credit-facilities/{facility['id']}/risk-events", json=event_payload, headers=manager)
        self.assertEqual(ingested.status_code, 201)
        self.assertFalse(ingested.json()["idempotent"])
        risk_event = ingested.json()["risk_event"]
        alert = ingested.json()["alert"]
        self.assertEqual(risk_event["linked_alert_id"], alert["id"])
        self.assertEqual(alert["status"], "open")

        duplicate = self.client.post(f"/api/v1/credit-facilities/{facility['id']}/risk-events", json=event_payload, headers=manager)
        self.assertTrue(duplicate.json()["idempotent"])
        conflicting = self.client.post(f"/api/v1/credit-facilities/{facility['id']}/risk-events", json={**event_payload, "description": "同编号但内容不同"}, headers=manager)
        self.assertEqual(conflicting.status_code, 422)
        future_event = self.client.post(f"/api/v1/credit-facilities/{facility['id']}/risk-events", json={**event_payload, "external_event_id": "FUTURE-001", "occurred_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()}, headers=manager)
        self.assertEqual(future_event.status_code, 422)
        oversized_event = self.client.post(f"/api/v1/credit-facilities/{facility['id']}/risk-events", json={**event_payload, "external_event_id": "LARGE-001", "payload": {"raw": "x" * 33000}}, headers=manager)
        self.assertEqual(oversized_event.status_code, 422)
        other_source = self.client.post(
            f"/api/v1/credit-facilities/{facility['id']}/risk-events",
            json={**event_payload, "source": "ERP 回款监控", "event_type": "payment_overdue", "severity": "warning", "title": "同编号的内部逾期事件", "description": "不同来源允许使用相同事件编号。"},
            headers=manager,
        )
        self.assertEqual(other_source.status_code, 201)
        self.assertFalse(other_source.json()["idempotent"])
        self.assertEqual(len(self.client.get("/api/v1/credit-facilities/risk-events", headers=client).json()), 2)

        forbidden_control = self.client.post(
            f"/api/v1/credit-facilities/alerts/{alert['id']}/dispose",
            json={"expected_alert_version": alert["row_version"], "expected_facility_version": facility["row_version"], "action": "freeze", "conclusion": "运营尝试冻结"},
            headers=operations,
        )
        self.assertEqual(forbidden_control.status_code, 403)
        disposed = self.client.post(
            f"/api/v1/credit-facilities/alerts/{alert['id']}/dispose",
            json={"expected_alert_version": alert["row_version"], "expected_facility_version": facility["row_version"], "action": "freeze", "conclusion": "重大诉讼待核实，先行冻结额度"},
            headers=risk,
        )
        self.assertEqual(disposed.status_code, 200)
        self.assertEqual(disposed.json()["facility"]["status"], "frozen")
        self.assertEqual(disposed.json()["alert"]["disposition_action"], "freeze")
        original_event = next(item for item in self.client.get("/api/v1/credit-facilities/risk-events", headers=risk).json() if item["id"] == risk_event["id"])
        self.assertEqual(original_event["status"], "resolved")
        stale_disposition = self.client.post(
            f"/api/v1/credit-facilities/alerts/{alert['id']}/dispose",
            json={"expected_alert_version": alert["row_version"], "expected_facility_version": facility["row_version"], "action": "monitor", "conclusion": "并发重复处置测试"},
            headers=risk,
        )
        self.assertEqual(stale_disposition.status_code, 409)

        frozen = disposed.json()["facility"]
        monitored = self.client.post(
            f"/api/v1/credit-facilities/alerts/{other_source.json()['alert']['id']}/dispose",
            json={"expected_alert_version": other_source.json()["alert"]["row_version"], "expected_facility_version": frozen["row_version"], "action": "monitor", "conclusion": "运营完成核查，纳入持续监控"},
            headers=operations,
        )
        self.assertEqual(monitored.status_code, 200)
        self.assertEqual(monitored.json()["facility"]["status"], "frozen")

        blocked_draw = self.client.post(
            f"/api/v1/credit-facilities/{facility['id']}/transactions",
            json={"transaction_ref": "FROZEN-DRAW", "transaction_type": "drawdown", "amount": 1, "expected_row_version": frozen["row_version"], "reason": "冻结后用信测试"},
            headers=manager,
        )
        self.assertEqual(blocked_draw.status_code, 422)
        unfrozen = self.client.post(
            f"/api/v1/credit-facilities/{facility['id']}/controls",
            json={"expected_row_version": frozen["row_version"], "action": "unfreeze", "reason": "诉讼已核实且风险可控"},
            headers=approver,
        )
        self.assertEqual(unfrozen.json()["status"], "active")
        drawn = self.client.post(
            f"/api/v1/credit-facilities/{facility['id']}/transactions",
            json={"transaction_ref": "CONTROL-DRAW", "transaction_type": "drawdown", "amount": 40000, "expected_row_version": unfrozen.json()["row_version"], "reason": "订单占用"},
            headers=manager,
        ).json()["facility"]
        invalid_reduction = self.client.post(
            f"/api/v1/credit-facilities/{facility['id']}/controls",
            json={"expected_row_version": drawn["row_version"], "action": "reduce_limit", "target_limit": 30000, "reason": "不能低于已用额度"},
            headers=risk,
        )
        self.assertEqual(invalid_reduction.status_code, 422)
        reduced = self.client.post(
            f"/api/v1/credit-facilities/{facility['id']}/controls",
            json={"expected_row_version": drawn["row_version"], "action": "reduce_limit", "target_limit": 80000, "reason": "风险上升，压降额度"},
            headers=risk,
        ).json()
        self.assertEqual(reduced["approved_limit"], 80000)
        close_with_balance = self.client.post(
            f"/api/v1/credit-facilities/{facility['id']}/controls",
            json={"expected_row_version": reduced["row_version"], "action": "close", "reason": "有余额时关闭测试"},
            headers=approver,
        )
        self.assertEqual(close_with_balance.status_code, 422)
        repaid = self.client.post(
            f"/api/v1/credit-facilities/{facility['id']}/transactions",
            json={"transaction_ref": "CONTROL-REPAY", "transaction_type": "repayment", "amount": 40000, "expected_row_version": reduced["row_version"], "reason": "结清占用"},
            headers=manager,
        ).json()["facility"]
        closed = self.client.post(
            f"/api/v1/credit-facilities/{facility['id']}/controls",
            json={"expected_row_version": repaid["row_version"], "action": "close", "reason": "终止合作并关闭授信"},
            headers=approver,
        )
        self.assertEqual(closed.json()["status"], "closed")
        audits = self.client.get(f"/api/v1/audit-events?aggregate_id={facility['id']}", headers=risk).json()
        event_types = [item["event_type"] for item in audits]
        self.assertIn("risk_event_ingested", event_types)
        self.assertIn("facility_alert_disposed", event_types)
        self.assertIn("facility_reduce_limit", event_types)
        self.assertIn("facility_close", event_types)

    def test_approval_stage_role_and_multiple_applications(self) -> None:
        manager_headers = {"Authorization": "Bearer dev-manager"}
        approver_headers = {"Authorization": "Bearer dev-approver"}
        first = self.client.post("/api/v1/approval-cases", json={"counterparty_id": self.counterparty["id"]}, headers=manager_headers)
        second = self.client.post("/api/v1/approval-cases", json={"counterparty_id": self.counterparty["id"]}, headers=manager_headers)
        denied = self.client.post(
            f"/api/v1/approval-cases/{first.json()['case_id']}/advance",
            json={"expected_row_version": first.json()["row_version"], "payload": {"registered_name": self.counterparty["name"], "unified_social_credit_code": self.counterparty["credit_code"], "contact_name": "联系人"}},
            headers=approver_headers,
        )

        self.assertNotEqual(first.json()["case_id"], second.json()["case_id"])
        self.assertEqual(denied.status_code, 403)

        model_admin_view = self.client.get("/api/v1/approval-cases", headers={"Authorization": "Bearer dev-model-admin"})
        self.assertEqual(model_admin_view.status_code, 200)

    def test_approval_automates_model_rating_and_credit_proposal(self) -> None:
        manager = {"Authorization": "Bearer dev-manager"}
        risk = {"Authorization": "Bearer dev-risk"}
        approver = {"Authorization": "Bearer dev-approver"}
        response = self.client.post("/api/v1/approval-cases", json={"counterparty_id": self.counterparty["id"]}, headers=manager)
        case = response.json()

        response = self.client.post(
            f"/api/v1/approval-cases/{case['case_id']}/advance",
            json={"expected_row_version": case["row_version"], "payload": {"registered_name": self.counterparty["name"], "unified_social_credit_code": self.counterparty["credit_code"], "contact_name": "联系人"}},
            headers=manager,
        )
        self.assertEqual(response.status_code, 200)
        case = response.json()

        missing_documents = self.client.post(
            f"/api/v1/approval-cases/{case['case_id']}/automate",
            json={"expected_row_version": case["row_version"]},
            headers=manager,
        )
        self.assertEqual(missing_documents.status_code, 422)

        for index, document_type in enumerate(["营业执照", "财务报表"]):
            uploaded = self.client.post(
                "/api/v1/documents",
                data={"counterparty_id": self.counterparty["id"], "case_id": case["case_id"], "document_type": document_type},
                files={"file": (f"document-{index}.pdf", b"%PDF-1.7\nworkflow-document", "application/pdf")},
                headers=manager,
            )
            self.assertEqual(uploaded.status_code, 201)

        uploaded_metadata = uploaded.json()
        pending_gate = self.client.post(
            f"/api/v1/approval-cases/{case['case_id']}/automate",
            json={"expected_row_version": case["row_version"]},
            headers=manager,
        )
        self.assertEqual(pending_gate.status_code, 422)
        self.assertIn("已上传但待风控独立核验", pending_gate.json()["detail"])
        LocalObjectStorage(self.temp_storage.name).put(uploaded_metadata["object_key"], b"%PDF-1.7\ntampered", "application/pdf")
        tampered_document = self.client.post(
            f"/api/v1/approval-cases/{case['case_id']}/automate",
            json={"expected_row_version": case["row_version"]},
            headers=manager,
        )
        self.assertEqual(tampered_document.status_code, 409)
        LocalObjectStorage(self.temp_storage.name).put(uploaded_metadata["object_key"], b"%PDF-1.7\nworkflow-document", "application/pdf")
        documents = self.client.get(
            f"/api/v1/documents?case_id={case['case_id']}", headers=risk
        ).json()
        for document in documents:
            self._review_document(document)

        response = self.client.post(
            f"/api/v1/approval-cases/{case['case_id']}/automate",
            json={"expected_row_version": case["row_version"]},
            headers=manager,
        )
        self.assertEqual(response.status_code, 200)
        case = response.json()
        self.assertEqual(case["current_stage"], "supplement")

        missing_supplement = self.client.post(
            f"/api/v1/approval-cases/{case['case_id']}/automate",
            json={"expected_row_version": case["row_version"]},
            headers=manager,
        )
        self.assertEqual(missing_supplement.status_code, 422)
        uploaded = self.client.post(
            "/api/v1/documents",
            data={"counterparty_id": self.counterparty["id"], "case_id": case["case_id"], "document_type": "征信授权书"},
            files={"file": ("authorization.pdf", b"%PDF-1.7\nauthorization", "application/pdf")},
            headers=manager,
        )
        self.assertEqual(uploaded.status_code, 201)
        self._review_document(uploaded.json())

        response = self.client.post(
            f"/api/v1/approval-cases/{case['case_id']}/automate",
            json={"expected_row_version": case["row_version"]},
            headers=manager,
        )
        self.assertEqual(response.status_code, 200)
        case = response.json()

        response = self.client.post(
            f"/api/v1/approval-cases/{case['case_id']}/advance",
            json={"expected_row_version": case["row_version"], "payload": {"business_type": "供应链赊销", "requested_limit": self.counterparty["requested_limit"], "requested_term_days": 30}},
            headers=manager,
        )
        self.assertEqual(response.status_code, 200)
        case = response.json()

        response = self.client.post(
            f"/api/v1/approval-cases/{case['case_id']}/automate",
            json={"expected_row_version": case["row_version"], "template_key": "general"},
            headers=risk,
        )
        self.assertEqual(response.status_code, 200)
        case = response.json()
        self.assertEqual(case["current_stage"], "scoring")

        manual_scoring = self.client.post(
            f"/api/v1/approval-cases/{case['case_id']}/advance",
            json={"expected_row_version": case["row_version"], "payload": {"total_score": 100, "rating": "AAA"}},
            headers=risk,
        )
        self.assertEqual(manual_scoring.status_code, 409)

        response = self.client.post(
            f"/api/v1/approval-cases/{case['case_id']}/automate",
            json={"expected_row_version": case["row_version"]},
            headers=risk,
        )
        self.assertEqual(response.status_code, 200)
        case = response.json()
        rating_run_id = case["data"]["scoring"]["rating_run_id"]
        run = self.client.get(f"/api/v1/ratings/runs/{rating_run_id}", headers=risk)
        self.assertEqual(run.status_code, 200)
        self.assertEqual(run.json()["case_id"], case["case_id"])

        response = self.client.post(
            f"/api/v1/approval-cases/{case['case_id']}/automate",
            json={"expected_row_version": case["row_version"]},
            headers=approver,
        )
        self.assertEqual(response.status_code, 200)
        case = response.json()
        self.assertEqual(case["current_stage"], "final_strategy")
        self.assertEqual(case["data"]["credit_proposal"]["rating_run_id"], rating_run_id)

        returned = self.client.post(
            f"/api/v1/approval-cases/{case['case_id']}/actions",
            json={"action": "return_for_supplement", "reason": "请补充业务合同后重新评估", "required_document_types": ["业务合同"], "expected_row_version": case["row_version"]},
            headers=approver,
        )
        self.assertEqual(returned.status_code, 200)
        case = returned.json()
        self.assertEqual(case["current_stage"], "supplement")
        self.assertEqual(case["status"], "待补件")
        self.assertNotIn("scoring", case["data"])

        still_missing = self.client.post(
            f"/api/v1/approval-cases/{case['case_id']}/automate",
            json={"expected_row_version": case["row_version"]},
            headers=manager,
        )
        self.assertEqual(still_missing.status_code, 422)
        uploaded = self.client.post(
            "/api/v1/documents",
            data={"counterparty_id": self.counterparty["id"], "case_id": case["case_id"], "document_type": "业务合同"},
            files={"file": ("contract.pdf", b"%PDF-1.7\ncontract", "application/pdf")},
            headers=manager,
        )
        self.assertEqual(uploaded.status_code, 201)
        self._review_document(uploaded.json())
        response = self.client.post(
            f"/api/v1/approval-cases/{case['case_id']}/automate",
            json={"expected_row_version": case["row_version"]},
            headers=manager,
        )
        self.assertEqual(response.status_code, 200)
        case = response.json()
        self.assertEqual(case["status"], "处理中")

        response = self.client.post(
            f"/api/v1/approval-cases/{case['case_id']}/advance",
            json={"expected_row_version": case["row_version"], "payload": {"business_type": "供应链赊销", "requested_limit": self.counterparty["requested_limit"], "requested_term_days": 30}},
            headers=manager,
        )
        case = response.json()
        rejected = self.client.post(
            f"/api/v1/approval-cases/{case['case_id']}/actions",
            json={"action": "reject", "reason": "补件后风险仍超出策略容忍度", "expected_row_version": case["row_version"]},
            headers=risk,
        )
        self.assertEqual(rejected.status_code, 200)
        self.assertEqual(rejected.json()["status"], "已拒绝")
        self.assertEqual(rejected.json()["sla_status"], "已停止")

    def test_approval_comment_withdraw_and_sla(self) -> None:
        manager = {"Authorization": "Bearer dev-manager"}
        created = self.client.post("/api/v1/approval-cases", json={"counterparty_id": self.counterparty["id"]}, headers=manager).json()
        self.assertEqual(created["sla_status"], "正常")
        self.assertIsNotNone(created["stage_due_at"])

        commented = self.client.post(
            f"/api/v1/approval-cases/{created['case_id']}/actions",
            json={"action": "comment", "reason": "已联系企业确认注册信息", "expected_row_version": created["row_version"]},
            headers=manager,
        )
        self.assertEqual(commented.status_code, 200)
        self.assertEqual(commented.json()["stage_due_at"], created["stage_due_at"])
        self.assertEqual(commented.json()["timeline"][-1]["类型"], "审批意见")

        blank_comment = self.client.post(
            f"/api/v1/approval-cases/{created['case_id']}/actions",
            json={"action": "comment", "reason": "   ", "expected_row_version": commented.json()["row_version"]},
            headers=manager,
        )
        self.assertEqual(blank_comment.status_code, 422)

        with database.SessionLocal() as session:
            record = session.get(ApprovalCaseRecord, created["case_id"])
            record.stage_due_at = datetime.now(timezone.utc) - timedelta(minutes=5)
            session.commit()
        overdue = self.client.get(f"/api/v1/approval-cases/{created['case_id']}", headers=manager).json()
        self.assertEqual(overdue["sla_status"], "已超时")

        denied = self.client.post(
            f"/api/v1/approval-cases/{created['case_id']}/actions",
            json={"action": "withdraw", "reason": "无权撤回测试", "expected_row_version": overdue["row_version"]},
            headers={"Authorization": "Bearer dev-approver"},
        )
        self.assertEqual(denied.status_code, 403)
        withdrawn = self.client.post(
            f"/api/v1/approval-cases/{created['case_id']}/actions",
            json={"action": "withdraw", "reason": "客户主动取消本次申请", "expected_row_version": overdue["row_version"]},
            headers=manager,
        )
        self.assertEqual(withdrawn.status_code, 200)
        self.assertEqual(withdrawn.json()["status"], "已撤回")
        self.assertEqual(withdrawn.json()["sla_status"], "已停止")

        audit = self.client.get(f"/api/v1/audit-events?aggregate_id={created['case_id']}", headers={"Authorization": "Bearer dev-risk"})
        self.assertEqual(audit.json()[-1]["payload"]["action"], "withdraw")

    def test_sla_scan_notifications_escalation_and_read_tracking(self) -> None:
        manager = {"Authorization": "Bearer dev-manager"}
        admin = {"Authorization": "Bearer dev-admin"}
        created = self.client.post("/api/v1/approval-cases", json={"counterparty_id": self.counterparty["id"]}, headers=manager).json()
        with database.SessionLocal() as session:
            record = session.get(ApprovalCaseRecord, created["case_id"])
            record.stage_due_at = datetime.now(timezone.utc) + timedelta(minutes=30)
            session.commit()

        first_scan = self.client.post("/api/v1/operations/sla/scan", headers=admin)
        second_scan = self.client.post("/api/v1/operations/sla/scan", headers=admin)
        self.assertEqual(first_scan.status_code, 200)
        self.assertEqual(first_scan.json()["due_soon_cases"], 1)
        self.assertEqual(first_scan.json()["notifications_created"], 1)
        self.assertEqual(second_scan.json()["notifications_created"], 0)
        scan_audit = self.client.get(
            f"/api/v1/audit-events?aggregate_id={second_scan.json()['run_id']}",
            headers={"Authorization": "Bearer dev-operations"},
        )
        self.assertEqual(scan_audit.status_code, 200)
        self.assertEqual(scan_audit.json()[0]["event_type"], "sla_scan_completed")
        self.assertEqual(scan_audit.json()[0]["payload"]["notifications_created"], 0)

        manager_notifications = self.client.get("/api/v1/notifications?unread_only=true", headers=manager)
        self.assertEqual(len(manager_notifications.json()), 1)
        notification_id = manager_notifications.json()[0]["id"]
        denied = self.client.post(f"/api/v1/notifications/{notification_id}/read", headers={"Authorization": "Bearer dev-approver"})
        self.assertEqual(denied.status_code, 404)
        marked = self.client.post(f"/api/v1/notifications/{notification_id}/read", headers=manager)
        self.assertEqual(marked.status_code, 200)
        self.assertEqual(marked.json()["status"], "read")

        with database.SessionLocal() as session:
            record = session.get(ApprovalCaseRecord, created["case_id"])
            record.stage_due_at = datetime.now(timezone.utc) - timedelta(hours=5)
            session.commit()
        escalated_scan = self.client.post("/api/v1/operations/sla/scan", headers={"Authorization": "Bearer dev-operations"})
        self.assertEqual(escalated_scan.status_code, 200)
        self.assertEqual(escalated_scan.json()["escalated_cases"], 1)
        self.assertEqual(escalated_scan.json()["notifications_created"], 4)
        self.assertEqual(len(self.client.get("/api/v1/notifications?unread_only=true", headers={"Authorization": "Bearer dev-risk"}).json()), 1)
        self.assertEqual(len(self.client.get("/api/v1/notifications?unread_only=true", headers={"Authorization": "Bearer dev-approver"}).json()), 1)
        self.assertEqual(len(self.client.get("/api/v1/notifications?unread_only=true", headers={"Authorization": "Bearer dev-operations"}).json()), 1)
        invalid_limit = self.client.get("/api/v1/notifications?limit=0", headers=manager)
        self.assertEqual(invalid_limit.status_code, 422)

        summary = self.client.get("/api/v1/operations/sla/summary", headers={"Authorization": "Bearer dev-auditor"})
        forbidden_summary = self.client.get("/api/v1/operations/sla/summary", headers={"Authorization": "Bearer dev-client"})
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.json()["sla"]["escalated"], 1)
        self.assertEqual(summary.json()["last_scan"]["run_id"], escalated_scan.json()["run_id"])
        self.assertEqual(forbidden_summary.status_code, 403)

    def test_authentication_rbac_and_current_user(self) -> None:
        unauthorized = self.client.get("/api/v1/counterparties")
        forbidden = self.client.post("/api/v1/ratings/run", json={"counterparty_id": self.counterparty["id"], "template_key": "general"}, headers={"Authorization": "Bearer dev-client"})
        current_user = self.client.get("/api/v1/auth/me", headers={"Authorization": "Bearer dev-risk"})

        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(current_user.status_code, 200)
        self.assertIn("risk_manager", current_user.json()["roles"])

    def test_document_upload_download_and_client_data_scope(self) -> None:
        client_headers = {"Authorization": "Bearer dev-client"}
        uploaded = self.client.post(
            "/api/v1/documents",
            data={"counterparty_id": self.counterparty["id"], "document_type": "营业执照"},
            files={"file": ("license.pdf", b"%PDF-1.7\ndemo-pdf-content", "application/pdf")},
            headers=client_headers,
        )
        self.assertEqual(uploaded.status_code, 201)
        document_id = uploaded.json()["id"]
        self.assertEqual(uploaded.json()["sha256"], hashlib.sha256(b"%PDF-1.7\ndemo-pdf-content").hexdigest())

        documents = self.client.get("/api/v1/documents", headers=client_headers)
        downloaded = self.client.get(f"/api/v1/documents/{document_id}/download", headers=client_headers)
        denied = self.client.post(
            "/api/v1/documents",
            data={"counterparty_id": "cp_supplier_mid_001", "document_type": "营业执照"},
            files={"file": ("license.pdf", b"other", "application/pdf")},
            headers=client_headers,
        )
        self.assertEqual(len(documents.json()), 1)
        self.assertEqual(downloaded.content, b"%PDF-1.7\ndemo-pdf-content")
        self.assertEqual(denied.status_code, 403)

        disguised = self.client.post(
            "/api/v1/documents",
            data={"counterparty_id": self.counterparty["id"], "document_type": "营业执照"},
            files={"file": ("fake.pdf", b"not-a-pdf", "application/pdf")},
            headers=client_headers,
        )
        self.assertEqual(disguised.status_code, 415)

        unsupported_type = self.client.post(
            "/api/v1/documents",
            data={"counterparty_id": self.counterparty["id"], "document_type": "随意分类"},
            files={"file": ("other.pdf", b"%PDF-1.7\nother", "application/pdf")},
            headers=client_headers,
        )
        self.assertEqual(unsupported_type.status_code, 422)

    def test_document_checklist_and_four_eye_item_review(self) -> None:
        client_headers = {"Authorization": "Bearer dev-client"}
        risk_headers = {"Authorization": "Bearer dev-risk"}
        uploaded = self.client.post(
            "/api/v1/documents",
            data={"counterparty_id": self.counterparty["id"], "document_type": "营业执照"},
            files={"file": ("license.pdf", b"%PDF-1.7\nlicense", "application/pdf")},
            headers=client_headers,
        )
        self.assertEqual(uploaded.status_code, 201)
        self.assertEqual(uploaded.json()["review_status"], "pending_review")

        checklist = self.client.get(
            f"/api/v1/documents/checklist?counterparty_id={self.counterparty['id']}&template_key=tech_enterprise_basic",
            headers=risk_headers,
        )
        self.assertEqual(checklist.status_code, 200)
        self.assertGreaterEqual(checklist.json()["summary"]["total_count"], 20)
        self.assertTrue(any(item["document_type"] == "知识产权清单" for item in checklist.json()["items"]))
        self.assertEqual(len(checklist.json()["review_checks"]), 5)

        storage = LocalObjectStorage(self.temp_storage.name)
        storage.put(uploaded.json()["object_key"], b"%PDF-1.7\ntampered-license", "application/pdf")
        integrity_rejected = self.client.post(
            f"/api/v1/documents/{uploaded.json()['id']}/review",
            json={
                "decision": "verify",
                "comment": "文件指纹检查测试",
                "checks": [
                    {"key": item["key"], "label": "客户端不可覆盖标签", "status": "pass", "note": ""}
                    for item in checklist.json()["review_checks"]
                ],
                "expected_row_version": uploaded.json()["row_version"],
            },
            headers=risk_headers,
        )
        self.assertEqual(integrity_rejected.status_code, 409)
        storage.put(uploaded.json()["object_key"], b"%PDF-1.7\nlicense", "application/pdf")

        reviewed = self._review_document(uploaded.json())
        self.assertEqual(reviewed["status"], "已核验")
        self.assertEqual(reviewed["review_status"], "verified")
        self.assertEqual(len(reviewed["checklist"]), 5)
        self.assertEqual(reviewed["checklist"][0]["label"], "文件格式与指纹完整")

        not_applicable = self.client.post(
            f"/api/v1/documents/{uploaded.json()['id']}/review",
            json={
                "decision": "verify",
                "comment": "不适用项不能核验通过",
                "checks": [
                    {"key": item["key"], "label": item["label"], "status": "not_applicable" if index == 0 else "pass", "note": ""}
                    for index, item in enumerate(checklist.json()["review_checks"])
                ],
                "expected_row_version": reviewed["row_version"],
            },
            headers=risk_headers,
        )
        self.assertEqual(not_applicable.status_code, 422)

        stale = self.client.post(
            f"/api/v1/documents/{uploaded.json()['id']}/review",
            json={
                "decision": "verify",
                "comment": "重复审核测试",
                "checks": [
                    {"key": key, "label": label, "status": "pass", "note": ""}
                    for key, label in {
                        "integrity": "文件格式与指纹完整",
                        "entity_match": "企业名称及统一信用代码一致",
                        "validity": "证照、报告或证明仍在有效期",
                        "completeness": "关键页、签章和附件完整",
                        "legibility": "内容清晰可读且不存在明显涂改",
                    }.items()
                ],
                "expected_row_version": uploaded.json()["row_version"],
            },
            headers=risk_headers,
        )
        self.assertEqual(stale.status_code, 409)

    def test_document_precheck_flags_misclassified_files_without_replacing_review(self) -> None:
        headers = {"Authorization": "Bearer dev-manager"}
        matching_content = (
            f"营业执照\n企业名称：{self.counterparty['name']}\n"
            f"统一社会信用代码：{self.counterparty['credit_code']}\n法定代表人：测试人员"
        ).encode()
        matching = self.client.post(
            "/api/v1/documents",
            data={"counterparty_id": self.counterparty["id"], "document_type": "营业执照"},
            files={"file": ("营业执照.txt", matching_content, "text/plain")},
            headers=headers,
        )
        mismatched = self.client.post(
            "/api/v1/documents",
            data={"counterparty_id": self.counterparty["id"], "document_type": "营业执照"},
            files={"file": ("交付数据范围.txt", "字段范围与接口交付清单".encode(), "text/plain")},
            headers=headers,
        )
        self.assertEqual(matching.status_code, 201)
        self.assertEqual(mismatched.status_code, 201)

        response = self.client.get(
            f"/api/v1/documents/prechecks?counterparty_id={self.counterparty['id']}",
            headers={"Authorization": "Bearer dev-risk"},
        )
        self.assertEqual(response.status_code, 200)
        results = {item["document_id"]: item for item in response.json()}
        self.assertEqual(results[matching.json()["id"]]["overall_status"], "pass")
        self.assertEqual(results[mismatched.json()["id"]]["overall_status"], "warning")
        self.assertEqual(mismatched.json()["review_status"], "pending_review")
        self.assertIn("自动预检仅提供核验辅助", results[mismatched.json()["id"]]["disclaimer"])
        unbounded = self.client.get("/api/v1/documents/prechecks", headers=headers)
        self.assertEqual(unbounded.status_code, 422)

    def test_document_correction_replacement_version_chain_and_closure(self) -> None:
        manager = {"Authorization": "Bearer dev-manager"}
        risk = {"Authorization": "Bearer dev-risk"}
        created_case = self.client.post("/api/v1/approval-cases", json={"counterparty_id": self.counterparty["id"]}, headers=manager)
        case_id = created_case.json()["case_id"]
        original = self.client.post(
            "/api/v1/documents",
            data={"counterparty_id": self.counterparty["id"], "case_id": case_id, "document_type": "营业执照"},
            files={"file": ("错误资料.txt", "字段范围清单".encode(), "text/plain")},
            headers=manager,
        )
        self.assertEqual(original.status_code, 201)
        checklist = self.client.get(
            f"/api/v1/documents/checklist?counterparty_id={self.counterparty['id']}&case_id={case_id}",
            headers=risk,
        ).json()
        supplement = self.client.post(
            f"/api/v1/documents/{original.json()['id']}/review",
            json={
                "decision": "needs_supplement",
                "comment": "资料类型与主体均不一致，请重新上传营业执照",
                "checks": [
                    {"key": item["key"], "label": item["label"], "status": "fail" if item["key"] in {"entity_match", "completeness"} else "pass", "note": ""}
                    for item in checklist["review_checks"]
                ],
                "expected_row_version": original.json()["row_version"],
            },
            headers=risk,
        )
        self.assertEqual(supplement.status_code, 200)
        self.assertEqual(supplement.json()["review_status"], "needs_supplement")

        listed = self.client.get(
            f"/api/v1/documents/corrections?counterparty_id={self.counterparty['id']}&case_id={case_id}",
            headers=manager,
        )
        self.assertEqual(listed.status_code, 200)
        correction = listed.json()[0]
        self.assertEqual(correction["status"], "open")
        self.assertEqual(correction["version_document_ids"], [original.json()["id"]])
        self.assertEqual(set(correction["failed_check_keys"]), {"entity_match", "completeness"})

        replacement_content = (
            f"营业执照\n企业名称：{self.counterparty['name']}\n统一社会信用代码：{self.counterparty['credit_code']}"
        ).encode()
        mismatched_replacement = self.client.post(
            "/api/v1/documents",
            data={
                "counterparty_id": self.counterparty["id"],
                "case_id": case_id,
                "document_type": "财务报表",
                "correction_id": correction["id"],
            },
            files={"file": ("错误类型.txt", replacement_content, "text/plain")},
            headers=manager,
        )
        self.assertEqual(mismatched_replacement.status_code, 422)
        replacement = self.client.post(
            "/api/v1/documents",
            data={
                "counterparty_id": self.counterparty["id"],
                "case_id": case_id,
                "document_type": "营业执照",
                "correction_id": correction["id"],
            },
            files={"file": ("营业执照.txt", replacement_content, "text/plain")},
            headers=manager,
        )
        self.assertEqual(replacement.status_code, 201)
        resubmitted = self.client.get(
            f"/api/v1/documents/corrections?counterparty_id={self.counterparty['id']}&case_id={case_id}",
            headers=risk,
        ).json()[0]
        self.assertEqual(resubmitted["status"], "resubmitted")
        self.assertEqual(resubmitted["current_document_id"], replacement.json()["id"])
        self.assertEqual(resubmitted["version_document_ids"], [original.json()["id"], replacement.json()["id"]])
        self.assertEqual(resubmitted["attempt_count"], 1)

        second_supplement = self.client.post(
            f"/api/v1/documents/{replacement.json()['id']}/review",
            json={
                "decision": "needs_supplement",
                "comment": "证照有效期页仍不完整，请再次补交完整扫描件",
                "checks": [
                    {"key": item["key"], "label": item["label"], "status": "fail" if item["key"] == "validity" else "pass", "note": ""}
                    for item in checklist["review_checks"]
                ],
                "expected_row_version": replacement.json()["row_version"],
            },
            headers=risk,
        )
        self.assertEqual(second_supplement.status_code, 200)
        reopened = self.client.get(
            f"/api/v1/documents/corrections?counterparty_id={self.counterparty['id']}&case_id={case_id}",
            headers=manager,
        ).json()[0]
        self.assertEqual(reopened["status"], "open")
        self.assertEqual(reopened["reason"], "证照有效期页仍不完整，请再次补交完整扫描件")
        self.assertEqual(reopened["failed_check_keys"], ["validity"])

        final_replacement = self.client.post(
            "/api/v1/documents",
            data={
                "counterparty_id": self.counterparty["id"],
                "case_id": case_id,
                "document_type": "营业执照",
                "correction_id": correction["id"],
            },
            files={"file": ("营业执照完整扫描件.txt", replacement_content, "text/plain")},
            headers=manager,
        )
        self.assertEqual(final_replacement.status_code, 201)
        second_resubmission = self.client.get(
            f"/api/v1/documents/corrections?counterparty_id={self.counterparty['id']}&case_id={case_id}",
            headers=risk,
        ).json()[0]
        self.assertEqual(second_resubmission["attempt_count"], 2)
        self.assertEqual(
            second_resubmission["version_document_ids"],
            [original.json()["id"], replacement.json()["id"], final_replacement.json()["id"]],
        )

        verified = self._review_document(final_replacement.json())
        self.assertEqual(verified["review_status"], "verified")
        closed = self.client.get(
            f"/api/v1/documents/corrections?counterparty_id={self.counterparty['id']}&case_id={case_id}",
            headers=manager,
        ).json()[0]
        self.assertEqual(closed["status"], "closed")
        self.assertEqual(closed["resolved_by_name"], "风控经理")

        repeated_replacement = self.client.post(
            "/api/v1/documents",
            data={
                "counterparty_id": self.counterparty["id"],
                "case_id": case_id,
                "document_type": "营业执照",
                "correction_id": correction["id"],
            },
            files={"file": ("重复上传.txt", replacement_content, "text/plain")},
            headers=manager,
        )
        self.assertEqual(repeated_replacement.status_code, 422)

    def test_document_case_binding_and_office_package_validation(self) -> None:
        created = self.client.post("/api/v1/approval-cases", json={"counterparty_id": self.counterparty["id"]}, headers=self.headers)
        case_id = created.json()["case_id"]
        other_counterparty = demo_repository.list_counterparties()[1]

        mismatched = self.client.post(
            "/api/v1/documents",
            data={"counterparty_id": other_counterparty["id"], "case_id": case_id, "document_type": "财务报表"},
            files={"file": ("report.pdf", b"%PDF-1.7\ndemo", "application/pdf")},
            headers=self.headers,
        )
        self.assertEqual(mismatched.status_code, 422)

        fake_office = self.client.post(
            "/api/v1/documents",
            data={"counterparty_id": self.counterparty["id"], "case_id": case_id, "document_type": "财务报表"},
            files={"file": ("report.xlsx", b"PK\x03\x04not-an-office-package", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=self.headers,
        )
        self.assertEqual(fake_office.status_code, 415)

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types />")
            archive.writestr("xl/workbook.xml", "<workbook />")
        valid_office = self.client.post(
            "/api/v1/documents",
            data={"counterparty_id": self.counterparty["id"], "case_id": case_id, "document_type": "财务报表"},
            files={"file": ("report.xlsx", buffer.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=self.headers,
        )
        self.assertEqual(valid_office.status_code, 201)

        unlinked = self.client.post(
            "/api/v1/documents",
            data={"counterparty_id": self.counterparty["id"], "document_type": "应收账款账龄表"},
            files={"file": ("aging.pdf", b"%PDF-1.7\naging", "application/pdf")},
            headers=self.headers,
        )
        self.assertEqual(unlinked.status_code, 201)
        self.assertIsNone(unlinked.json()["case_id"])

        other_case = self.client.post(
            "/api/v1/approval-cases",
            json={"counterparty_id": other_counterparty["id"]},
            headers=self.headers,
        )
        mismatched_link = self.client.post(
            f"/api/v1/documents/{unlinked.json()['id']}/case",
            json={"case_id": other_case.json()["case_id"], "expected_row_version": unlinked.json()["row_version"]},
            headers=self.headers,
        )
        self.assertEqual(mismatched_link.status_code, 422)

        linked = self.client.post(
            f"/api/v1/documents/{unlinked.json()['id']}/case",
            json={"case_id": case_id, "expected_row_version": unlinked.json()["row_version"]},
            headers=self.headers,
        )
        self.assertEqual(linked.status_code, 200)
        self.assertEqual(linked.json()["case_id"], case_id)
        self.assertGreater(linked.json()["row_version"], unlinked.json()["row_version"])

        stale_link = self.client.post(
            f"/api/v1/documents/{unlinked.json()['id']}/case",
            json={"case_id": case_id, "expected_row_version": unlinked.json()["row_version"]},
            headers=self.headers,
        )
        self.assertEqual(stale_link.status_code, 409)


if __name__ == "__main__":
    unittest.main()
