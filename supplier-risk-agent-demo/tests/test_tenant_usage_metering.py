from __future__ import annotations

import csv
import io
import unittest
from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import delete

import backend.database as database
from backend.db_models import (
    DecisionExecutionRecord,
    DecisionJobRecord,
    DocumentRecord,
    PortfolioRatingBatchRecord,
    ProductPackageRecord,
    RuleCenterReleasePackage,
    RuleCenterReplayRun,
    TenantAssetBindingRecord,
    TenantEntitlementRecord,
)
from backend.main import app
from backend.repository import clear_persistent_data
from tests.database_support import IsolatedTestDatabase


TENANT_ID = "tenant-demo-hengxin"
ALT_TENANT_ID = "tenant-demo-alt"
COUNTERPARTY_ID = "cp_supplier_low_001"


class TenantUsageMeteringApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.test_database = IsolatedTestDatabase()
        cls.test_database.start()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.test_database.stop()

    def setUp(self) -> None:
        with database.SessionLocal() as session:
            clear_persistent_data(session)
            session.execute(delete(RuleCenterReplayRun).where(RuleCenterReplayRun.id == "usage-replay"))
            session.execute(delete(RuleCenterReleasePackage).where(RuleCenterReleasePackage.id == "usage-release-package"))
            session.execute(delete(TenantEntitlementRecord).where(TenantEntitlementRecord.id.in_((f"entitlement-{TENANT_ID}", f"entitlement-{ALT_TENANT_ID}"))))
            session.execute(delete(ProductPackageRecord).where(ProductPackageRecord.id.in_((f"package-{TENANT_ID}", f"package-{ALT_TENANT_ID}"))))
            self._seed_usage(session, TENANT_ID, include_all=True)
            self._seed_usage(session, ALT_TENANT_ID, include_all=False)
            session.commit()
        self.headers = {"Authorization": "Bearer dev-admin"}
        utc_date = datetime.now(timezone.utc).date()
        self.today = utc_date.isoformat()
        self.month = utc_date.replace(day=1).isoformat()

    def _seed_usage(self, session, tenant_id: str, *, include_all: bool) -> None:
        now = datetime.now(timezone.utc)
        package_id = f"package-{tenant_id}"
        session.add(ProductPackageRecord(
            id=package_id, code=f"USAGE-{tenant_id}", version=1, name="计量测试包", description="用于验证租户使用量计量和对账快照。",
            status="published", is_active=False, environment_scopes_json=["sandbox"], asset_catalog_json=[],
            quotas_json={"qps_limit": 20, "concurrent_job_limit": 3, "daily_item_quota": 100, "max_asset_bindings": 10},
            expiry_policy="block", config_hash="a" * 64, change_reason="计量验收", created_by="test", created_by_name="test",
        ))
        session.add(TenantEntitlementRecord(
            id=f"entitlement-{tenant_id}", tenant_id=tenant_id, product_package_id=package_id, package_code=f"USAGE-{tenant_id}", package_version=1,
            package_config_hash="a" * 64, package_snapshot_json={}, effective_quotas_json={"qps_limit": 20, "concurrent_job_limit": 3, "daily_item_quota": 100, "max_asset_bindings": 10},
            initialized_assets_json=[], status="active", starts_at=now - timedelta(days=2), expires_at=now + timedelta(days=2),
            change_reason="计量验收", created_by="test", created_by_name="test",
        ))
        session.add(TenantAssetBindingRecord(
            id=f"binding-{tenant_id}", tenant_id=tenant_id, asset_type="rule", asset_code=f"RULE-{tenant_id}", binding_mode="inherit_active",
            pinned_version=None, allow_tenant_override=False, status="active", change_reason="计量验收", created_by="test", created_by_name="test",
            updated_by="test", updated_by_name="test",
        ))
        session.add_all([
            DecisionExecutionRecord(
                id=f"sync-{tenant_id}", tenant_id=tenant_id, client_id="client", request_id=f"SYNC-{tenant_id}", request_hash="1" * 64,
                trace_id=f"trace-sync-{tenant_id}", counterparty_id=COUNTERPARTY_ID, request_json={}, normalized_input_json={}, input_hash="2" * 64,
                model_key="general", model_version="v1", model_config_hash="3" * 64, pipeline_code="pipeline", pipeline_version=1, pipeline_hash="4" * 64,
                asset_snapshot_json={}, assets_hash="5" * 64, result_json={}, result_hash="6" * 64, trace_json={}, trace_hash="7" * 64,
                evidence_hash="8" * 64, elapsed_ms=3, created_by="test", created_by_name="test", created_at=now,
            ),
            DecisionExecutionRecord(
                id=f"job-execution-{tenant_id}", tenant_id=tenant_id, client_id="client", request_id=f"JOB-ITEM-{tenant_id}", request_hash="9" * 64,
                trace_id=f"trace-job-{tenant_id}", counterparty_id=COUNTERPARTY_ID, request_json={}, normalized_input_json={}, input_hash="a" * 64,
                model_key="general", model_version="v1", model_config_hash="b" * 64, pipeline_code="pipeline", pipeline_version=1, pipeline_hash="c" * 64,
                asset_snapshot_json={}, assets_hash="d" * 64, result_json={}, result_hash="e" * 64, trace_json={}, trace_hash="f" * 64,
                evidence_hash="0" * 64, elapsed_ms=3, created_by="test", created_by_name="test", created_at=now,
            ),
            DecisionJobRecord(
                id=f"job-{tenant_id}", job_key=f"JOB-{tenant_id}", request_hash="b" * 64, tenant_id=tenant_id, client_id="client", status="completed",
                total_count=7, succeeded_count=6, failed_count=1, request_json={"requests": [{"request_id": f"JOB-ITEM-{tenant_id}"}]},
                results_json=[], failures_json=[], callback_json={}, asset_snapshot_json={}, assets_hash="c" * 64, result_hash="d" * 64, evidence_hash="e" * 64,
                created_by="test", created_by_name="test", created_at=now,
            ),
            PortfolioRatingBatchRecord(
                id=f"batch-{tenant_id}", tenant_id=tenant_id, batch_key=f"BATCH-{tenant_id}", request_hash="1" * 64, template_key="general", model_version="v1",
                model_snapshot_id=None, scope_type="all", status="completed", candidate_count=9, success_count=8, skipped_count=1,
                summary_json={}, results_json=[], skipped_json=[], result_hash="2" * 64, asset_snapshot_json={}, assets_hash="3" * 64,
                created_by="test", created_by_name="test", created_at=now,
            ),
        ])
        if include_all:
            session.add(RuleCenterReleasePackage(
                id="usage-release-package", name="计量回放发布包", change_reason="计量验收", status="published", config_hash="4" * 64,
                dependency_snapshot_json={}, impact_json={}, created_by="test", created_by_name="test",
            ))
            session.add(RuleCenterReplayRun(
                id="usage-replay", tenant_id=tenant_id, package_id="usage-release-package", package_config_hash="5" * 64,
                dataset_snapshot_id=None, dataset_snapshot_hash=None, model_key="general", model_version="v1", pipeline_code="pipeline",
                sample_source="test", sample_count=11, status="completed", thresholds_json={}, metrics_json={}, details_json=[], gate_json={},
                asset_snapshot_json={}, assets_hash="6" * 64, evidence_hash="7" * 64, created_by="test", created_by_name="test", created_at=now,
            ))
            session.add(DocumentRecord(
                id="usage-document", tenant_id=tenant_id, counterparty_id=COUNTERPARTY_ID, case_id=None, document_type="财务报表",
                original_name="usage.pdf", object_key=f"{tenant_id}/usage.pdf", content_type="application/pdf", size_bytes=2048, sha256="8" * 64,
                uploaded_by="test", status="已上传", checklist_json=[], review_status="pending_review", row_version=1, created_at=now,
            ))

    def test_daily_ledger_excludes_async_execution_and_is_idempotent(self) -> None:
        first = self.client.post("/api/v1/tenant-admin/usage/refresh", json={"tenant_id": TENANT_ID, "usage_date": self.today}, headers=self.headers)
        self.assertEqual(first.status_code, 200, first.text)
        ledger = first.json()
        self.assertEqual(ledger["usage"]["sync_decision_requests"], 1)
        self.assertEqual(ledger["usage"]["async_job_items"], 7)
        self.assertEqual(ledger["usage"]["portfolio_candidates"], 9)
        self.assertEqual(ledger["usage"]["replay_samples"], 11)
        self.assertEqual(ledger["usage"]["document_storage_bytes"], 2048)
        self.assertEqual(ledger["usage"]["active_asset_bindings"], 1)
        self.assertEqual(ledger["usage"]["daily_item_utilization"], 0.07)
        second = self.client.post("/api/v1/tenant-admin/usage/refresh", json={"tenant_id": TENANT_ID, "usage_date": self.today}, headers=self.headers)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual((second.json()["id"], second.json()["evidence_hash"]), (ledger["id"], ledger["evidence_hash"]))

    def test_statement_freezes_daily_evidence_and_csv(self) -> None:
        refreshed = self.client.post("/api/v1/tenant-admin/usage/refresh", json={"tenant_id": TENANT_ID, "usage_date": self.today}, headers=self.headers)
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        created = self.client.post("/api/v1/tenant-admin/usage/statements", json={"tenant_id": TENANT_ID, "billing_month": self.month}, headers=self.headers)
        self.assertEqual(created.status_code, 201, created.text)
        statement = created.json()
        self.assertEqual(statement["statement"]["totals"]["async_job_items"], 7)
        self.assertEqual(statement["statement"]["statement_type"], "reconciliation_evidence_not_invoice")

        with database.SessionLocal() as session:
            row = session.get(DecisionJobRecord, f"job-{TENANT_ID}")
            row.total_count = 99
            session.commit()
        refreshed_again = self.client.post("/api/v1/tenant-admin/usage/refresh", json={"tenant_id": TENANT_ID, "usage_date": self.today}, headers=self.headers)
        self.assertEqual(refreshed_again.status_code, 200, refreshed_again.text)
        summary = self.client.get(f"/api/v1/tenant-admin/usage/summary?tenant_id={TENANT_ID}&billing_month={self.month}", headers=self.headers)
        self.assertEqual(summary.status_code, 200, summary.text)
        self.assertEqual(summary.json()["totals"]["async_job_items"], 99)
        self.assertEqual(statement["statement"]["totals"]["async_job_items"], 7)

        exported = self.client.get(f"/api/v1/tenant-admin/usage/statements/{statement['id']}/export.csv", headers=self.headers)
        self.assertEqual(exported.status_code, 200, exported.text)
        rows = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
        self.assertEqual(rows[0]["async_job_items"], "7")
        self.assertEqual(rows[0]["statement_hash"], statement["statement_hash"])

    def test_usage_endpoints_require_platform_tenant_admin_permission(self) -> None:
        response = self.client.get(f"/api/v1/tenant-admin/usage/summary?tenant_id={ALT_TENANT_ID}&billing_month={self.month}", headers={"Authorization": "Bearer dev-manager"})
        self.assertEqual(response.status_code, 403, response.text)


if __name__ == "__main__":
    unittest.main()
