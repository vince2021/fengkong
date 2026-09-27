from __future__ import annotations

import json
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

import backend.database as database
from backend.db_models import ApiClientRecord, AuditEventRecord, TenantMembershipRecord, TenantRecord
from backend.main import app
from backend.repository import clear_persistent_data
from tests.database_support import IsolatedTestDatabase


class TenantAdminApiTest(unittest.TestCase):
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
            session.execute(delete(ApiClientRecord).where(ApiClientRecord.tenant_id.like("tenant-test-%")))
            session.execute(delete(TenantMembershipRecord).where(TenantMembershipRecord.tenant_id.like("tenant-test-%")))
            session.execute(delete(TenantRecord).where(TenantRecord.id.like("tenant-test-%")))
            session.commit()
        self.headers = {"Authorization": "Bearer dev-admin"}

    def create_tenant(self, tenant_id: str) -> dict:
        response = self.client.post(
            "/api/v1/tenant-admin/tenants",
            headers=self.headers,
            json={
                "tenant_id": tenant_id,
                "name": "测试企业租户",
                "deployment_mode": "saas",
                "data_region": "cn-east",
                "reason": "客户试点租户开户",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_control_plane_is_platform_admin_only_and_paginated(self) -> None:
        forbidden = self.client.get(
            "/api/v1/tenant-admin/tenants",
            headers={"Authorization": "Bearer dev-risk"},
        )
        self.assertEqual(forbidden.status_code, 403, forbidden.text)

        page = self.client.get(
            "/api/v1/tenant-admin/tenants?status=active&limit=2&offset=0",
            headers=self.headers,
        )
        self.assertEqual(page.status_code, 200, page.text)
        self.assertGreaterEqual(page.json()["total"], 3)
        self.assertEqual(len(page.json()["items"]), 2)
        self.assertEqual((page.json()["limit"], page.json()["offset"]), (2, 0))

        missing = self.client.get(
            "/api/v1/tenant-admin/tenants/tenant-test-missing",
            headers=self.headers,
        )
        self.assertEqual(missing.status_code, 404, missing.text)
        self.assertEqual(missing.json()["detail"]["code"], "TENANT_NOT_FOUND")

    def test_tenant_lifecycle_requires_version_reason_and_writes_audit(self) -> None:
        tenant = self.create_tenant("tenant-test-lifecycle")
        self.assertEqual(tenant["status"], "active")
        self.assertEqual((tenant["membership_count"], tenant["api_client_count"]), (0, 0))

        duplicate = self.client.post(
            "/api/v1/tenant-admin/tenants",
            headers=self.headers,
            json={
                "tenant_id": tenant["id"],
                "name": "重复租户",
                "deployment_mode": "saas",
                "data_region": "cn-east",
                "reason": "验证重复租户保护",
            },
        )
        self.assertEqual(duplicate.status_code, 409, duplicate.text)

        stale = self.client.patch(
            f"/api/v1/tenant-admin/tenants/{tenant['id']}/status",
            headers=self.headers,
            json={"status": "suspended", "expected_row_version": 99, "reason": "模拟过期页面提交"},
        )
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(stale.json()["detail"]["code"], "ROW_VERSION_CONFLICT")

        changed = self.client.patch(
            f"/api/v1/tenant-admin/tenants/{tenant['id']}/status",
            headers=self.headers,
            json={"status": "suspended", "expected_row_version": tenant["row_version"], "reason": "客户试点暂时停止"},
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(changed.json()["status"], "suspended")
        self.assertEqual(changed.json()["row_version"], tenant["row_version"] + 1)

        audit = self.client.get(
            f"/api/v1/audit-events?aggregate_id={tenant['id']}",
            headers=self.headers,
        )
        self.assertEqual(audit.status_code, 200, audit.text)
        self.assertEqual(
            [item["event_type"] for item in audit.json()],
            ["tenant_created", "tenant_status_changed"],
        )
        self.assertEqual(audit.json()[-1]["payload"]["reason"], "客户试点暂时停止")
        self.assertEqual(audit.json()[-1]["payload"]["actor_subject"], "admin-demo")

        current = self.client.get(
            "/api/v1/tenant-admin/tenants/tenant-platform-internal",
            headers=self.headers,
        ).json()
        protected = self.client.patch(
            "/api/v1/tenant-admin/tenants/tenant-platform-internal/status",
            headers=self.headers,
            json={"status": "disabled", "expected_row_version": current["row_version"], "reason": "验证当前租户保护"},
        )
        self.assertEqual(protected.status_code, 422, protected.text)
        self.assertEqual(protected.json()["detail"]["code"], "CURRENT_TENANT_PROTECTED")

    def test_member_authorization_management_and_self_protection(self) -> None:
        tenant = self.create_tenant("tenant-test-members")
        created = self.client.post(
            f"/api/v1/tenant-admin/tenants/{tenant['id']}/members",
            headers=self.headers,
            json={
                "subject": "risk-user-001",
                "display_name": "试点风控经理",
                "roles": ["risk_manager"],
                "expires_at": None,
                "reason": "建立试点风控成员关系",
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        member = created.json()
        self.assertEqual(member["roles"], ["risk_manager"])

        invalid_admin = self.client.post(
            f"/api/v1/tenant-admin/tenants/{tenant['id']}/members",
            headers=self.headers,
            json={
                "subject": "outside-admin",
                "display_name": "错误管理员",
                "roles": ["admin"],
                "reason": "验证平台管理员范围限制",
            },
        )
        self.assertEqual(invalid_admin.status_code, 422, invalid_admin.text)
        self.assertEqual(invalid_admin.json()["detail"]["code"], "PLATFORM_ADMIN_SCOPE_INVALID")

        updated = self.client.patch(
            f"/api/v1/tenant-admin/tenants/{tenant['id']}/members/{member['subject']}",
            headers=self.headers,
            json={
                "roles": ["auditor"],
                "status": "suspended",
                "expected_row_version": member["row_version"],
                "reason": "试点人员职责发生调整",
            },
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual((updated.json()["roles"], updated.json()["status"]), (["auditor"], "suspended"))

        admin_member = next(
            item
            for item in self.client.get(
                "/api/v1/tenant-admin/tenants/tenant-platform-internal/members",
                headers=self.headers,
            ).json()
            if item["subject"] == "admin-demo"
        )
        protected = self.client.patch(
            "/api/v1/tenant-admin/tenants/tenant-platform-internal/members/admin-demo",
            headers=self.headers,
            json={
                "status": "revoked",
                "expected_row_version": admin_member["row_version"],
                "reason": "验证当前管理员自我保护",
            },
        )
        self.assertEqual(protected.status_code, 422, protected.text)
        self.assertEqual(protected.json()["detail"]["code"], "CURRENT_MEMBERSHIP_PROTECTED")

    def test_client_governance_normalizes_cidr_and_immediately_blocks_access(self) -> None:
        tenant = self.create_tenant("tenant-test-clients")
        created = self.client.post(
            f"/api/v1/tenant-admin/tenants/{tenant['id']}/clients",
            headers=self.headers,
            json={
                "client_id": "erp-production-01",
                "name": "ERP 生产接入",
                "key_id": "erp-key-2026-01",
                "key_fingerprint": "SHA256:11:22:33:44",
                "secret_reference": "kms://tenant-test/erp-key",
                "qps_limit": 25,
                "concurrent_job_limit": 4,
                "daily_item_quota": 20000,
                "allowed_cidrs": ["10.20.30.42/24", "10.20.30.0/24"],
                "reason": "建立客户 ERP 生产接入",
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        api_client = created.json()
        self.assertEqual(api_client["allowed_cidrs"], ["10.20.30.0/24"])
        self.assertNotIn("kms-secret-value", json.dumps(api_client))

        updated = self.client.patch(
            f"/api/v1/tenant-admin/tenants/{tenant['id']}/clients/{api_client['client_id']}",
            headers=self.headers,
            json={
                "qps_limit": 40,
                "key_id": "erp-key-2026-02",
                "key_fingerprint": "SHA256:55:66:77:88",
                "expected_row_version": api_client["row_version"],
                "reason": "客户扩容并完成密钥轮换",
            },
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["qps_limit"], 40)
        self.assertEqual(updated.json()["row_version"], api_client["row_version"] + 1)
        with database.SessionLocal() as session:
            events = session.scalars(
                select(AuditEventRecord)
                .where(
                    AuditEventRecord.aggregate_type == "api_client",
                    AuditEventRecord.aggregate_id == f"{tenant['id']}:{api_client['client_id']}",
                )
                .order_by(AuditEventRecord.created_at)
            ).all()
            self.assertEqual([event.event_type for event in events], ["api_client_created", "api_client_updated"])
            self.assertEqual(events[-1].payload["before"]["qps_limit"], 25)
            self.assertEqual(events[-1].payload["after"]["qps_limit"], 40)

        stale = self.client.patch(
            f"/api/v1/tenant-admin/tenants/{tenant['id']}/clients/{api_client['client_id']}",
            headers=self.headers,
            json={"status": "disabled", "expected_row_version": api_client["row_version"], "reason": "模拟并发停用请求"},
        )
        self.assertEqual(stale.status_code, 409, stale.text)

        alt_client = next(
            item
            for item in self.client.get(
                "/api/v1/tenant-admin/tenants/tenant-demo-alt/clients",
                headers=self.headers,
            ).json()
            if item["client_id"] == "erp-alt-sandbox"
        )
        disabled = self.client.patch(
            "/api/v1/tenant-admin/tenants/tenant-demo-alt/clients/erp-alt-sandbox",
            headers=self.headers,
            json={"status": "disabled", "expected_row_version": alt_client["row_version"], "reason": "验证停用即时阻断接入"},
        )
        self.assertEqual(disabled.status_code, 200, disabled.text)
        denied = self.client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer dev-integration-alt"},
        )
        self.assertEqual(denied.status_code, 403, denied.text)

        restored = self.client.patch(
            "/api/v1/tenant-admin/tenants/tenant-demo-alt/clients/erp-alt-sandbox",
            headers=self.headers,
            json={"status": "active", "expected_row_version": disabled.json()["row_version"], "reason": "完成阻断验证后恢复沙箱"},
        )
        self.assertEqual(restored.status_code, 200, restored.text)

        current_client = next(
            item
            for item in self.client.get(
                "/api/v1/tenant-admin/tenants/tenant-platform-internal/clients",
                headers=self.headers,
            ).json()
            if item["client_id"] == "platform-console"
        )
        protected = self.client.patch(
            "/api/v1/tenant-admin/tenants/tenant-platform-internal/clients/platform-console",
            headers=self.headers,
            json={"status": "disabled", "expected_row_version": current_client["row_version"], "reason": "验证当前客户端保护"},
        )
        self.assertEqual(protected.status_code, 422, protected.text)
        self.assertEqual(protected.json()["detail"]["code"], "CURRENT_CLIENT_PROTECTED")

        raw_secret = self.client.post(
            f"/api/v1/tenant-admin/tenants/{tenant['id']}/clients",
            headers=self.headers,
            json={
                "client_id": "raw-secret-client",
                "name": "错误明文客户端",
                "key_id": "raw-secret-key",
                "key_fingerprint": "SHA256:AA:BB:CC:DD",
                "secret": "must-not-be-accepted",
                "reason": "验证明文密钥字段被拒绝",
            },
        )
        self.assertEqual(raw_secret.status_code, 422, raw_secret.text)


if __name__ == "__main__":
    unittest.main()
