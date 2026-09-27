from __future__ import annotations

import unittest
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

import backend.database as database
from backend.db_models import (
    ApiClientRecord,
    ProductPackageRecord,
    RuleDefinition,
    TenantAssetBindingRecord,
    TenantEntitlementRecord,
)
from backend.main import app
from backend.repository import clear_persistent_data
from backend.security import Principal, ROLE_PERMISSIONS, get_current_principal
from tests.database_support import IsolatedTestDatabase


RULE_CODE = "PACKAGE-TEST-RULE"
PRIMARY_TENANT = "tenant-demo-hengxin"
ALTERNATE_TENANT = "tenant-demo-alt"


def principal(subject: str, role: str = "admin", tenant_id: str = "tenant-platform-internal") -> Principal:
    return Principal(
        subject=subject, name=subject, roles=(role,), permissions=frozenset(ROLE_PERMISSIONS[role]),
        tenant_id=tenant_id, client_id="platform-console",
    )


class ProductPackageApiTest(unittest.TestCase):
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
            session.execute(delete(TenantEntitlementRecord))
            session.execute(delete(ProductPackageRecord))
            session.execute(delete(TenantAssetBindingRecord))
            session.execute(delete(RuleDefinition).where(RuleDefinition.code == RULE_CODE))
            session.add(RuleDefinition(
                id=str(uuid4()), code=RULE_CODE, name="企业授信准入规则", rule_type="strong_rule",
                category="credit_admission", enabled=True,
                conditions_json=[{"field": "financial.overdue_rate", "operator": ">", "value": 0.2}],
                condition_relation="all", actions_json={"access_strategy": "REVIEW"}, priority=100,
                version=1, status="published", is_active=True, created_by="test-seed",
            ))
            session.commit()
        self._as(principal("package-maker"))

    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def _as(self, value: Principal) -> None:
        app.dependency_overrides[get_current_principal] = lambda: value

    def _published_package(self, environment_scopes: list[str] | None = None) -> dict:
        created = self.client.post("/api/v1/tenant-admin/product-packages", json={
            "code": "ENTERPRISE-CREDIT-PRO", "name": "企业信用决策专业版",
            "description": "覆盖企业评级、授信准入和决策规则的生产产品包。",
            "environment_scopes": environment_scopes or ["sandbox", "production"],
            "assets": [{"asset_type": "rule", "asset_code": RULE_CODE, "binding_mode": "pinned", "pinned_version": "1", "allow_tenant_override": True}],
            "quotas": {"qps_limit": 40, "concurrent_job_limit": 6, "daily_item_quota": 50000, "max_asset_bindings": 100},
            "expiry_policy": "block", "reason": "建立企业授信标准商业产品包",
        })
        self.assertEqual(created.status_code, 201, created.text)
        submitted = self.client.post(
            f"/api/v1/tenant-admin/product-packages/{created.json()['id']}/submit",
            json={"expected_row_version": created.json()["row_version"], "reason": "提交产品委员会独立复核"},
        )
        self.assertEqual(submitted.status_code, 200, submitted.text)
        same_actor = self.client.post(
            f"/api/v1/tenant-admin/product-packages/{created.json()['id']}/review",
            json={"expected_row_version": submitted.json()["row_version"], "decision": "approve", "comment": "产品范围与商业配额审核通过"},
        )
        self.assertEqual(same_actor.status_code, 409)
        self.assertEqual(same_actor.json()["detail"]["code"], "FOUR_EYES_REQUIRED")
        self._as(principal("package-reviewer"))
        approved = self.client.post(
            f"/api/v1/tenant-admin/product-packages/{created.json()['id']}/review",
            json={"expected_row_version": submitted.json()["row_version"], "decision": "approve", "comment": "产品范围与商业配额审核通过"},
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertTrue(approved.json()["is_active"])
        return approved.json()

    def test_package_and_entitlement_four_eyes_activation(self) -> None:
        package = self._published_package()
        starts = datetime.now(timezone.utc) - timedelta(minutes=1)
        expires = starts + timedelta(days=365)
        request = {
            "tenant_id": PRIMARY_TENANT, "product_package_id": package["id"],
            "starts_at": starts.isoformat(), "expires_at": expires.isoformat(),
            "quota_overrides": {"qps_limit": 25, "concurrent_job_limit": 4, "daily_item_quota": 20000, "max_asset_bindings": 80},
            "reason": "为试点客户开通年度生产授权",
        }
        preview = self.client.post("/api/v1/tenant-admin/entitlements/preview", json=request)
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.json()["assets_to_create"][0]["asset_code"], RULE_CODE)
        self.assertEqual(preview.json()["effective_quotas"]["qps_limit"], 25)
        self.assertEqual(len(preview.json()["preview_hash"]), 64)

        self._as(principal("entitlement-maker"))
        created = self.client.post("/api/v1/tenant-admin/entitlements", json=request)
        self.assertEqual(created.status_code, 201, created.text)
        submitted = self.client.post(
            f"/api/v1/tenant-admin/entitlements/{created.json()['id']}/submit",
            json={"expected_row_version": created.json()["row_version"], "reason": "授权资料完整，提交独立复核"},
        )
        self.assertEqual(submitted.status_code, 200, submitted.text)
        same_actor = self.client.post(
            f"/api/v1/tenant-admin/entitlements/{created.json()['id']}/review",
            json={"expected_row_version": submitted.json()["row_version"], "decision": "approve", "comment": "合同期限与资产范围已核对"},
        )
        self.assertEqual(same_actor.status_code, 409)

        self._as(principal("entitlement-reviewer"))
        approved = self.client.post(
            f"/api/v1/tenant-admin/entitlements/{created.json()['id']}/review",
            json={"expected_row_version": submitted.json()["row_version"], "decision": "approve", "comment": "合同期限与资产范围已核对"},
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(approved.json()["status"], "active")
        self.assertEqual(len(approved.json()["activation_hash"]), 64)
        self.assertEqual(len(approved.json()["initialized_assets"]), 1)

        with database.SessionLocal() as session:
            binding = session.scalar(select(TenantAssetBindingRecord).where(
                TenantAssetBindingRecord.tenant_id == PRIMARY_TENANT,
                TenantAssetBindingRecord.asset_code == RULE_CODE,
            ))
            self.assertIsNotNone(binding)
            self.assertEqual((binding.status, binding.pinned_version), ("active", "1"))
            clients = session.scalars(select(ApiClientRecord).where(ApiClientRecord.tenant_id == PRIMARY_TENANT)).all()
            self.assertTrue(clients)
            self.assertTrue(all(client.qps_limit == 25 and client.daily_item_quota == 20000 for client in clients))

        self._as(principal("tenant-model-admin", "model_admin", PRIMARY_TENANT))
        resolved = self.client.get(f"/api/v1/tenant-assets/rule/{RULE_CODE}/resolve")
        self.assertEqual(resolved.status_code, 200, resolved.text)
        self.assertEqual(resolved.json()["source_scope"], "platform_pinned")

    def test_entitlement_gate_blocks_unlicensed_asset_and_suspended_tenant(self) -> None:
        package = self._published_package()
        now = datetime.now(timezone.utc)
        self._as(principal("entitlement-maker"))
        draft = self.client.post("/api/v1/tenant-admin/entitlements", json={
            "tenant_id": ALTERNATE_TENANT, "product_package_id": package["id"],
            "starts_at": now.isoformat(), "expires_at": (now + timedelta(days=30)).isoformat(),
            "reason": "创建待审核授权以验证未授权阻断",
        })
        self.assertEqual(draft.status_code, 201, draft.text)
        self._as(principal("alternate-model", "model_admin", ALTERNATE_TENANT))
        blocked = self.client.get(f"/api/v1/tenant-assets/rule/{RULE_CODE}/resolve")
        self.assertEqual(blocked.status_code, 403, blocked.text)
        self.assertEqual(blocked.json()["detail"]["code"], "TENANT_ENTITLEMENT_REQUIRED")

    def test_future_entitlement_requires_activation_time_and_environment_scope(self) -> None:
        package = self._published_package(["sandbox"])
        now = datetime.now(timezone.utc)
        self._as(principal("scheduled-maker"))
        created = self.client.post("/api/v1/tenant-admin/entitlements", json={
            "tenant_id": PRIMARY_TENANT, "product_package_id": package["id"],
            "starts_at": (now + timedelta(days=1)).isoformat(),
            "expires_at": (now + timedelta(days=31)).isoformat(),
            "reason": "配置下月开始的客户续期授权",
        }).json()
        submitted = self.client.post(
            f"/api/v1/tenant-admin/entitlements/{created['id']}/submit",
            json={"expected_row_version": created["row_version"], "reason": "未来授权提交独立复核"},
        ).json()
        self._as(principal("scheduled-reviewer"))
        scheduled_response = self.client.post(
            f"/api/v1/tenant-admin/entitlements/{created['id']}/review",
            json={"expected_row_version": submitted["row_version"], "decision": "approve", "comment": "续期合同与未来生效时间核对通过"},
        )
        self.assertEqual(scheduled_response.status_code, 200, scheduled_response.text)
        scheduled = scheduled_response.json()
        self.assertEqual((scheduled["status"], scheduled["effective_status"]), ("scheduled", "scheduled"))
        early = self.client.post(
            f"/api/v1/tenant-admin/entitlements/{created['id']}/status",
            json={"expected_row_version": scheduled["row_version"], "action": "activate", "reason": "尝试提前激活未来授权"},
        )
        self.assertEqual(early.status_code, 409, early.text)
        self.assertEqual(early.json()["detail"]["code"], "ENTITLEMENT_NOT_STARTED")

        with database.SessionLocal() as session:
            record = session.get(TenantEntitlementRecord, created["id"])
            record.starts_at = now - timedelta(minutes=1)
            session.commit()
        activated_response = self.client.post(
            f"/api/v1/tenant-admin/entitlements/{created['id']}/status",
            json={"expected_row_version": scheduled["row_version"] + 1, "action": "activate", "reason": "排期时间已到，激活续期授权"},
        )
        self.assertEqual(activated_response.status_code, 200, activated_response.text)
        self._as(principal("tenant-model-admin", "model_admin", PRIMARY_TENANT))
        with patch.dict(os.environ, {"APP_ENV": "production"}):
            blocked = self.client.get(f"/api/v1/tenant-assets/rule/{RULE_CODE}/resolve")
        self.assertEqual(blocked.status_code, 403, blocked.text)
        self.assertEqual(blocked.json()["detail"]["code"], "TENANT_ENVIRONMENT_NOT_ENTITLED")


if __name__ == "__main__":
    unittest.main()
