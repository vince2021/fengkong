from __future__ import annotations

import json
import os
import sqlite3
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select

import backend.database as database
from backend.db_models import (
    ApprovalCaseRecord,
    CreditFacilityRecord,
    CreditReportRecord,
    CounterpartyRecord,
    DecisionVarianceRecord,
    DocumentCorrectionRecord,
    DocumentRecord,
    EnterpriseDataFieldRecord,
    EnterpriseDataImportRecord,
    EnterpriseDataResolutionRecord,
    FacilityControlConditionRecord,
    ModelSnapshotRecord,
    RatingRunRecord,
)
from backend.main import app
from backend.repository import (
    AuditRepository,
    AuditTenantResolutionError,
    NotificationRepository,
    audit_event_hash,
    clear_persistent_data,
    content_hash,
)
from backend.security import Principal, ROLE_PERMISSIONS, get_current_principal
from tests.database_support import IsolatedTestDatabase


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRIMARY_TENANT = "tenant-demo-hengxin"
ALTERNATE_TENANT = "tenant-demo-alt"
SHARED_COUNTERPARTY_ID = "cp_supplier_low_001"


def _principal(tenant_id: str, subject: str, role: str) -> Principal:
    return Principal(
        subject=subject,
        name=subject,
        roles=(role,),
        permissions=frozenset(ROLE_PERMISSIONS[role]),
        tenant_id=tenant_id,
        client_id=f"{tenant_id}-test-client",
    )


class TenantDomainIsolationApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.test_database = IsolatedTestDatabase()
        cls.test_database.start()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        app.dependency_overrides.clear()
        cls.test_database.stop()

    def setUp(self) -> None:
        app.dependency_overrides.clear()
        with database.SessionLocal() as session:
            clear_persistent_data(session)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def _as(self, principal: Principal) -> None:
        app.dependency_overrides[get_current_principal] = lambda: principal

    @staticmethod
    def _insert_facility(
        tenant_id: str,
        case: dict,
        facility_id: str,
        *,
        expires_at: datetime,
        next_review_at: datetime,
    ) -> None:
        now = datetime.now(timezone.utc)
        with database.SessionLocal() as session:
            session.add(
                CreditFacilityRecord(
                    id=facility_id,
                    tenant_id=tenant_id,
                    case_id=case["case_id"],
                    counterparty_id=case["counterparty_id"],
                    counterparty_name=case["counterparty_name"],
                    approved_limit=Decimal("100000.00"),
                    used_limit=Decimal("0.00"),
                    opening_balance=Decimal("0.00"),
                    payment_term_days=30,
                    rating="A",
                    access_strategy="准入",
                    monitoring_frequency="月度",
                    status="active",
                    effective_at=now - timedelta(days=30),
                    expires_at=expires_at,
                    next_review_at=next_review_at,
                    row_version=1,
                )
            )
            session.commit()

    def test_approval_cases_are_not_readable_or_mutable_across_tenants(self) -> None:
        primary_manager = _principal(PRIMARY_TENANT, "primary-manager", "relationship_manager")
        alternate_manager = _principal(ALTERNATE_TENANT, "alternate-manager", "relationship_manager")

        self._as(primary_manager)
        primary = self.client.post(
            "/api/v1/approval-cases",
            json={"counterparty_id": SHARED_COUNTERPARTY_ID},
        )
        self.assertEqual(primary.status_code, 201, primary.text)
        primary_case = primary.json()
        self.assertEqual(primary_case["tenant_id"], PRIMARY_TENANT)

        self._as(alternate_manager)
        hidden_detail = self.client.get(f"/api/v1/approval-cases/{primary_case['case_id']}")
        hidden_advance = self.client.post(
            f"/api/v1/approval-cases/{primary_case['case_id']}/advance",
            json={"expected_row_version": primary_case["row_version"], "payload": {}},
        )
        alternate = self.client.post(
            "/api/v1/approval-cases",
            json={"counterparty_id": SHARED_COUNTERPARTY_ID},
        )
        self.assertEqual(hidden_detail.status_code, 404)
        self.assertEqual(hidden_advance.status_code, 404)
        self.assertEqual(alternate.status_code, 201, alternate.text)
        alternate_case = alternate.json()
        self.assertEqual(alternate_case["tenant_id"], ALTERNATE_TENANT)

        alternate_list = self.client.get("/api/v1/approval-cases")
        self.assertEqual(alternate_list.status_code, 200, alternate_list.text)
        self.assertEqual([item["case_id"] for item in alternate_list.json()], [alternate_case["case_id"]])

        self._as(primary_manager)
        primary_list = self.client.get("/api/v1/approval-cases")
        self.assertEqual([item["case_id"] for item in primary_list.json()], [primary_case["case_id"]])
        unchanged = self.client.get(f"/api/v1/approval-cases/{primary_case['case_id']}")
        self.assertEqual(unchanged.json()["row_version"], primary_case["row_version"])

    def test_pending_indicator_observations_are_tenant_scoped(self) -> None:
        primary_manager = _principal(PRIMARY_TENANT, "primary-maker", "relationship_manager")
        primary_reviewer = _principal(PRIMARY_TENANT, "primary-reviewer", "risk_manager")
        alternate_manager = _principal(ALTERNATE_TENANT, "alternate-maker", "relationship_manager")
        alternate_reviewer = _principal(ALTERNATE_TENANT, "alternate-reviewer", "risk_manager")

        self._as(primary_reviewer)
        pool = self.client.get("/api/v1/indicator-pool?q=股东变更")
        self.assertEqual(pool.status_code, 200, pool.text)
        indicator = next(item for item in pool.json()["indicators"] if item["name"] == "股东变更")
        payload = {
            "counterparty_id": SHARED_COUNTERPARTY_ID,
            "indicator_id": indicator["id"],
            "values": {indicator["field_path"]: 2},
            "evidence_reference": "租户隔离自动化测试证据",
            "as_of_date": datetime.now(timezone.utc).date().isoformat(),
        }

        self._as(primary_manager)
        primary = self.client.post("/api/v1/indicator-observations", json=payload)
        self.assertEqual(primary.status_code, 201, primary.text)
        self.assertEqual(primary.json()["tenant_id"], PRIMARY_TENANT)

        self._as(alternate_manager)
        alternate = self.client.post("/api/v1/indicator-observations", json=payload)
        self.assertEqual(alternate.status_code, 201, alternate.text)
        self.assertEqual(alternate.json()["tenant_id"], ALTERNATE_TENANT)

        self._as(alternate_reviewer)
        hidden_detail = self.client.get(f"/api/v1/indicator-observations/{primary.json()['id']}")
        hidden_review = self.client.post(
            f"/api/v1/indicator-observations/{primary.json()['id']}/review",
            json={
                "expected_row_version": primary.json()["row_version"],
                "decision": "verify",
                "comment": "另一租户不应能够完成复核",
            },
        )
        self.assertEqual(hidden_detail.status_code, 404)
        self.assertEqual(hidden_review.status_code, 404)
        alternate_list = self.client.get(
            f"/api/v1/indicator-observations?counterparty_id={SHARED_COUNTERPARTY_ID}"
        )
        self.assertEqual([item["id"] for item in alternate_list.json()], [alternate.json()["id"]])

        self._as(primary_reviewer)
        reviewed = self.client.post(
            f"/api/v1/indicator-observations/{primary.json()['id']}/review",
            json={
                "expected_row_version": primary.json()["row_version"],
                "decision": "verify",
                "comment": "本租户独立复核通过",
            },
        )
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        self.assertEqual(reviewed.json()["status"], "verified")

    def test_creation_requires_counterparty_in_current_tenant(self) -> None:
        primary_manager = _principal(PRIMARY_TENANT, "primary-manager", "relationship_manager")
        alternate_manager = _principal(ALTERNATE_TENANT, "alternate-manager", "relationship_manager")
        isolated_counterparty_id = "cp_tenant_primary_only"
        self._as(primary_manager)
        created = self.client.post(
            "/api/v1/counterparties",
            json={
                "counterparty_id": isolated_counterparty_id,
                "credit_code": "91440300TENANTONLY1",
                "name": "仅主租户存在的测试企业",
                "counterparty_type": "supplier",
                "industry": "manufacturing",
                "cooperation_status": "active",
                "is_key_counterparty": False,
                "requested_limit": 100000,
                "current_limit": 0,
                "current_payment_term_days": 30,
                "external": {},
                "internal": {},
                "financial": {},
                "extensions": {},
                "reason": "验证跨租户主体存在性校验",
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        pool = self.client.get("/api/v1/indicator-pool?q=股东变更")
        indicator = next(item for item in pool.json()["indicators"] if item["name"] == "股东变更")

        self._as(alternate_manager)
        approval = self.client.post(
            "/api/v1/approval-cases",
            json={"counterparty_id": isolated_counterparty_id},
        )
        observation = self.client.post(
            "/api/v1/indicator-observations",
            json={
                "counterparty_id": isolated_counterparty_id,
                "indicator_id": indicator["id"],
                "values": {indicator["field_path"]: 1},
                "evidence_reference": "跨租户主体不存在，不应落库",
                "as_of_date": datetime.now(timezone.utc).date().isoformat(),
            },
        )
        self.assertEqual(approval.status_code, 404)
        self.assertEqual(observation.status_code, 404, observation.text)

    def test_approval_evidence_is_not_readable_or_mutable_across_tenants(self) -> None:
        primary_manager = _principal(PRIMARY_TENANT, "primary-manager", "relationship_manager")
        alternate_manager = _principal(ALTERNATE_TENANT, "alternate-manager", "relationship_manager")
        alternate_risk = _principal(ALTERNATE_TENANT, "alternate-risk", "risk_manager")
        alternate_operations = _principal(ALTERNATE_TENANT, "alternate-operations", "operations")

        self._as(primary_manager)
        primary_case_response = self.client.post(
            "/api/v1/approval-cases",
            json={"counterparty_id": SHARED_COUNTERPARTY_ID},
        )
        self.assertEqual(primary_case_response.status_code, 201, primary_case_response.text)
        primary_case = primary_case_response.json()

        self._as(alternate_manager)
        alternate_case_response = self.client.post(
            "/api/v1/approval-cases",
            json={"counterparty_id": SHARED_COUNTERPARTY_ID},
        )
        self.assertEqual(alternate_case_response.status_code, 201, alternate_case_response.text)
        alternate_case = alternate_case_response.json()

        now = datetime.now(timezone.utc)
        snapshot = {
            "counterparty": {"id": SHARED_COUNTERPARTY_ID, "name": "主租户测试企业"},
            "case": {"case_id": primary_case["case_id"], "status": "已完成"},
            "model": {"model_version": "tenant-isolation-v1"},
            "rating": {"rating": "A"},
            "proposal": {"suggested_limit": 100000},
            "decision": {"approved_limit": 100000},
            "documents": [],
        }
        with database.SessionLocal() as session:
            session.add(
                ModelSnapshotRecord(
                    id="snapshot-tenant-primary",
                    template_key="general",
                    model_name="租户隔离测试模型",
                    model_version="tenant-isolation-v1",
                    config_json={},
                    config_hash="a" * 64,
                )
            )
            session.add(
                RatingRunRecord(
                    id="rating-run-tenant-primary",
                    tenant_id=PRIMARY_TENANT,
                    counterparty_id=SHARED_COUNTERPARTY_ID,
                    case_id=primary_case["case_id"],
                    template_key="general",
                    model_snapshot_id="snapshot-tenant-primary",
                    input_json={"counterparty_id": SHARED_COUNTERPARTY_ID},
                    input_hash="b" * 64,
                    result_json={"rating": "A"},
                    result_hash="c" * 64,
                )
            )
            session.add(
                DocumentRecord(
                    id="document-tenant-primary",
                    tenant_id=PRIMARY_TENANT,
                    counterparty_id=SHARED_COUNTERPARTY_ID,
                    case_id=primary_case["case_id"],
                    document_type="营业执照",
                    original_name="primary-license.pdf",
                    object_key=f"{PRIMARY_TENANT}/{SHARED_COUNTERPARTY_ID}/primary-license.pdf",
                    content_type="application/pdf",
                    size_bytes=12,
                    sha256="d" * 64,
                    uploaded_by="primary-manager",
                    status="待补件",
                    review_status="needs_supplement",
                    checklist_json=[],
                    row_version=1,
                )
            )
            session.flush()
            session.add(
                DocumentCorrectionRecord(
                    id="correction-tenant-primary",
                    tenant_id=PRIMARY_TENANT,
                    counterparty_id=SHARED_COUNTERPARTY_ID,
                    case_id=primary_case["case_id"],
                    document_type="营业执照",
                    original_document_id="document-tenant-primary",
                    current_document_id="document-tenant-primary",
                    version_document_ids_json=["document-tenant-primary"],
                    status="open",
                    reason="验证跨租户补件任务隔离",
                    failed_check_keys_json=["integrity"],
                    requested_by="primary-risk",
                    requested_by_name="primary-risk",
                    assigned_role="relationship_manager",
                    sla_started_at=now,
                    sla_due_at=now + timedelta(hours=24),
                    row_version=1,
                )
            )
            session.add(
                CreditReportRecord(
                    id="report-tenant-primary",
                    tenant_id=PRIMARY_TENANT,
                    report_no="CR-TENANT-PRIMARY",
                    case_id=primary_case["case_id"],
                    counterparty_id=SHARED_COUNTERPARTY_ID,
                    report_version=1,
                    report_type="credit_decision",
                    status="sealed",
                    snapshot_json=snapshot,
                    snapshot_hash="e" * 64,
                    object_key=f"reports/{PRIMARY_TENANT}/{SHARED_COUNTERPARTY_ID}/report.pdf",
                    pdf_sha256="f" * 64,
                    size_bytes=12,
                    created_by="primary-approver",
                )
            )
            session.commit()

        self._as(primary_manager)
        self.assertEqual(
            [item["id"] for item in self.client.get("/api/v1/ratings/runs").json()],
            ["rating-run-tenant-primary"],
        )
        self.assertEqual(
            [item["id"] for item in self.client.get("/api/v1/documents").json()],
            ["document-tenant-primary"],
        )
        self.assertEqual(
            [item["id"] for item in self.client.get(
                f"/api/v1/documents/corrections?case_id={primary_case['case_id']}"
            ).json()],
            ["correction-tenant-primary"],
        )
        self.assertEqual(
            [item["id"] for item in self.client.get("/api/v1/credit-reports").json()],
            ["report-tenant-primary"],
        )

        self._as(alternate_manager)
        self.assertEqual(self.client.get("/api/v1/ratings/runs").json(), [])
        self.assertEqual(self.client.get("/api/v1/documents").json(), [])
        self.assertEqual(
            self.client.get(
                f"/api/v1/documents/corrections?case_id={alternate_case['case_id']}"
            ).json(),
            [],
        )
        self.assertEqual(self.client.get("/api/v1/credit-reports").json(), [])
        hidden_rating = self.client.get("/api/v1/ratings/runs/rating-run-tenant-primary")
        hidden_download = self.client.get("/api/v1/documents/document-tenant-primary/download")
        hidden_link = self.client.post(
            "/api/v1/documents/document-tenant-primary/case",
            json={"case_id": alternate_case["case_id"], "expected_row_version": 1},
        )
        hidden_comparison = self.client.get(
            "/api/v1/documents/corrections/correction-tenant-primary/comparison"
        )
        self.assertTrue(all(response.status_code == 404 for response in (
            hidden_rating,
            hidden_download,
            hidden_link,
            hidden_comparison,
        )))

        self._as(alternate_risk)
        hidden_review = self.client.post(
            "/api/v1/documents/document-tenant-primary/review",
            json={
                "expected_row_version": 1,
                "decision": "reject",
                "comment": "跨租户不允许复核资料",
                "checks": [
                    {"key": key, "label": label, "status": "fail", "note": "跨租户测试"}
                    for key, label in (
                        ("integrity", "文件格式与指纹完整"),
                        ("entity_match", "企业名称及统一信用代码一致"),
                        ("validity", "证照、报告或证明仍在有效期"),
                        ("completeness", "关键页、签章和附件完整"),
                        ("legibility", "内容清晰可读且不存在明显涂改"),
                    )
                ],
            },
        )
        self._as(alternate_operations)
        hidden_correction_action = self.client.post(
            "/api/v1/operations/document-corrections/correction-tenant-primary/actions",
            json={
                "expected_row_version": 1,
                "action": "remind",
                "reason": "跨租户不允许处置补件任务",
            },
        )
        self._as(alternate_risk)
        hidden_report = self.client.get("/api/v1/credit-reports/report-tenant-primary")
        hidden_integrity = self.client.get("/api/v1/credit-reports/report-tenant-primary/integrity")
        hidden_report_download = self.client.get("/api/v1/credit-reports/report-tenant-primary/download")
        self.assertEqual(
            {
                "document_review": hidden_review.status_code,
                "correction_action": hidden_correction_action.status_code,
                "report_detail": hidden_report.status_code,
                "report_integrity": hidden_integrity.status_code,
                "report_download": hidden_report_download.status_code,
            },
            {
                "document_review": 404,
                "correction_action": 404,
                "report_detail": 404,
                "report_integrity": 404,
                "report_download": 404,
            },
        )

    def test_credit_facility_and_post_credit_operations_are_tenant_scoped(self) -> None:
        primary_manager = _principal(PRIMARY_TENANT, "primary-manager", "relationship_manager")
        alternate_manager = _principal(ALTERNATE_TENANT, "alternate-manager", "relationship_manager")
        primary_risk = _principal(PRIMARY_TENANT, "primary-risk", "risk_manager")
        alternate_risk = _principal(ALTERNATE_TENANT, "alternate-risk", "risk_manager")

        self._as(primary_manager)
        primary_case_response = self.client.post(
            "/api/v1/approval-cases",
            json={"counterparty_id": SHARED_COUNTERPARTY_ID},
        )
        self.assertEqual(primary_case_response.status_code, 201, primary_case_response.text)
        primary_case = primary_case_response.json()

        self._as(alternate_manager)
        alternate_case_response = self.client.post(
            "/api/v1/approval-cases",
            json={"counterparty_id": SHARED_COUNTERPARTY_ID},
        )
        self.assertEqual(alternate_case_response.status_code, 201, alternate_case_response.text)
        alternate_case = alternate_case_response.json()

        now = datetime.now(timezone.utc)
        primary_facility_id = "facility-tenant-primary"
        alternate_facility_id = "facility-tenant-alternate"
        condition_id = "condition-tenant-primary"
        self._insert_facility(
            PRIMARY_TENANT,
            primary_case,
            primary_facility_id,
            expires_at=now + timedelta(days=180),
            next_review_at=now - timedelta(days=1),
        )
        self._insert_facility(
            ALTERNATE_TENANT,
            alternate_case,
            alternate_facility_id,
            expires_at=now - timedelta(days=1),
            next_review_at=now + timedelta(days=30),
        )
        with database.SessionLocal() as session:
            session.add(
                FacilityControlConditionRecord(
                    id=condition_id,
                    tenant_id=PRIMARY_TENANT,
                    facility_id=primary_facility_id,
                    source_case_id=primary_case["case_id"],
                    source_review_hash="tenant-isolation-review-hash",
                    sequence=1,
                    measure="完成租户隔离回归验证",
                    owner_role="risk_manager",
                    status="pending",
                    due_at=now + timedelta(days=10),
                    row_version=1,
                )
            )
            session.commit()

        self._as(primary_manager)
        primary_list = self.client.get("/api/v1/credit-facilities")
        primary_summary = self.client.get("/api/v1/credit-facilities/summary")
        self.assertEqual([item["id"] for item in primary_list.json()], [primary_facility_id])
        self.assertEqual(primary_summary.json()["total_facilities"], 1)
        primary_transaction = self.client.post(
            f"/api/v1/credit-facilities/{primary_facility_id}/transactions",
            json={
                "transaction_ref": "TX-SHARED-TENANT",
                "transaction_type": "drawdown",
                "amount": 1000,
                "expected_row_version": 1,
                "reason": "主租户额度占用",
            },
        )
        self.assertEqual(primary_transaction.status_code, 200, primary_transaction.text)
        primary_risk_event = self.client.post(
            f"/api/v1/credit-facilities/{primary_facility_id}/risk-events",
            json={
                "external_event_id": "EVENT-SHARED-TENANT",
                "event_type": "business_abnormal",
                "source": "tenant-isolation-test",
                "severity": "warning",
                "occurred_at": now.isoformat(),
                "title": "主租户风险事件",
                "description": "验证租户内事件和预警去重",
                "payload": {},
            },
        )
        self.assertEqual(primary_risk_event.status_code, 201, primary_risk_event.text)
        primary_alert = primary_risk_event.json()["alert"]

        self._as(alternate_manager)
        alternate_list = self.client.get("/api/v1/credit-facilities")
        alternate_summary = self.client.get("/api/v1/credit-facilities/summary")
        self.assertEqual([item["id"] for item in alternate_list.json()], [alternate_facility_id])
        self.assertEqual(alternate_summary.json()["total_facilities"], 1)
        alternate_transaction = self.client.post(
            f"/api/v1/credit-facilities/{alternate_facility_id}/transactions",
            json={
                "transaction_ref": "TX-SHARED-TENANT",
                "transaction_type": "drawdown",
                "amount": 1000,
                "expected_row_version": 1,
                "reason": "另一租户复用交易参考号",
            },
        )
        self.assertEqual(alternate_transaction.status_code, 422, alternate_transaction.text)
        self.assertIn("失效", alternate_transaction.json()["detail"])

        with database.SessionLocal() as session:
            alternate_facility = session.get(CreditFacilityRecord, alternate_facility_id)
            alternate_facility.expires_at = now + timedelta(days=180)
            session.commit()
            alternate_version = alternate_facility.row_version
        alternate_transaction = self.client.post(
            f"/api/v1/credit-facilities/{alternate_facility_id}/transactions",
            json={
                "transaction_ref": "TX-SHARED-TENANT",
                "transaction_type": "drawdown",
                "amount": 1000,
                "expected_row_version": alternate_version,
                "reason": "另一租户复用交易参考号",
            },
        )
        self.assertEqual(alternate_transaction.status_code, 200, alternate_transaction.text)
        alternate_risk_event = self.client.post(
            f"/api/v1/credit-facilities/{alternate_facility_id}/risk-events",
            json={
                "external_event_id": "EVENT-SHARED-TENANT",
                "event_type": "business_abnormal",
                "source": "tenant-isolation-test",
                "severity": "warning",
                "occurred_at": now.isoformat(),
                "title": "另一租户风险事件",
                "description": "另一租户复用相同外部事件号",
                "payload": {},
            },
        )
        self.assertEqual(alternate_risk_event.status_code, 201, alternate_risk_event.text)
        alternate_alert = alternate_risk_event.json()["alert"]
        self.assertEqual(alternate_risk_event.json()["risk_event"]["tenant_id"], ALTERNATE_TENANT)
        self.assertEqual(alternate_alert["tenant_id"], ALTERNATE_TENANT)
        self.assertEqual(
            [item["id"] for item in self.client.get("/api/v1/credit-facilities/risk-events").json()],
            [alternate_risk_event.json()["risk_event"]["id"]],
        )
        self.assertEqual(
            [item["id"] for item in self.client.get("/api/v1/credit-facilities/alerts").json()],
            [alternate_alert["id"]],
        )

        hidden_detail = self.client.get(f"/api/v1/credit-facilities/{primary_facility_id}")
        hidden_transaction = self.client.post(
            f"/api/v1/credit-facilities/{primary_facility_id}/transactions",
            json={
                "transaction_ref": "TX-CROSS-TENANT",
                "transaction_type": "drawdown",
                "amount": 100,
                "expected_row_version": 2,
                "reason": "跨租户交易不应成功",
            },
        )
        hidden_event = self.client.post(
            f"/api/v1/credit-facilities/{primary_facility_id}/risk-events",
            json={
                "external_event_id": "EVENT-CROSS-TENANT",
                "event_type": "other",
                "source": "tenant-isolation-test",
                "severity": "warning",
                "occurred_at": now.isoformat(),
                "title": "跨租户风险事件",
                "description": "跨租户事件不应成功",
                "payload": {},
            },
        )
        self.assertEqual(hidden_detail.status_code, 404)
        self.assertEqual(hidden_transaction.status_code, 404)
        self.assertEqual(hidden_event.status_code, 404)

        self._as(alternate_risk)
        hidden_review = self.client.post(
            f"/api/v1/credit-facilities/{primary_facility_id}/reviews",
            json={
                "expected_row_version": 2,
                "rating": "A-",
                "next_review_days": 30,
                "conclusion": "跨租户复评不应成功",
            },
        )
        hidden_control = self.client.post(
            f"/api/v1/credit-facilities/{primary_facility_id}/controls",
            json={"expected_row_version": 2, "action": "freeze", "reason": "跨租户控制不应成功"},
        )
        hidden_completion = self.client.post(
            f"/api/v1/credit-facilities/{primary_facility_id}/control-conditions/{condition_id}/complete",
            json={"expected_row_version": 1, "conclusion": "跨租户不能完成控制条件"},
        )
        hidden_extension = self.client.post(
            f"/api/v1/credit-facilities/{primary_facility_id}/control-conditions/{condition_id}/extensions",
            json={"expected_condition_version": 1, "extension_days": 5, "reason": "跨租户不能申请控制条件延期"},
        )
        hidden_acknowledgement = self.client.post(
            f"/api/v1/credit-facilities/alerts/{primary_alert['id']}/acknowledge"
        )
        hidden_disposition = self.client.post(
            f"/api/v1/credit-facilities/alerts/{primary_alert['id']}/dispose",
            json={
                "expected_alert_version": primary_alert["row_version"],
                "expected_facility_version": 2,
                "action": "monitor",
                "conclusion": "跨租户不能处置预警",
            },
        )
        self.assertTrue(all(response.status_code == 404 for response in (
            hidden_review,
            hidden_control,
            hidden_completion,
            hidden_extension,
            hidden_acknowledgement,
            hidden_disposition,
        )))

        with database.SessionLocal() as session:
            alternate_facility = session.get(CreditFacilityRecord, alternate_facility_id)
            alternate_facility.expires_at = now - timedelta(days=1)
            session.commit()
        self._as(primary_risk)
        scan = self.client.post("/api/v1/credit-facilities/scan")
        self.assertEqual(scan.status_code, 200, scan.text)
        self.assertEqual(scan.json()["tenant_id"], PRIMARY_TENANT)
        self.assertEqual(scan.json()["active_facilities_scanned"], 1)
        with database.SessionLocal() as session:
            self.assertEqual(session.get(CreditFacilityRecord, alternate_facility_id).status, "active")

    def test_data_governance_batches_and_variances_are_tenant_scoped(self) -> None:
        primary_manager = _principal(PRIMARY_TENANT, "primary-manager", "relationship_manager")
        alternate_manager = _principal(ALTERNATE_TENANT, "alternate-manager", "relationship_manager")
        primary_risk = _principal(PRIMARY_TENANT, "primary-risk", "risk_manager")
        alternate_risk = _principal(ALTERNATE_TENANT, "alternate-risk", "risk_manager")
        today = datetime.now(timezone.utc).date().isoformat()

        with database.SessionLocal() as session:
            primary_code = session.execute(
                select(CounterpartyRecord.credit_code).where(
                    CounterpartyRecord.tenant_id == PRIMARY_TENANT,
                    CounterpartyRecord.counterparty_id == SHARED_COUNTERPARTY_ID,
                )
            ).scalar_one()

        def import_payload(principal: Principal, key: str, representative: str, source: str) -> dict:
            self._as(principal)
            response = self.client.post(
                "/api/v1/data-governance/imports",
                json={
                    "import_key": key,
                    "counterparty_id": SHARED_COUNTERPARTY_ID,
                    "source_type": source,
                    "source_name": f"{principal.tenant_id}-{source}",
                    "schema_version": "1.0",
                    "as_of_date": today,
                    "evidence_reference": f"tenant-test://{principal.tenant_id}/{key}",
                    "payload": {
                        "entity": {
                            "unified_social_credit_code": primary_code,
                            "legal_representative": representative,
                        }
                    },
                },
            )
            self.assertEqual(response.status_code, 201, response.text)
            return response.json()

        primary_first = import_payload(primary_manager, "DATA-SHARED-TENANT", "张三", "official_registry")
        alternate_first = import_payload(alternate_manager, "DATA-SHARED-TENANT", "王五", "official_registry")
        import_payload(primary_manager, "DATA-PRIMARY-CONFLICT", "李四", "management_submission")
        self.assertEqual(primary_first["tenant_id"], PRIMARY_TENANT)
        self.assertEqual(alternate_first["tenant_id"], ALTERNATE_TENANT)

        self._as(primary_manager)
        primary_conflict = self.client.get(
            f"/api/v1/data-governance/counterparties/{SHARED_COUNTERPARTY_ID}/conflicts"
        ).json()[0]
        selected = next(item for item in primary_conflict["candidates"] if item["value"] == "李四")
        proposed = self.client.post(
            "/api/v1/data-governance/resolutions",
            json={
                "counterparty_id": SHARED_COUNTERPARTY_ID,
                "field_path": "entity.legal_representative",
                "selected_field_id": selected["id"],
                "reason_category": "source_confirmation",
                "rationale": "主租户已核对管理层提交资料并确认最新法定代表人。",
            },
        )
        self.assertEqual(proposed.status_code, 201, proposed.text)
        self.assertEqual(proposed.json()["tenant_id"], PRIMARY_TENANT)

        self._as(alternate_manager)
        alternate_imports = self.client.get(
            f"/api/v1/data-governance/imports?counterparty_id={SHARED_COUNTERPARTY_ID}"
        )
        alternate_profile = self.client.get(
            f"/api/v1/data-governance/counterparties/{SHARED_COUNTERPARTY_ID}/profile"
        )
        alternate_conflicts = self.client.get(
            f"/api/v1/data-governance/counterparties/{SHARED_COUNTERPARTY_ID}/conflicts"
        )
        alternate_resolutions = self.client.get(
            f"/api/v1/data-governance/resolutions?counterparty_id={SHARED_COUNTERPARTY_ID}"
        )
        self.assertEqual([item["id"] for item in alternate_imports.json()], [alternate_first["id"]])
        self.assertEqual(alternate_profile.json()["profile"]["entity"]["legal_representative"], "王五")
        self.assertEqual(alternate_conflicts.json(), [])
        self.assertEqual(alternate_resolutions.json(), [])

        self._as(alternate_risk)
        hidden_review = self.client.post(
            f"/api/v1/data-governance/resolutions/{proposed.json()['id']}/review",
            json={
                "expected_row_version": proposed.json()["row_version"],
                "decision": "approve",
                "comment": "另一租户不得审核该字段冲突裁决。",
            },
        )
        self.assertEqual(hidden_review.status_code, 404)

        batch_request = {
            "batch_key": "RATING-BATCH-SHARED-TENANT",
            "template_key": "general",
            "counterparty_type": "supplier",
        }
        self._as(primary_risk)
        primary_batch = self.client.post("/api/v1/ratings/batches", json=batch_request)
        self.assertEqual(primary_batch.status_code, 201, primary_batch.text)
        self._as(alternate_risk)
        alternate_batch = self.client.post("/api/v1/ratings/batches", json=batch_request)
        self.assertEqual(alternate_batch.status_code, 201, alternate_batch.text)
        self.assertNotEqual(primary_batch.json()["id"], alternate_batch.json()["id"])
        self.assertEqual(alternate_batch.json()["tenant_id"], ALTERNATE_TENANT)
        self.assertEqual(
            [item["id"] for item in self.client.get("/api/v1/ratings/batches").json()],
            [alternate_batch.json()["id"]],
        )
        self.assertEqual(
            self.client.get(f"/api/v1/ratings/batches/{primary_batch.json()['id']}").status_code,
            404,
        )

        self._as(primary_manager)
        primary_case = self.client.post(
            "/api/v1/approval-cases", json={"counterparty_id": SHARED_COUNTERPARTY_ID}
        ).json()
        self._as(alternate_manager)
        alternate_case = self.client.post(
            "/api/v1/approval-cases", json={"counterparty_id": SHARED_COUNTERPARTY_ID}
        ).json()
        with database.SessionLocal() as session:
            session.add_all([
                DecisionVarianceRecord(
                    id="variance-tenant-primary",
                    tenant_id=PRIMARY_TENANT,
                    case_id=primary_case["case_id"],
                    counterparty_id=SHARED_COUNTERPARTY_ID,
                    counterparty_name="主租户企业",
                    direction="stricter",
                    materiality="minor",
                    recommendation_json={},
                    decision_json={},
                    variance_json={"deltas": {"limit_amount": -1000, "limit_ratio": -0.1}},
                    compensating_controls=[],
                    decided_by="primary-approver",
                ),
                DecisionVarianceRecord(
                    id="variance-tenant-alternate",
                    tenant_id=ALTERNATE_TENANT,
                    case_id=alternate_case["case_id"],
                    counterparty_id=SHARED_COUNTERPARTY_ID,
                    counterparty_name="另一租户企业",
                    direction="aligned",
                    materiality="none",
                    recommendation_json={},
                    decision_json={},
                    variance_json={"deltas": {"limit_amount": 0, "limit_ratio": 0}},
                    compensating_controls=[],
                    decided_by="alternate-approver",
                ),
            ])
            session.commit()
        self._as(alternate_risk)
        variances = self.client.get("/api/v1/decision-governance/variances")
        summary = self.client.get("/api/v1/decision-governance/summary")
        hidden_case = self.client.get(
            f"/api/v1/decision-governance/variances?case_id={primary_case['case_id']}"
        )
        self.assertEqual([item["id"] for item in variances.json()], ["variance-tenant-alternate"])
        self.assertEqual(summary.json()["total"], 1)
        self.assertEqual(summary.json()["aligned_count"], 1)
        self.assertEqual(hidden_case.json(), [])

    def test_notifications_and_manual_sla_scan_are_tenant_scoped(self) -> None:
        primary_manager = _principal(PRIMARY_TENANT, "primary-manager", "relationship_manager")
        alternate_manager = _principal(ALTERNATE_TENANT, "alternate-manager", "relationship_manager")
        primary_operations = _principal(PRIMARY_TENANT, "primary-operations", "operations")
        alternate_operations = _principal(ALTERNATE_TENANT, "alternate-operations", "operations")

        self._as(primary_manager)
        primary_case = self.client.post(
            "/api/v1/approval-cases", json={"counterparty_id": SHARED_COUNTERPARTY_ID}
        ).json()
        self._as(alternate_manager)
        alternate_case = self.client.post(
            "/api/v1/approval-cases", json={"counterparty_id": SHARED_COUNTERPARTY_ID}
        ).json()
        with database.SessionLocal() as session:
            due_at = datetime.now(timezone.utc) + timedelta(minutes=20)
            primary_record = session.execute(
                select(ApprovalCaseRecord).where(ApprovalCaseRecord.case_id == primary_case["case_id"])
            ).scalar_one()
            alternate_record = session.execute(
                select(ApprovalCaseRecord).where(ApprovalCaseRecord.case_id == alternate_case["case_id"])
            ).scalar_one()
            primary_record.stage_due_at = due_at
            alternate_record.stage_due_at = due_at
            session.commit()

        self._as(alternate_manager)
        cross_tenant_claim = self.client.post(
            f"/api/v1/operations/my-tasks/approval/{primary_case['case_id']}/assignment",
            json={"action": "claim", "expected_row_version": primary_case["row_version"]},
        )
        self.assertEqual(cross_tenant_claim.status_code, 404)

        self._as(primary_operations)
        primary_board_ids = {
            item["case_id"] for item in self.client.get("/api/v1/operations/team-tasks").json()["tasks"]
            if item["case_id"]
        }
        self._as(alternate_operations)
        alternate_board_ids = {
            item["case_id"] for item in self.client.get("/api/v1/operations/team-tasks").json()["tasks"]
            if item["case_id"]
        }
        self.assertIn(primary_case["case_id"], primary_board_ids)
        self.assertNotIn(alternate_case["case_id"], primary_board_ids)
        self.assertIn(alternate_case["case_id"], alternate_board_ids)
        self.assertNotIn(primary_case["case_id"], alternate_board_ids)

        self._as(primary_operations)
        scan = self.client.post("/api/v1/operations/sla/scan")
        self.assertEqual(scan.status_code, 200, scan.text)
        self.assertEqual(scan.json()["tenant_id"], PRIMARY_TENANT)
        self.assertEqual(scan.json()["active_cases_scanned"], 1)
        self.assertEqual(scan.json()["due_soon_cases"], 1)

        self._as(primary_manager)
        primary_notifications = self.client.get("/api/v1/notifications").json()
        self.assertEqual(len(primary_notifications), 1)
        primary_notification_id = primary_notifications[0]["id"]
        self.assertEqual(primary_notifications[0]["tenant_id"], PRIMARY_TENANT)

        self._as(alternate_manager)
        self.assertEqual(self.client.get("/api/v1/notifications").json(), [])
        self.assertEqual(
            self.client.post(f"/api/v1/notifications/{primary_notification_id}/read").status_code,
            404,
        )

        payload = {
            "case_id": None,
            "counterparty_id": None,
            "recipient_role": "risk_manager",
            "recipient_subject": None,
            "category": "tenant_test",
            "level": "opened",
            "severity": "warning",
            "title": "租户内通知",
            "message": "验证同一去重键可以由不同租户独立使用。",
            "action_json": {},
            "dedup_key": "shared-tenant-notification-key",
            "status": "unread",
        }
        with database.SessionLocal() as session:
            repository = NotificationRepository(session)
            primary_created, primary_was_created = repository.create_if_absent(PRIMARY_TENANT, payload)
            _, primary_duplicate_created = repository.create_if_absent(PRIMARY_TENANT, payload)
            alternate_created, alternate_was_created = repository.create_if_absent(ALTERNATE_TENANT, payload)
            repository.commit()
        self.assertTrue(primary_was_created)
        self.assertFalse(primary_duplicate_created)
        self.assertTrue(alternate_was_created)
        self.assertNotEqual(primary_created["id"], alternate_created["id"])

    def test_audit_hash_chains_are_isolated_by_tenant_and_scope(self) -> None:
        shared_aggregate_id = "AUDIT-SHARED-AGGREGATE"
        platform_aggregate_id = "AUDIT-PLATFORM-AGGREGATE"
        with database.SessionLocal() as session:
            audit = AuditRepository(session)
            primary_root, primary_created = audit.append_root_once(
                "sla_scan",
                shared_aggregate_id,
                "tenant_audit_started",
                "primary-auditor",
                {"tenant_id": PRIMARY_TENANT, "step": 1},
            )
            alternate_root, alternate_created = audit.append_root_once(
                "sla_scan",
                shared_aggregate_id,
                "tenant_audit_started",
                "alternate-auditor",
                {"tenant_id": ALTERNATE_TENANT, "step": 1},
            )
            primary_tail = audit.append(
                "sla_scan",
                shared_aggregate_id,
                "tenant_audit_completed",
                "primary-auditor",
                {"tenant_id": PRIMARY_TENANT, "step": 2},
            )
            alternate_tail = audit.append(
                "sla_scan",
                shared_aggregate_id,
                "tenant_audit_completed",
                "alternate-auditor",
                {"tenant_id": ALTERNATE_TENANT, "step": 2},
            )
            platform = audit.append(
                "model_change",
                platform_aggregate_id,
                "platform_audit_created",
                "platform-admin",
                {"change": "platform baseline"},
            )
            with self.assertRaises(AuditTenantResolutionError):
                audit.append(
                    "counterparty",
                    f"{PRIMARY_TENANT}:{SHARED_COUNTERPARTY_ID}",
                    "tenant_conflict_attempted",
                    "malicious-actor",
                    {"tenant_id": ALTERNATE_TENANT},
                )
            with self.assertRaises(AuditTenantResolutionError):
                audit.append(
                    "sla_scan",
                    "AUDIT-MANUAL-WITHOUT-TENANT",
                    "sla_scan_completed",
                    "unknown-tenant-operator",
                    {"trigger_type": "manual"},
                )
            session.commit()

        self.assertTrue(primary_created)
        self.assertTrue(alternate_created)
        self.assertEqual(primary_tail["previous_hash"], primary_root["event_hash"])
        self.assertEqual(alternate_tail["previous_hash"], alternate_root["event_hash"])
        self.assertNotEqual(primary_root["event_hash"], alternate_root["event_hash"])
        self.assertEqual(platform["tenant_id"], "tenant-platform-internal")
        self.assertEqual(platform["scope_type"], "platform")

        for tenant_id, expected_actor in (
            (PRIMARY_TENANT, "primary-auditor"),
            (ALTERNATE_TENANT, "alternate-auditor"),
        ):
            self._as(_principal(tenant_id, f"{tenant_id}-auditor", "auditor"))
            visible = self.client.get(
                f"/api/v1/audit-events?aggregate_id={shared_aggregate_id}"
            )
            hidden_platform = self.client.get(
                f"/api/v1/audit-events?aggregate_id={platform_aggregate_id}"
            )
            self.assertEqual(visible.status_code, 200, visible.text)
            self.assertEqual(len(visible.json()), 2)
            self.assertEqual({item["tenant_id"] for item in visible.json()}, {tenant_id})
            self.assertEqual({item["scope_type"] for item in visible.json()}, {"tenant"})
            self.assertEqual({item["actor"] for item in visible.json()}, {expected_actor})
            self.assertEqual(hidden_platform.json(), [])

        self._as(_principal("tenant-platform-internal", "platform-auditor", "auditor"))
        self.assertEqual(
            self.client.get(
                f"/api/v1/audit-events?aggregate_id={shared_aggregate_id}"
            ).json(),
            [],
        )
        visible_platform = self.client.get(
            f"/api/v1/audit-events?aggregate_id={platform_aggregate_id}"
        ).json()
        self.assertEqual(
            [item["event_type"] for item in visible_platform],
            ["platform_audit_created"],
        )

        expected_hash = audit_event_hash(
            event_id=primary_root["id"],
            tenant_id=primary_root["tenant_id"],
            scope_type=primary_root["scope_type"],
            aggregate_type=primary_root["aggregate_type"],
            aggregate_id=primary_root["aggregate_id"],
            event_type=primary_root["event_type"],
            actor=primary_root["actor"],
            payload=primary_root["payload"],
            previous_hash=primary_root["previous_hash"],
        )
        tampered_tenant_hash = audit_event_hash(
            event_id=primary_root["id"],
            tenant_id=ALTERNATE_TENANT,
            scope_type=primary_root["scope_type"],
            aggregate_type=primary_root["aggregate_type"],
            aggregate_id=primary_root["aggregate_id"],
            event_type=primary_root["event_type"],
            actor=primary_root["actor"],
            payload=primary_root["payload"],
            previous_hash=primary_root["previous_hash"],
        )
        self.assertEqual(expected_hash, primary_root["event_hash"])
        self.assertNotEqual(tampered_tenant_hash, primary_root["event_hash"])


class TenantDomainMigrationTest(unittest.TestCase):
    @contextmanager
    def _database_at_0081(self):
        with TemporaryDirectory() as directory:
            database_path = Path(directory) / "platform.db"
            url = f"sqlite:///{database_path}"
            config = Config(str(PROJECT_ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
            config.set_main_option("sqlalchemy.url", url)
            with patch.dict(os.environ, {"DATABASE_URL": url}):
                command.upgrade(config, "20260907_0081")
                yield config, database_path

    @staticmethod
    def _insert_tenant(connection: sqlite3.Connection, tenant_id: str) -> None:
        connection.execute(
            "INSERT INTO tenants(id,name,deployment_mode,status,data_region,row_version) VALUES(?,?,?,?,?,1)",
            (tenant_id, tenant_id, "saas", "active", "cn"),
        )

    @staticmethod
    def _insert_counterparty(connection: sqlite3.Connection, tenant_id: str, counterparty_id: str, suffix: str) -> None:
        connection.execute(
            """
            INSERT INTO counterparties(
                id,tenant_id,counterparty_id,credit_code,name,counterparty_type,industry,
                cooperation_status,is_key_counterparty,requested_limit,current_limit,
                current_payment_term_days,external_json,internal_json,financial_json,
                extensions_json,profile_hash,status,source_type,created_by,updated_by,row_version
            ) VALUES(?,?,?,?,?,'supplier','manufacturing','active',0,0,0,30,'{}','{}','{}','{}',
                     ?,'active','manual','migration-test','migration-test',1)
            """,
            (f"row-{suffix}", tenant_id, counterparty_id, f"CREDIT-{suffix}", f"企业-{suffix}", f"hash-{suffix}"),
        )

    @staticmethod
    def _insert_legacy_approval(connection: sqlite3.Connection, counterparty_id: str, case_id: str) -> None:
        connection.execute(
            """
            INSERT INTO approval_cases(
                case_id,counterparty_id,counterparty_name,application_type,current_stage,status,
                completed_stages,data,timeline,row_version
            ) VALUES(?,?,?,'new_credit','registration','处理中','[]','{}','[]',1)
            """,
            (case_id, counterparty_id, counterparty_id),
        )

    @staticmethod
    def _insert_scoped_approval(
        connection: sqlite3.Connection,
        tenant_id: str,
        counterparty_id: str,
        case_id: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO approval_cases(
                case_id,tenant_id,counterparty_id,counterparty_name,application_type,
                current_stage,status,completed_stages,data,timeline,row_version
            ) VALUES(?,?,?,?,'new_credit','registration','处理中','[]','{}','[]',1)
            """,
            (case_id, tenant_id, counterparty_id, counterparty_id),
        )

    @staticmethod
    def _insert_legacy_approval_evidence(
        connection: sqlite3.Connection,
        case_id: str,
        counterparty_id: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO model_snapshots(
                id,template_key,model_name,model_version,config_json,config_hash
            ) VALUES('SNAPSHOT-LEGACY','general','历史评级模型','legacy-v1','{}',?)
            """,
            ("a" * 64,),
        )
        connection.execute(
            """
            INSERT INTO rating_runs(
                id,counterparty_id,case_id,template_key,model_snapshot_id,input_json,input_hash,
                result_json,result_hash
            ) VALUES('RATING-LEGACY',?,?,'general','SNAPSHOT-LEGACY','{}',?,'{}',?)
            """,
            (counterparty_id, case_id, "b" * 64, "c" * 64),
        )
        connection.execute(
            """
            INSERT INTO documents(
                id,counterparty_id,case_id,document_type,original_name,object_key,content_type,
                size_bytes,sha256,uploaded_by,status,checklist_json,review_status,row_version
            ) VALUES('DOCUMENT-ORIGINAL',?,?,'营业执照','original.pdf','legacy/original.pdf',
                     'application/pdf',12,?,'migration-test','待补件','[]','needs_supplement',1)
            """,
            (counterparty_id, case_id, "d" * 64),
        )
        connection.execute(
            """
            INSERT INTO documents(
                id,counterparty_id,case_id,document_type,original_name,object_key,content_type,
                size_bytes,sha256,uploaded_by,status,checklist_json,review_status,
                source_document_id,row_version
            ) VALUES('DOCUMENT-CURRENT',?,?,'营业执照','current.pdf','legacy/current.pdf',
                     'application/pdf',12,?,'migration-test','已上传','[]','pending_review',
                     'DOCUMENT-ORIGINAL',1)
            """,
            (counterparty_id, case_id, "e" * 64),
        )
        connection.execute(
            """
            INSERT INTO document_corrections(
                id,counterparty_id,case_id,document_type,original_document_id,current_document_id,
                version_document_ids_json,status,reason,failed_check_keys_json,attempt_count,
                requested_by,requested_by_name,assigned_role,sla_started_at,sla_due_at,row_version
            ) VALUES('CORRECTION-LEGACY',?,?,'营业执照','DOCUMENT-ORIGINAL','DOCUMENT-CURRENT',
                     '["DOCUMENT-ORIGINAL","DOCUMENT-CURRENT"]','resubmitted','历史补件',
                     '["integrity"]',1,'migration-test','migration-test','risk_manager',
                     '2026-09-01 00:00:00','2026-09-02 00:00:00',1)
            """,
            (counterparty_id, case_id),
        )
        connection.execute(
            """
            INSERT INTO credit_reports(
                id,report_no,case_id,counterparty_id,report_version,report_type,status,
                snapshot_json,snapshot_hash,object_key,pdf_sha256,size_bytes,created_by
            ) VALUES('REPORT-LEGACY','CR-LEGACY',?,?,1,'credit_decision','sealed','{}',?,
                     'reports/legacy.pdf',?,12,'migration-test')
            """,
            (case_id, counterparty_id, "f" * 64, "0" * 64),
        )

    @staticmethod
    def _insert_legacy_data_governance_records(
        connection: sqlite3.Connection,
        case_id: str,
        counterparty_id: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO enterprise_data_imports(
                id,import_key,counterparty_id,source_type,source_name,source_priority,
                schema_version,as_of_date,evidence_reference,payload_hash,status,field_count,
                conflict_count,stale_count,invalid_count,quality_score,quality_json,created_by
            ) VALUES('IMPORT-LEGACY','DATA-LEGACY',?,'official_registry','历史工商',100,
                     '1.0','2026-09-01 00:00:00','legacy://registry',?,'accepted',1,
                     0,0,0,1.0,'{}','migration-test')
            """,
            (counterparty_id, "4" * 64),
        )
        connection.execute(
            """
            INSERT INTO enterprise_data_fields(
                id,import_id,counterparty_id,field_path,value_json,value_hash,value_type,
                source_type,source_name,source_priority,evidence_reference,observed_at,
                freshness_days,freshness_status,validation_status,conflict_status
            ) VALUES('FIELD-LEGACY','IMPORT-LEGACY',?,'entity.legal_representative','"张三"',?,
                     'string','official_registry','历史工商',100,'legacy://registry',
                     '2026-09-01 00:00:00',365,'fresh','valid','none')
            """,
            (counterparty_id, "5" * 64),
        )
        connection.execute(
            """
            INSERT INTO enterprise_data_resolutions(
                id,counterparty_id,field_path,selected_field_id,selected_value_json,
                selected_value_hash,candidate_snapshot_hash,candidate_count,reason_category,
                rationale,status,created_by,created_by_name,row_version
            ) VALUES('RESOLUTION-LEGACY',?,'entity.legal_representative','FIELD-LEGACY',
                     '"张三"',?,?,2,'source_confirmation','历史字段裁决','approved',
                     'migration-test','migration-test',1)
            """,
            (counterparty_id, "5" * 64, "6" * 64),
        )
        connection.execute(
            """
            INSERT INTO portfolio_rating_batches(
                id,batch_key,request_hash,template_key,model_version,scope_type,status,
                candidate_count,success_count,skipped_count,summary_json,results_json,
                skipped_json,result_hash,created_by,created_by_name
            ) VALUES('BATCH-LEGACY','BATCH-LEGACY',?,'general','legacy-v1','supplier',
                     'completed',1,1,0,'{}','[]','[]',?,'migration-test','migration-test')
            """,
            ("7" * 64, "8" * 64),
        )
        connection.execute(
            """
            INSERT INTO decision_variances(
                id,case_id,counterparty_id,counterparty_name,direction,materiality,
                recommendation_json,decision_json,variance_json,compensating_controls,decided_by
            ) VALUES('VARIANCE-LEGACY',?,?,?,'aligned','none','{}','{}','{}','[]',
                     'migration-test')
            """,
            (case_id, counterparty_id, counterparty_id),
        )

    @staticmethod
    def _insert_legacy_notification(
        connection: sqlite3.Connection,
        notification_id: str,
        dedup_key: str,
        *,
        case_id: str | None = None,
        counterparty_id: str | None = None,
        category: str = "approval_sla",
    ) -> None:
        connection.execute(
            """
            INSERT INTO notifications(
                id,case_id,counterparty_id,recipient_role,recipient_subject,category,level,
                severity,title,message,action_json,dedup_key,status
            ) VALUES(?,?,?,'operations',NULL,?,'due_soon','warning',
                     '历史通知','历史通知迁移测试','{}',?,'unread')
            """,
            (notification_id, case_id, counterparty_id, category, dedup_key),
        )

    @staticmethod
    def _insert_legacy_audit_event(
        connection: sqlite3.Connection,
        *,
        event_id: str,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        payload: dict,
        previous_hash: str = "",
    ) -> str:
        event_hash = content_hash({
            "id": event_id,
            "aggregate_type": aggregate_type,
            "aggregate_id": aggregate_id,
            "event_type": event_type,
            "actor": "migration-test",
            "payload": payload,
            "previous_hash": previous_hash,
        })
        connection.execute(
            """
            INSERT INTO audit_events(
                id,aggregate_type,aggregate_id,event_type,actor,payload,
                previous_hash,event_hash
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                event_id,
                aggregate_type,
                aggregate_id,
                event_type,
                "migration-test",
                json.dumps(payload, ensure_ascii=False),
                previous_hash,
                event_hash,
            ),
        )
        return event_hash

    @staticmethod
    def _insert_legacy_facility(
        connection: sqlite3.Connection,
        facility_id: str,
        case_id: str,
        counterparty_id: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO credit_facilities(
                id,case_id,counterparty_id,counterparty_name,approved_limit,used_limit,
                opening_balance,payment_term_days,rating,access_strategy,monitoring_frequency,
                status,effective_at,expires_at,next_review_at,row_version
            ) VALUES(?,?,?,?,100000,1000,0,30,'A','准入','月度','active',
                     '2026-08-01 00:00:00','2027-08-01 00:00:00','2026-10-01 00:00:00',1)
            """,
            (facility_id, case_id, counterparty_id, counterparty_id),
        )

    @staticmethod
    def _insert_legacy_facility_children(
        connection: sqlite3.Connection,
        facility_id: str,
        case_id: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO credit_usage_transactions(
                id,facility_id,transaction_ref,transaction_type,amount,balance_after,
                occurred_at,actor,reason
            ) VALUES('TX-ROW',?,'TX-LEGACY','drawdown',1000,1000,
                     '2026-08-01 00:00:00','migration-test','历史交易')
            """,
            (facility_id,),
        )
        connection.execute(
            """
            INSERT INTO facility_alerts(
                id,facility_id,alert_type,severity,title,message,dedup_key,status,row_version
            ) VALUES('ALERT-LEGACY',?,'review_due','warning','待复评','历史预警',
                     'review:legacy','open',1)
            """,
            (facility_id,),
        )
        connection.execute(
            """
            INSERT INTO risk_events(
                id,facility_id,external_event_id,event_type,source,severity,occurred_at,
                title,description,payload,linked_alert_id,status,created_by
            ) VALUES('EVENT-ROW',?,'EVENT-LEGACY','business_abnormal','migration-test',
                     'warning','2026-08-01 00:00:00','经营异常','历史风险事件','{}',
                     'ALERT-LEGACY','active','migration-test')
            """,
            (facility_id,),
        )
        connection.execute(
            """
            INSERT INTO facility_control_conditions(
                id,facility_id,source_case_id,source_review_hash,sequence,measure,
                owner_role,status,due_at,linked_alert_id,row_version
            ) VALUES('CONDITION-LEGACY',?,?, 'legacy-review-hash',1,'补充历史核验材料',
                     'risk_manager','pending','2026-10-01 00:00:00','ALERT-LEGACY',1)
            """,
            (facility_id, case_id),
        )
        connection.execute(
            """
            INSERT INTO facility_control_extensions(
                id,condition_id,facility_id,extension_days,previous_due_at,proposed_due_at,
                reason,status,requested_by,requested_by_name,requested_at,row_version
            ) VALUES('EXTENSION-LEGACY','CONDITION-LEGACY',?,10,'2026-10-01 00:00:00',
                     '2026-10-11 00:00:00','历史延期申请','pending','risk-user','风控经理',
                     '2026-09-01 00:00:00',1)
            """,
            (facility_id,),
        )

    def test_0082_backfills_legacy_rows_and_round_trips(self) -> None:
        with self._database_at_0081() as (config, database_path):
            with sqlite3.connect(database_path) as connection:
                self._insert_tenant(connection, PRIMARY_TENANT)
                self._insert_tenant(connection, ALTERNATE_TENANT)
                self._insert_counterparty(connection, PRIMARY_TENANT, "CP-SAME", "primary")
                self._insert_counterparty(connection, ALTERNATE_TENANT, "CP-SAME", "alternate")
                self._insert_legacy_approval(connection, "CP-SAME", "CASE-LEGACY")
                connection.execute(
                    """
                    INSERT INTO enterprise_indicator_observations(
                        id,counterparty_id,indicator_id,indicator_name,values_json,values_hash,
                        evidence_reference,observed_at,status,created_by,created_by_name,row_version
                    ) VALUES('OBS-LEGACY','CP-SAME','IND-001','指标一','{}','hash','migration-test',
                             '2026-09-07 00:00:00','pending_review','maker','提交人',1)
                    """
                )
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                command.upgrade(config, "20260907_0082")

            engine = create_engine(config.get_main_option("sqlalchemy.url"))
            schema = inspect(engine)
            approval_columns = {item["name"]: item for item in schema.get_columns("approval_cases")}
            observation_columns = {item["name"]: item for item in schema.get_columns("enterprise_indicator_observations")}
            self.assertFalse(approval_columns["tenant_id"]["nullable"])
            self.assertFalse(observation_columns["tenant_id"]["nullable"])
            self.assertTrue(any(
                item["constrained_columns"] == ["tenant_id", "counterparty_id"]
                for item in schema.get_foreign_keys("approval_cases")
            ))
            indexes = {item["name"]: item for item in schema.get_indexes("enterprise_indicator_observations")}
            self.assertEqual(
                indexes["uq_indicator_observations_pending"]["column_names"],
                ["tenant_id", "counterparty_id", "indicator_id"],
            )
            engine.dispose()
            with sqlite3.connect(database_path) as connection:
                self.assertEqual(
                    connection.execute("SELECT tenant_id FROM approval_cases WHERE case_id='CASE-LEGACY'").fetchone()[0],
                    PRIMARY_TENANT,
                )
                self.assertEqual(
                    connection.execute("SELECT tenant_id FROM enterprise_indicator_observations WHERE id='OBS-LEGACY'").fetchone()[0],
                    PRIMARY_TENANT,
                )

            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                command.downgrade(config, "20260907_0081")
                command.upgrade(config, "20260907_0082")

    def test_0082_rejects_missing_counterparty_backfill(self) -> None:
        with self._database_at_0081() as (config, database_path):
            with sqlite3.connect(database_path) as connection:
                self._insert_tenant(connection, PRIMARY_TENANT)
                self._insert_legacy_approval(connection, "CP-MISSING", "CASE-MISSING")
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                with self.assertRaisesRegex(RuntimeError, "is not registered in counterparties"):
                    command.upgrade(config, "20260907_0082")

    def test_0082_rejects_ambiguous_nonlegacy_counterparty_backfill(self) -> None:
        with self._database_at_0081() as (config, database_path):
            with sqlite3.connect(database_path) as connection:
                self._insert_tenant(connection, "tenant-a")
                self._insert_tenant(connection, "tenant-b")
                self._insert_counterparty(connection, "tenant-a", "CP-AMBIGUOUS", "a")
                self._insert_counterparty(connection, "tenant-b", "CP-AMBIGUOUS", "b")
                self._insert_legacy_approval(connection, "CP-AMBIGUOUS", "CASE-AMBIGUOUS")
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                with self.assertRaisesRegex(RuntimeError, "is ambiguous across tenants"):
                    command.upgrade(config, "20260907_0082")

    def test_0083_backfills_facility_domain_and_round_trips(self) -> None:
        tables = (
            "credit_facilities",
            "credit_usage_transactions",
            "facility_alerts",
            "risk_events",
            "facility_control_conditions",
            "facility_control_extensions",
        )
        with self._database_at_0081() as (config, database_path):
            with sqlite3.connect(database_path) as connection:
                self._insert_tenant(connection, PRIMARY_TENANT)
                self._insert_counterparty(connection, PRIMARY_TENANT, "CP-FACILITY", "facility")
                self._insert_legacy_approval(connection, "CP-FACILITY", "CASE-FACILITY")
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                command.upgrade(config, "20260907_0082")
            with sqlite3.connect(database_path) as connection:
                self._insert_legacy_facility(connection, "FACILITY-LEGACY", "CASE-FACILITY", "CP-FACILITY")
                self._insert_legacy_facility_children(connection, "FACILITY-LEGACY", "CASE-FACILITY")
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                command.upgrade(config, "20260908_0083")

            engine = create_engine(config.get_main_option("sqlalchemy.url"))
            schema = inspect(engine)
            for table_name in tables:
                columns = {item["name"]: item for item in schema.get_columns(table_name)}
                self.assertIn("tenant_id", columns)
                self.assertFalse(columns["tenant_id"]["nullable"])
                self.assertTrue(any(
                    item["constrained_columns"][:1] == ["tenant_id"]
                    for item in schema.get_foreign_keys(table_name)
                ))
            facility_foreign_keys = {
                tuple(item["constrained_columns"])
                for item in schema.get_foreign_keys("credit_facilities")
            }
            self.assertIn(("tenant_id", "case_id"), facility_foreign_keys)
            self.assertIn(("tenant_id", "counterparty_id"), facility_foreign_keys)
            usage_uniques = {
                tuple(item["column_names"])
                for item in schema.get_unique_constraints("credit_usage_transactions")
            }
            alert_uniques = {
                tuple(item["column_names"])
                for item in schema.get_unique_constraints("facility_alerts")
            }
            self.assertIn(("tenant_id", "transaction_ref"), usage_uniques)
            self.assertIn(("tenant_id", "dedup_key"), alert_uniques)
            risk_indexes = {item["name"]: item for item in schema.get_indexes("risk_events")}
            self.assertEqual(
                risk_indexes["uq_risk_events_source_external_id"]["column_names"],
                ["tenant_id", "source", "external_event_id"],
            )
            engine.dispose()

            with sqlite3.connect(database_path) as connection:
                for table_name in tables:
                    tenant_ids = connection.execute(
                        f"SELECT DISTINCT tenant_id FROM {table_name}"
                    ).fetchall()
                    self.assertEqual(tenant_ids, [(PRIMARY_TENANT,)])

            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                command.downgrade(config, "20260907_0082")
                command.upgrade(config, "20260908_0083")

    def test_0083_rejects_facility_without_matching_approval(self) -> None:
        with self._database_at_0081() as (config, database_path):
            with sqlite3.connect(database_path) as connection:
                self._insert_tenant(connection, PRIMARY_TENANT)
                self._insert_counterparty(connection, PRIMARY_TENANT, "CP-FACILITY", "facility")
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                command.upgrade(config, "20260907_0082")
            with sqlite3.connect(database_path) as connection:
                self._insert_legacy_facility(connection, "FACILITY-ORPHAN", "CASE-MISSING", "CP-FACILITY")
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                with self.assertRaisesRegex(RuntimeError, "has no matching tenant approval/counterparty"):
                    command.upgrade(config, "20260908_0083")

    def test_0083_rejects_child_without_matching_facility(self) -> None:
        with self._database_at_0081() as (config, database_path):
            with sqlite3.connect(database_path) as connection:
                self._insert_tenant(connection, PRIMARY_TENANT)
                self._insert_counterparty(connection, PRIMARY_TENANT, "CP-FACILITY", "facility")
                self._insert_legacy_approval(connection, "CP-FACILITY", "CASE-FACILITY")
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                command.upgrade(config, "20260907_0082")
            with sqlite3.connect(database_path) as connection:
                connection.execute(
                    """
                    INSERT INTO credit_usage_transactions(
                        id,facility_id,transaction_ref,transaction_type,amount,balance_after,
                        occurred_at,actor,reason
                    ) VALUES('TX-ORPHAN','FACILITY-MISSING','TX-ORPHAN','drawdown',100,100,
                             '2026-08-01 00:00:00','migration-test','孤立历史交易')
                    """
                )
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                with self.assertRaisesRegex(RuntimeError, "has no matching credit facility"):
                    command.upgrade(config, "20260908_0083")

    def test_0083_downgrade_rejects_unrepresentable_cross_tenant_keys(self) -> None:
        with self._database_at_0081() as (config, database_path):
            with sqlite3.connect(database_path) as connection:
                self._insert_tenant(connection, PRIMARY_TENANT)
                self._insert_tenant(connection, ALTERNATE_TENANT)
                self._insert_counterparty(connection, PRIMARY_TENANT, "CP-PRIMARY", "primary-facility")
                self._insert_counterparty(connection, ALTERNATE_TENANT, "CP-ALTERNATE", "alternate-facility")
                self._insert_legacy_approval(connection, "CP-PRIMARY", "CASE-PRIMARY")
                self._insert_legacy_approval(connection, "CP-ALTERNATE", "CASE-ALTERNATE")
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                command.upgrade(config, "20260907_0082")
            with sqlite3.connect(database_path) as connection:
                self._insert_legacy_facility(connection, "FACILITY-PRIMARY", "CASE-PRIMARY", "CP-PRIMARY")
                self._insert_legacy_facility(connection, "FACILITY-ALTERNATE", "CASE-ALTERNATE", "CP-ALTERNATE")
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                command.upgrade(config, "20260908_0083")
            with sqlite3.connect(database_path) as connection:
                connection.execute(
                    """
                    INSERT INTO facility_alerts(
                        id,tenant_id,facility_id,alert_type,severity,title,message,dedup_key,status,row_version
                    ) VALUES('ALERT-PRIMARY',?,'FACILITY-PRIMARY','review_due','warning',
                             '主租户预警','主租户预警','SHARED-DEDUP','open',1)
                    """,
                    (PRIMARY_TENANT,),
                )
                connection.execute(
                    """
                    INSERT INTO facility_alerts(
                        id,tenant_id,facility_id,alert_type,severity,title,message,dedup_key,status,row_version
                    ) VALUES('ALERT-ALTERNATE',?,'FACILITY-ALTERNATE','review_due','warning',
                             '另一租户预警','另一租户预警','SHARED-DEDUP','open',1)
                    """,
                    (ALTERNATE_TENANT,),
                )
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                with self.assertRaisesRegex(RuntimeError, "cannot be represented"):
                    command.downgrade(config, "20260907_0082")

    def test_0084_backfills_approval_evidence_and_round_trips(self) -> None:
        tables = ("documents", "document_corrections", "rating_runs", "credit_reports")
        with self._database_at_0081() as (config, database_path):
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                command.upgrade(config, "20260908_0083")
            with sqlite3.connect(database_path) as connection:
                self._insert_tenant(connection, PRIMARY_TENANT)
                self._insert_counterparty(connection, PRIMARY_TENANT, "CP-EVIDENCE", "evidence")
                self._insert_scoped_approval(connection, PRIMARY_TENANT, "CP-EVIDENCE", "CASE-EVIDENCE")
                self._insert_legacy_approval_evidence(connection, "CASE-EVIDENCE", "CP-EVIDENCE")
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                command.upgrade(config, "20260908_0084")

            engine = create_engine(config.get_main_option("sqlalchemy.url"))
            schema = inspect(engine)
            for table_name in tables:
                columns = {item["name"]: item for item in schema.get_columns(table_name)}
                self.assertFalse(columns["tenant_id"]["nullable"])
                indexes = {item["name"] for item in schema.get_indexes(table_name)}
                self.assertIn(f"ix_{table_name}_tenant_id", indexes)
            self.assertIn(
                ("tenant_id", "source_document_id"),
                {tuple(item["constrained_columns"]) for item in schema.get_foreign_keys("documents")},
            )
            correction_foreign_keys = {
                tuple(item["constrained_columns"])
                for item in schema.get_foreign_keys("document_corrections")
            }
            self.assertIn(("tenant_id", "original_document_id"), correction_foreign_keys)
            self.assertIn(("tenant_id", "current_document_id"), correction_foreign_keys)
            report_uniques = {
                tuple(item["column_names"])
                for item in schema.get_unique_constraints("credit_reports")
            }
            self.assertIn(("tenant_id", "case_id", "snapshot_hash"), report_uniques)
            self.assertIn(("tenant_id", "case_id", "report_version"), report_uniques)
            engine.dispose()

            with sqlite3.connect(database_path) as connection:
                for table_name in tables:
                    tenant_ids = connection.execute(
                        f"SELECT DISTINCT tenant_id FROM {table_name}"
                    ).fetchall()
                    self.assertEqual(tenant_ids, [(PRIMARY_TENANT,)])

            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                command.downgrade(config, "20260908_0083")
                command.upgrade(config, "20260908_0084")

    def test_0084_rejects_ambiguous_unbound_document(self) -> None:
        with self._database_at_0081() as (config, database_path):
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                command.upgrade(config, "20260908_0083")
            with sqlite3.connect(database_path) as connection:
                self._insert_tenant(connection, "tenant-a")
                self._insert_tenant(connection, "tenant-b")
                self._insert_counterparty(connection, "tenant-a", "CP-AMBIGUOUS-EVIDENCE", "evidence-a")
                self._insert_counterparty(connection, "tenant-b", "CP-AMBIGUOUS-EVIDENCE", "evidence-b")
                connection.execute(
                    """
                    INSERT INTO documents(
                        id,counterparty_id,document_type,original_name,object_key,content_type,
                        size_bytes,sha256,uploaded_by,status,checklist_json,review_status,row_version
                    ) VALUES('DOCUMENT-AMBIGUOUS','CP-AMBIGUOUS-EVIDENCE','营业执照',
                             'ambiguous.pdf','legacy/ambiguous.pdf','application/pdf',12,?,
                             'migration-test','已上传','[]','pending_review',1)
                    """,
                    ("1" * 64,),
                )
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                with self.assertRaisesRegex(RuntimeError, "missing or ambiguous counterparty ownership"):
                    command.upgrade(config, "20260908_0084")

    def test_0084_rejects_report_with_mismatched_approval_counterparty(self) -> None:
        with self._database_at_0081() as (config, database_path):
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                command.upgrade(config, "20260908_0083")
            with sqlite3.connect(database_path) as connection:
                self._insert_tenant(connection, PRIMARY_TENANT)
                self._insert_counterparty(connection, PRIMARY_TENANT, "CP-CASE", "report-case")
                self._insert_counterparty(connection, PRIMARY_TENANT, "CP-REPORT", "report-row")
                self._insert_scoped_approval(connection, PRIMARY_TENANT, "CP-CASE", "CASE-REPORT-MISMATCH")
                connection.execute(
                    """
                    INSERT INTO credit_reports(
                        id,report_no,case_id,counterparty_id,report_version,report_type,status,
                        snapshot_json,snapshot_hash,object_key,pdf_sha256,size_bytes,created_by
                    ) VALUES('REPORT-MISMATCH','CR-MISMATCH','CASE-REPORT-MISMATCH','CP-REPORT',
                             1,'credit_decision','sealed','{}',?,'reports/mismatch.pdf',?,12,
                             'migration-test')
                    """,
                    ("2" * 64, "3" * 64),
                )
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                with self.assertRaisesRegex(RuntimeError, "has no matching approval/counterparty"):
                    command.upgrade(config, "20260908_0084")

    def test_0085_backfills_data_governance_and_decision_evidence_round_trip(self) -> None:
        tables = (
            "enterprise_data_imports",
            "enterprise_data_fields",
            "enterprise_data_resolutions",
            "portfolio_rating_batches",
            "decision_variances",
        )
        with self._database_at_0081() as (config, database_path):
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                command.upgrade(config, "20260908_0084")
            with sqlite3.connect(database_path) as connection:
                self._insert_tenant(connection, PRIMARY_TENANT)
                self._insert_counterparty(connection, PRIMARY_TENANT, "CP-DATA", "data")
                self._insert_scoped_approval(connection, PRIMARY_TENANT, "CP-DATA", "CASE-DATA")
                self._insert_legacy_data_governance_records(connection, "CASE-DATA", "CP-DATA")
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                command.upgrade(config, "20260908_0085")

            engine = create_engine(config.get_main_option("sqlalchemy.url"))
            schema = inspect(engine)
            for table_name in tables:
                columns = {item["name"]: item for item in schema.get_columns(table_name)}
                self.assertFalse(columns["tenant_id"]["nullable"])
                self.assertIn(
                    f"ix_{table_name}_tenant_id",
                    {item["name"] for item in schema.get_indexes(table_name)},
                )
            self.assertIn(
                ("tenant_id", "import_id"),
                {tuple(item["constrained_columns"]) for item in schema.get_foreign_keys("enterprise_data_fields")},
            )
            self.assertIn(
                ("tenant_id", "selected_field_id"),
                {tuple(item["constrained_columns"]) for item in schema.get_foreign_keys("enterprise_data_resolutions")},
            )
            variance_foreign_keys = {
                tuple(item["constrained_columns"])
                for item in schema.get_foreign_keys("decision_variances")
            }
            self.assertIn(("tenant_id", "case_id"), variance_foreign_keys)
            self.assertIn(("tenant_id", "rating_run_id"), variance_foreign_keys)
            import_uniques = {
                tuple(item["column_names"])
                for item in schema.get_unique_constraints("enterprise_data_imports")
            }
            batch_uniques = {
                tuple(item["column_names"])
                for item in schema.get_unique_constraints("portfolio_rating_batches")
            }
            self.assertIn(("tenant_id", "import_key"), import_uniques)
            self.assertIn(("tenant_id", "batch_key"), batch_uniques)
            engine.dispose()

            with sqlite3.connect(database_path) as connection:
                for table_name in tables:
                    self.assertEqual(
                        connection.execute(f"SELECT DISTINCT tenant_id FROM {table_name}").fetchall(),
                        [(PRIMARY_TENANT,)],
                    )

            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                command.downgrade(config, "20260908_0084")
                command.upgrade(config, "20260908_0085")

    def test_0085_rejects_ambiguous_enterprise_data_import(self) -> None:
        with self._database_at_0081() as (config, database_path):
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                command.upgrade(config, "20260908_0084")
            with sqlite3.connect(database_path) as connection:
                self._insert_tenant(connection, "tenant-a")
                self._insert_tenant(connection, "tenant-b")
                self._insert_counterparty(connection, "tenant-a", "CP-DATA-AMBIGUOUS", "data-a")
                self._insert_counterparty(connection, "tenant-b", "CP-DATA-AMBIGUOUS", "data-b")
                connection.execute(
                    """
                    INSERT INTO enterprise_data_imports(
                        id,import_key,counterparty_id,source_type,source_name,source_priority,
                        schema_version,as_of_date,evidence_reference,payload_hash,status,
                        field_count,conflict_count,stale_count,invalid_count,quality_score,
                        quality_json,created_by
                    ) VALUES('IMPORT-AMBIGUOUS','DATA-AMBIGUOUS','CP-DATA-AMBIGUOUS',
                             'official_registry','历史工商',100,'1.0','2026-09-01 00:00:00',
                             'legacy://ambiguous',?,'accepted',0,0,0,0,1.0,'{}','migration-test')
                    """,
                    ("9" * 64,),
                )
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                with self.assertRaisesRegex(RuntimeError, "missing or ambiguous counterparty ownership"):
                    command.upgrade(config, "20260908_0085")

    def test_0085_downgrade_rejects_cross_tenant_reused_batch_key(self) -> None:
        with self._database_at_0081() as (config, database_path):
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                command.upgrade(config, "20260908_0085")
            with sqlite3.connect(database_path) as connection:
                for tenant_id, row_id in (("tenant-a", "BATCH-A"), ("tenant-b", "BATCH-B")):
                    connection.execute(
                        """
                        INSERT INTO portfolio_rating_batches(
                            id,tenant_id,batch_key,request_hash,template_key,model_version,
                            scope_type,status,candidate_count,success_count,skipped_count,
                            summary_json,results_json,skipped_json,result_hash,created_by,
                            created_by_name
                        ) VALUES(?,?,'BATCH-SHARED-DOWNGRADE',?,'general','v1','supplier',
                                 'completed',0,0,0,'{}','[]','[]',?,'migration-test',
                                 'migration-test')
                        """,
                        (row_id, tenant_id, "a" * 64, "b" * 64),
                    )
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                with self.assertRaisesRegex(RuntimeError, "cannot be represented"):
                    command.downgrade(config, "20260908_0084")

    def test_0086_backfills_notifications_and_round_trips(self) -> None:
        with self._database_at_0081() as (config, database_path):
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                command.upgrade(config, "20260908_0085")
            with sqlite3.connect(database_path) as connection:
                self._insert_tenant(connection, PRIMARY_TENANT)
                self._insert_tenant(connection, "tenant-platform-internal")
                self._insert_counterparty(connection, PRIMARY_TENANT, "CP-NOTIFY", "notify")
                self._insert_scoped_approval(connection, PRIMARY_TENANT, "CP-NOTIFY", "CASE-NOTIFY")
                self._insert_legacy_notification(
                    connection,
                    "NOTIFICATION-CASE",
                    "notification-case",
                    case_id="CASE-NOTIFY",
                    counterparty_id="CP-NOTIFY",
                )
                self._insert_legacy_notification(
                    connection,
                    "NOTIFICATION-SYSTEM",
                    "notification-system",
                    category="sla_scan",
                )
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                command.upgrade(config, "20260908_0086")

            engine = create_engine(config.get_main_option("sqlalchemy.url"))
            schema = inspect(engine)
            columns = {item["name"]: item for item in schema.get_columns("notifications")}
            self.assertFalse(columns["tenant_id"]["nullable"])
            self.assertIn(
                ("tenant_id", "dedup_key"),
                {tuple(item["column_names"]) for item in schema.get_unique_constraints("notifications")},
            )
            foreign_keys = {
                tuple(item["constrained_columns"])
                for item in schema.get_foreign_keys("notifications")
            }
            self.assertIn(("tenant_id", "case_id"), foreign_keys)
            self.assertIn(("tenant_id", "counterparty_id"), foreign_keys)
            engine.dispose()

            with sqlite3.connect(database_path) as connection:
                owners = dict(connection.execute(
                    "SELECT id,tenant_id FROM notifications ORDER BY id"
                ).fetchall())
            self.assertEqual(owners["NOTIFICATION-CASE"], PRIMARY_TENANT)
            self.assertEqual(owners["NOTIFICATION-SYSTEM"], "tenant-platform-internal")

            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                command.downgrade(config, "20260908_0085")
                command.upgrade(config, "20260908_0086")

    def test_0086_rejects_ambiguous_notification_counterparty(self) -> None:
        with self._database_at_0081() as (config, database_path):
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                command.upgrade(config, "20260908_0085")
            with sqlite3.connect(database_path) as connection:
                self._insert_tenant(connection, "tenant-a")
                self._insert_tenant(connection, "tenant-b")
                self._insert_counterparty(connection, "tenant-a", "CP-NOTIFY-AMBIGUOUS", "notify-a")
                self._insert_counterparty(connection, "tenant-b", "CP-NOTIFY-AMBIGUOUS", "notify-b")
                self._insert_legacy_notification(
                    connection,
                    "NOTIFICATION-AMBIGUOUS",
                    "notification-ambiguous",
                    counterparty_id="CP-NOTIFY-AMBIGUOUS",
                )
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                with self.assertRaisesRegex(RuntimeError, "missing or ambiguous counterparty ownership"):
                    command.upgrade(config, "20260908_0086")

    def test_0086_downgrade_rejects_cross_tenant_reused_dedup_key(self) -> None:
        with self._database_at_0081() as (config, database_path):
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                command.upgrade(config, "20260908_0086")
            with sqlite3.connect(database_path) as connection:
                self._insert_tenant(connection, "tenant-a")
                self._insert_tenant(connection, "tenant-b")
                for tenant_id, notification_id in (
                    ("tenant-a", "NOTIFICATION-A"),
                    ("tenant-b", "NOTIFICATION-B"),
                ):
                    connection.execute(
                        """
                        INSERT INTO notifications(
                            id,tenant_id,case_id,counterparty_id,recipient_role,recipient_subject,
                            category,level,severity,title,message,action_json,dedup_key,status
                        ) VALUES(?,?,NULL,NULL,'operations',NULL,'tenant_test','opened',
                                 'warning','租户通知','降级保护测试','{}','SHARED-DEDUP','unread')
                        """,
                        (notification_id, tenant_id),
                    )
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                with self.assertRaisesRegex(RuntimeError, "cannot be represented"):
                    command.downgrade(config, "20260908_0085")

    def test_0087_backfills_audit_scope_rehashes_and_round_trips(self) -> None:
        with self._database_at_0081() as (config, database_path):
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                command.upgrade(config, "20260908_0086")
            with sqlite3.connect(database_path) as connection:
                self._insert_tenant(connection, PRIMARY_TENANT)
                self._insert_tenant(connection, "tenant-platform-internal")
                self._insert_counterparty(connection, PRIMARY_TENANT, "CP-AUDIT", "audit")
                self._insert_scoped_approval(connection, PRIMARY_TENANT, "CP-AUDIT", "CASE-AUDIT")
                root_hash = self._insert_legacy_audit_event(
                    connection,
                    event_id="AUDIT-BUSINESS-ROOT",
                    aggregate_type="approval_case",
                    aggregate_id="CASE-AUDIT",
                    event_type="approval_created",
                    payload={"stage": "准入筛查"},
                )
                self._insert_legacy_audit_event(
                    connection,
                    event_id="AUDIT-BUSINESS-TAIL",
                    aggregate_type="approval_case",
                    aggregate_id="CASE-AUDIT",
                    event_type="approval_updated",
                    payload={"tenant_id": PRIMARY_TENANT, "stage": "信用评级"},
                    previous_hash=root_hash,
                )
                self._insert_legacy_audit_event(
                    connection,
                    event_id="AUDIT-PLATFORM-ROOT",
                    aggregate_type="model_change",
                    aggregate_id="MODEL-CHANGE-AUDIT",
                    event_type="model_change_created",
                    payload={"template_key": "general"},
                )
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                command.upgrade(config, "20260908_0087")

            engine = create_engine(config.get_main_option("sqlalchemy.url"))
            schema = inspect(engine)
            columns = {item["name"]: item for item in schema.get_columns("audit_events")}
            self.assertFalse(columns["tenant_id"]["nullable"])
            self.assertFalse(columns["scope_type"]["nullable"])
            self.assertIn(
                ("tenant_id", "aggregate_type", "aggregate_id", "previous_hash"),
                {
                    tuple(item["column_names"])
                    for item in schema.get_unique_constraints("audit_events")
                },
            )
            self.assertIn(
                ("tenant_id",),
                {
                    tuple(item["constrained_columns"])
                    for item in schema.get_foreign_keys("audit_events")
                },
            )
            self.assertIn(
                "ix_audit_tenant_aggregate",
                {item["name"] for item in schema.get_indexes("audit_events")},
            )
            self.assertIn(
                "ck_audit_scope_tenant",
                {item["name"] for item in schema.get_check_constraints("audit_events")},
            )
            engine.dispose()

            with sqlite3.connect(database_path) as connection:
                connection.row_factory = sqlite3.Row
                rows = [dict(row) for row in connection.execute(
                    "SELECT * FROM audit_events ORDER BY id"
                ).fetchall()]
            by_id = {row["id"]: row for row in rows}
            self.assertEqual(by_id["AUDIT-BUSINESS-ROOT"]["tenant_id"], PRIMARY_TENANT)
            self.assertEqual(by_id["AUDIT-BUSINESS-ROOT"]["scope_type"], "tenant")
            self.assertEqual(
                by_id["AUDIT-BUSINESS-TAIL"]["previous_hash"],
                by_id["AUDIT-BUSINESS-ROOT"]["event_hash"],
            )
            self.assertEqual(
                by_id["AUDIT-PLATFORM-ROOT"]["tenant_id"],
                "tenant-platform-internal",
            )
            self.assertEqual(by_id["AUDIT-PLATFORM-ROOT"]["scope_type"], "platform")
            for row in rows:
                self.assertEqual(
                    row["event_hash"],
                    audit_event_hash(
                        event_id=row["id"],
                        tenant_id=row["tenant_id"],
                        scope_type=row["scope_type"],
                        aggregate_type=row["aggregate_type"],
                        aggregate_id=row["aggregate_id"],
                        event_type=row["event_type"],
                        actor=row["actor"],
                        payload=json.loads(row["payload"]),
                        previous_hash=row["previous_hash"],
                    ),
                )
            first_hashes = {row["id"]: row["event_hash"] for row in rows}

            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                command.downgrade(config, "20260908_0086")
                command.upgrade(config, "20260908_0087")
            with sqlite3.connect(database_path) as connection:
                round_trip_hashes = dict(connection.execute(
                    "SELECT id,event_hash FROM audit_events ORDER BY id"
                ).fetchall())
            self.assertEqual(round_trip_hashes, first_hashes)

    def test_0087_rejects_conflicting_audit_tenant_ownership(self) -> None:
        with self._database_at_0081() as (config, database_path):
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                command.upgrade(config, "20260908_0086")
            with sqlite3.connect(database_path) as connection:
                self._insert_tenant(connection, PRIMARY_TENANT)
                self._insert_tenant(connection, ALTERNATE_TENANT)
                self._insert_counterparty(connection, PRIMARY_TENANT, "CP-AUDIT-CONFLICT", "audit-conflict")
                self._insert_scoped_approval(
                    connection,
                    PRIMARY_TENANT,
                    "CP-AUDIT-CONFLICT",
                    "CASE-AUDIT-CONFLICT",
                )
                self._insert_legacy_audit_event(
                    connection,
                    event_id="AUDIT-CONFLICT",
                    aggregate_type="approval_case",
                    aggregate_id="CASE-AUDIT-CONFLICT",
                    event_type="approval_created",
                    payload={"tenant_id": ALTERNATE_TENANT},
                )
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                with self.assertRaisesRegex(RuntimeError, "conflicting tenant ownership"):
                    command.upgrade(config, "20260908_0087")

    def test_0087_rejects_broken_legacy_audit_hash(self) -> None:
        with self._database_at_0081() as (config, database_path):
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                command.upgrade(config, "20260908_0086")
            with sqlite3.connect(database_path) as connection:
                self._insert_tenant(connection, "tenant-platform-internal")
                connection.execute(
                    """
                    INSERT INTO audit_events(
                        id,aggregate_type,aggregate_id,event_type,actor,payload,
                        previous_hash,event_hash
                    ) VALUES('AUDIT-BROKEN','model_change','MODEL-BROKEN',
                             'model_change_created','migration-test','{}','',?)
                    """,
                    ("0" * 64,),
                )
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                with self.assertRaisesRegex(RuntimeError, "invalid content hash"):
                    command.upgrade(config, "20260908_0087")

    def test_0087_downgrade_rejects_cross_tenant_reused_chain_identity(self) -> None:
        with self._database_at_0081() as (config, database_path):
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                command.upgrade(config, "20260908_0087")
            with sqlite3.connect(database_path) as connection:
                self._insert_tenant(connection, "tenant-a")
                self._insert_tenant(connection, "tenant-b")
                for tenant_id, event_id in (
                    ("tenant-a", "AUDIT-TENANT-A"),
                    ("tenant-b", "AUDIT-TENANT-B"),
                ):
                    payload = {"tenant_id": tenant_id}
                    event_hash = audit_event_hash(
                        event_id=event_id,
                        tenant_id=tenant_id,
                        scope_type="tenant",
                        aggregate_type="sla_scan",
                        aggregate_id="SHARED-AUDIT-CHAIN",
                        event_type="sla_scan_completed",
                        actor="migration-test",
                        payload=payload,
                        previous_hash="",
                    )
                    connection.execute(
                        """
                        INSERT INTO audit_events(
                            id,tenant_id,scope_type,aggregate_type,aggregate_id,event_type,
                            actor,payload,previous_hash,event_hash
                        ) VALUES(?,?,'tenant','sla_scan','SHARED-AUDIT-CHAIN',
                                 'sla_scan_completed','migration-test',?,'',?)
                        """,
                        (event_id, tenant_id, json.dumps(payload), event_hash),
                    )
            with patch.dict(os.environ, {"DATABASE_URL": config.get_main_option("sqlalchemy.url")}):
                with self.assertRaisesRegex(RuntimeError, "cannot be represented"):
                    command.downgrade(config, "20260908_0086")


if __name__ == "__main__":
    unittest.main()
