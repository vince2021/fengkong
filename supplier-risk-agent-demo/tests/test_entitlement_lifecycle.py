from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

import backend.database as database
from backend.db_models import (
    ApiClientRecord,
    NotificationRecord,
    ProductPackageRecord,
    TenantEntitlementLifecycleRunRecord,
    TenantEntitlementRecord,
)
from backend.main import app
from backend.product_package_repository import content_hash, entitlement_lifecycle_run_key
from backend.repository import clear_persistent_data
from backend.security import Principal, ROLE_PERMISSIONS, get_current_principal
from tests.database_support import IsolatedTestDatabase


TENANT_ID = "tenant-demo-hengxin"
PLATFORM_TENANT_ID = "tenant-platform-internal"


def admin(subject: str = "lifecycle-admin") -> Principal:
    return Principal(
        subject=subject,
        name=subject,
        roles=("admin",),
        permissions=frozenset(ROLE_PERMISSIONS["admin"]),
        tenant_id=PLATFORM_TENANT_ID,
        client_id="platform-console",
    )


class EntitlementLifecycleApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.database = IsolatedTestDatabase()
        cls.database.start()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        app.dependency_overrides.clear()
        cls.database.stop()

    def setUp(self) -> None:
        app.dependency_overrides.clear()
        app.dependency_overrides[get_current_principal] = lambda: admin()
        with database.SessionLocal() as session:
            clear_persistent_data(session)
            session.execute(delete(TenantEntitlementLifecycleRunRecord))
            session.execute(delete(TenantEntitlementRecord))
            session.execute(delete(ProductPackageRecord))
            session.commit()

    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    @staticmethod
    def _snapshot() -> dict:
        return {
            "code": "ENTERPRISE-CREDIT-PRO",
            "name": "企业信用决策专业版",
            "description": "用于授权调度专项回归的企业信用决策产品包。",
            "environment_scopes": ["sandbox", "production"],
            "assets": [],
            "quotas": {
                "qps_limit": 35,
                "concurrent_job_limit": 5,
                "daily_item_quota": 30000,
                "max_asset_bindings": 100,
            },
            "expiry_policy": "block",
        }

    def _seed(self, *, include_expired_active: bool, tampered: bool = False) -> tuple[str, str | None]:
        now = datetime.now(timezone.utc)
        package_id = str(uuid4())
        scheduled_id = str(uuid4())
        active_id = str(uuid4()) if include_expired_active else None
        snapshot = self._snapshot()
        snapshot_hash = content_hash(snapshot)
        with database.SessionLocal() as session:
            session.add(ProductPackageRecord(
                id=package_id,
                code=snapshot["code"], version=1, name=snapshot["name"], description=snapshot["description"],
                status="published", is_active=True, environment_scopes_json=snapshot["environment_scopes"],
                asset_catalog_json=[], quotas_json=snapshot["quotas"], expiry_policy="block",
                config_hash=snapshot_hash, change_reason="授权调度专项测试", created_by="maker",
                created_by_name="maker", published_at=now,
            ))
            if active_id:
                session.add(TenantEntitlementRecord(
                    id=active_id, tenant_id=TENANT_ID, product_package_id=package_id,
                    package_code=snapshot["code"], package_version=1, package_config_hash=snapshot_hash,
                    package_snapshot_json=snapshot, effective_quotas_json=snapshot["quotas"], initialized_assets_json=[],
                    activation_hash="a" * 64, status="active", starts_at=now - timedelta(days=30),
                    expires_at=now - timedelta(minutes=1), change_reason="旧授权已到期",
                    created_by="maker", created_by_name="maker", activated_at=now - timedelta(days=30),
                ))
            session.add(TenantEntitlementRecord(
                id=scheduled_id, tenant_id=TENANT_ID, product_package_id=package_id,
                package_code=snapshot["code"], package_version=1, package_config_hash=snapshot_hash,
                package_snapshot_json={**snapshot, "name": "被篡改的产品包"} if tampered else snapshot,
                effective_quotas_json=snapshot["quotas"], initialized_assets_json=[], activation_hash=None,
                status="scheduled", starts_at=now - timedelta(minutes=1), expires_at=now + timedelta(days=365),
                change_reason="续期授权等待自动生效", created_by="maker", created_by_name="maker",
                reviewed_by="reviewer", reviewed_by_name="reviewer", reviewed_at=now - timedelta(minutes=2),
            ))
            session.commit()
        return scheduled_id, active_id

    def test_scan_expires_old_entitlement_activates_renewal_and_is_idempotent(self) -> None:
        scheduled_id, active_id = self._seed(include_expired_active=True)
        run_key = f"tenant-entitlement:test:{uuid4()}"
        response = self.client.post("/api/v1/tenant-admin/entitlement-lifecycle/scan", json={"run_key": run_key})
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertFalse(payload["idempotent"])
        self.assertEqual(payload["run"]["status"], "completed")
        self.assertEqual(payload["run"]["activated_count"], 1)
        self.assertEqual(payload["run"]["expired_count"], 1)
        self.assertEqual(len(payload["run"]["evidence_hash"]), 64)

        repeated = self.client.post("/api/v1/tenant-admin/entitlement-lifecycle/scan", json={"run_key": run_key})
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertTrue(repeated.json()["idempotent"])
        self.assertEqual(repeated.json()["run"]["id"], payload["run"]["id"])

        status = self.client.get("/api/v1/tenant-admin/entitlement-lifecycle/status")
        runs = self.client.get("/api/v1/tenant-admin/entitlement-runs")
        self.assertEqual(status.status_code, 200, status.text)
        self.assertEqual(runs.status_code, 200, runs.text)
        self.assertEqual(runs.json()[0]["run_key"], run_key)

        with database.SessionLocal() as session:
            self.assertEqual(session.get(TenantEntitlementRecord, scheduled_id).status, "active")
            expired = session.get(TenantEntitlementRecord, active_id)
            self.assertEqual(expired.status, "expired")
            self.assertIsNotNone(expired.expired_at)
            clients = session.scalars(select(ApiClientRecord).where(ApiClientRecord.tenant_id == TENANT_ID)).all()
            self.assertTrue(all(client.qps_limit == 35 and client.daily_item_quota == 30000 for client in clients))

    def test_failed_activation_requires_acknowledgement_then_retry_resolves_alerts(self) -> None:
        scheduled_id, _ = self._seed(include_expired_active=False, tampered=True)
        failed = self.client.post(
            "/api/v1/tenant-admin/entitlement-lifecycle/scan",
            json={"run_key": f"tenant-entitlement:failed:{uuid4()}"},
        )
        self.assertEqual(failed.status_code, 200, failed.text)
        run = failed.json()["run"]
        self.assertEqual((run["status"], run["failed_count"], run["incident_status"]), ("failed", 1, "open"))

        premature = self.client.post(
            f"/api/v1/tenant-admin/entitlement-runs/{run['id']}/retry",
            json={"expected_row_version": run["row_version"], "reason": "尚未确认异常就尝试重试"},
        )
        self.assertEqual(premature.status_code, 409, premature.text)

        acknowledged = self.client.post(
            f"/api/v1/tenant-admin/entitlement-runs/{run['id']}/acknowledge",
            json={"expected_row_version": run["row_version"], "reason": "确认产品包快照完整性异常，准备修复后重试"},
        )
        self.assertEqual(acknowledged.status_code, 200, acknowledged.text)
        self.assertEqual(acknowledged.json()["incident_status"], "acknowledged")

        with database.SessionLocal() as session:
            entitlement = session.get(TenantEntitlementRecord, scheduled_id)
            entitlement.package_snapshot_json = self._snapshot()
            session.commit()

        retried = self.client.post(
            f"/api/v1/tenant-admin/entitlement-runs/{run['id']}/retry",
            json={
                "expected_row_version": acknowledged.json()["row_version"],
                "reason": "已恢复产品包快照并执行补偿激活",
                "run_key": f"tenant-entitlement:retry:{uuid4()}",
            },
        )
        self.assertEqual(retried.status_code, 200, retried.text)
        self.assertEqual(retried.json()["run"]["activated_count"], 1)
        self.assertEqual(retried.json()["run"]["retry_of_run_id"], run["id"])

        with database.SessionLocal() as session:
            original = session.get(TenantEntitlementLifecycleRunRecord, run["id"])
            self.assertEqual(original.incident_status, "resolved")
            self.assertEqual(original.resolved_by_run_id, retried.json()["run"]["id"])
            notifications = session.scalars(select(NotificationRecord).where(
                NotificationRecord.dedup_key.like(f"tenant-entitlement-lifecycle:{run['id']}:%")
            )).all()
            self.assertEqual({item.tenant_id for item in notifications}, {PLATFORM_TENANT_ID, TENANT_ID})
            self.assertTrue(all(item.status == "resolved" for item in notifications))

    def test_scheduler_key_uses_stable_utc_window(self) -> None:
        base = datetime(2026, 9, 16, 8, 12, 30, tzinfo=timezone.utc)
        self.assertEqual(entitlement_lifecycle_run_key(base), entitlement_lifecycle_run_key(base + timedelta(minutes=2)))
        self.assertNotEqual(entitlement_lifecycle_run_key(base), entitlement_lifecycle_run_key(base + timedelta(minutes=3)))
        with self.assertRaises(ValueError):
            entitlement_lifecycle_run_key(base, 0)


if __name__ == "__main__":
    unittest.main()
