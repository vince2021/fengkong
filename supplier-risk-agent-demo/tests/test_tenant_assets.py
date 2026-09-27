from __future__ import annotations

import unittest
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

import backend.database as database
from backend.db_models import AuditEventRecord, RuleDefinition, TenantAssetBindingRecord, TenantAssetOverrideRecord
from backend.main import app
from backend.repository import clear_persistent_data
from backend.security import Principal, ROLE_PERMISSIONS, get_current_principal
from tests.database_support import IsolatedTestDatabase


PRIMARY_TENANT = "tenant-demo-hengxin"
ALTERNATE_TENANT = "tenant-demo-alt"
ASSET_CODE = "TENANT-ASSET-TEST-RULE"


def _principal(tenant_id: str, subject: str, role: str) -> Principal:
    return Principal(
        subject=subject,
        name=subject,
        roles=(role,),
        permissions=frozenset(ROLE_PERMISSIONS[role]),
        tenant_id=tenant_id,
        client_id=f"{tenant_id}-asset-tests",
    )


class TenantAssetApiTest(unittest.TestCase):
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
            session.execute(delete(TenantAssetOverrideRecord))
            session.execute(delete(TenantAssetBindingRecord))
            session.execute(delete(RuleDefinition).where(RuleDefinition.code == ASSET_CODE))
            session.add_all([
                self._rule(version=1, active=False, priority=300),
                self._rule(version=2, active=True, priority=200),
            ])
            session.commit()

    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def _as(self, principal: Principal) -> None:
        app.dependency_overrides[get_current_principal] = lambda: principal

    @staticmethod
    def _rule(version: int, active: bool, priority: int) -> RuleDefinition:
        return RuleDefinition(
            id=str(uuid4()),
            code=ASSET_CODE,
            name="租户资产测试规则",
            rule_type="strong_rule",
            category="governance_test",
            enabled=True,
            conditions_json=[{"field": "financial.overdue_rate", "operator": ">", "value": 0.2}],
            condition_relation="all",
            actions_json={"access_strategy": "REVIEW"},
            priority=priority,
            version=version,
            status="published",
            is_active=active,
            created_by="platform-seed",
        )

    def _create_binding(self, *, mode: str = "pinned", pinned_version: str | None = "1") -> dict:
        response = self.client.post(
            "/api/v1/tenant-assets/bindings",
            json={
                "asset_type": "rule",
                "asset_code": ASSET_CODE.lower(),
                "binding_mode": mode,
                "pinned_version": pinned_version,
                "allow_tenant_override": True,
                "status": "active",
                "reason": "试点租户固定规则基线",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_catalog_binding_and_resolution_are_isolated_by_tenant(self) -> None:
        maker = _principal(PRIMARY_TENANT, "asset-maker", "model_admin")
        alternate = _principal(ALTERNATE_TENANT, "alternate-risk", "risk_manager")
        self._as(maker)

        implicit = self.client.get(f"/api/v1/tenant-assets/rule/{ASSET_CODE}/resolve")
        self.assertEqual(implicit.status_code, 200, implicit.text)
        self.assertEqual((implicit.json()["source_scope"], implicit.json()["version"]), ("implicit_platform_default", "2"))

        binding = self._create_binding()
        pinned = self.client.get(f"/api/v1/tenant-assets/rule/{ASSET_CODE}/resolve").json()
        self.assertEqual((pinned["source_scope"], pinned["version"]), ("platform_pinned", "1"))
        self.assertEqual(binding["resolved_config_hash"], pinned["config_hash"])

        catalog = self.client.get("/api/v1/tenant-assets?asset_type=rule")
        self.assertEqual(catalog.status_code, 200, catalog.text)
        row = next(item for item in catalog.json()["items"] if item["asset_code"] == ASSET_CODE)
        self.assertEqual(row["available_versions"], ["2", "1"])
        self.assertEqual(row["binding"]["id"], binding["id"])

        self._as(alternate)
        alternate_resolution = self.client.get(f"/api/v1/tenant-assets/rule/{ASSET_CODE}/resolve")
        self.assertEqual(alternate_resolution.status_code, 200, alternate_resolution.text)
        self.assertEqual((alternate_resolution.json()["source_scope"], alternate_resolution.json()["version"]), ("implicit_platform_default", "2"))
        hidden = self.client.patch(
            f"/api/v1/tenant-assets/bindings/{binding['id']}",
            json={
                "status": "suspended",
                "expected_row_version": binding["row_version"],
                "reason": "尝试跨租户更新目录",
            },
        )
        self.assertEqual(hidden.status_code, 403)  # reviewer has no manage permission

        alternate_maker = _principal(ALTERNATE_TENANT, "alternate-maker", "model_admin")
        self._as(alternate_maker)
        hidden = self.client.patch(
            f"/api/v1/tenant-assets/bindings/{binding['id']}",
            json={
                "status": "suspended",
                "expected_row_version": binding["row_version"],
                "reason": "尝试跨租户更新目录",
            },
        )
        self.assertEqual(hidden.status_code, 404)

    def test_override_requires_maker_checker_and_becomes_effective(self) -> None:
        maker = _principal(PRIMARY_TENANT, "asset-maker", "model_admin")
        reviewer = _principal(PRIMARY_TENANT, "asset-reviewer", "risk_manager")
        self._as(maker)
        binding = self._create_binding()
        base = self.client.get(f"/api/v1/tenant-assets/rule/{ASSET_CODE}/resolve").json()
        candidate = dict(base["config"])
        candidate["priority"] = 88
        created_response = self.client.post(
            "/api/v1/tenant-assets/overrides",
            json={
                "asset_type": "rule",
                "asset_code": ASSET_CODE,
                "base_version": "1",
                "config": candidate,
                "reason": "为本租户收紧人工复核顺序",
            },
        )
        self.assertEqual(created_response.status_code, 201, created_response.text)
        created = created_response.json()
        submitted_response = self.client.post(
            f"/api/v1/tenant-assets/overrides/{created['id']}/submit",
            json={"expected_row_version": created["row_version"], "reason": "提交租户覆盖版本独立复核"},
        )
        self.assertEqual(submitted_response.status_code, 200, submitted_response.text)
        submitted = submitted_response.json()

        self._as(_principal(PRIMARY_TENANT, "asset-maker", "risk_manager"))
        self_review = self.client.post(
            f"/api/v1/tenant-assets/overrides/{created['id']}/review",
            json={"expected_row_version": submitted["row_version"], "decision": "approve", "comment": "本人尝试复核应被四眼门禁阻断"},
        )
        self.assertEqual(self_review.status_code, 403, self_review.text)
        self.assertEqual(self_review.json()["detail"]["code"], "FOUR_EYE_REVIEW_REQUIRED")

        self._as(reviewer)
        approved_response = self.client.post(
            f"/api/v1/tenant-assets/overrides/{created['id']}/review",
            json={"expected_row_version": submitted["row_version"], "decision": "approve", "comment": "已核对基线、规则条件和租户适用范围"},
        )
        self.assertEqual(approved_response.status_code, 200, approved_response.text)
        approved = approved_response.json()
        self.assertTrue(approved["is_active"])
        self.assertEqual(approved["status"], "published")

        resolved = self.client.get(f"/api/v1/tenant-assets/rule/{ASSET_CODE}/resolve").json()
        self.assertEqual(resolved["source_scope"], "tenant_override")
        self.assertEqual(resolved["version"], "tenant-v1")
        self.assertEqual(resolved["config"]["priority"], 88)
        self.assertEqual(resolved["override_id"], created["id"])

        self._as(maker)
        disabled = self.client.patch(
            f"/api/v1/tenant-assets/bindings/{binding['id']}",
            json={
                "allow_tenant_override": False,
                "expected_row_version": binding["row_version"] + 1,
                "reason": "暂时回到平台固定版本运行",
            },
        )
        self.assertEqual(disabled.status_code, 200, disabled.text)
        reverted = self.client.get(f"/api/v1/tenant-assets/rule/{ASSET_CODE}/resolve").json()
        self.assertEqual((reverted["source_scope"], reverted["version"]), ("platform_pinned", "1"))

        with database.SessionLocal() as session:
            events = session.scalars(
                select(AuditEventRecord).where(
                    AuditEventRecord.tenant_id == PRIMARY_TENANT,
                    AuditEventRecord.aggregate_type.in_(("tenant_asset_binding", "tenant_asset_override")),
                )
            ).all()
            self.assertGreaterEqual(len(events), 5)
            self.assertTrue(all(event.scope_type == "tenant" for event in events))

    def test_invalid_binding_permission_and_integrity_guards(self) -> None:
        self._as(_principal(PRIMARY_TENANT, "readonly-manager", "relationship_manager"))
        forbidden = self.client.get("/api/v1/tenant-assets")
        self.assertEqual(forbidden.status_code, 403)

        self._as(_principal(PRIMARY_TENANT, "asset-maker", "model_admin"))
        invalid = self.client.post(
            "/api/v1/tenant-assets/bindings",
            json={
                "asset_type": "rule",
                "asset_code": ASSET_CODE,
                "binding_mode": "pinned",
                "allow_tenant_override": False,
                "status": "active",
                "reason": "缺少固定版本的无效目录",
            },
        )
        self.assertEqual(invalid.status_code, 422)
        missing = self.client.post(
            "/api/v1/tenant-assets/bindings",
            json={
                "asset_type": "rule",
                "asset_code": ASSET_CODE,
                "binding_mode": "pinned",
                "pinned_version": "99",
                "allow_tenant_override": False,
                "status": "active",
                "reason": "固定到不存在的平台版本",
            },
        )
        self.assertEqual(missing.status_code, 404, missing.text)

        binding = self._create_binding()
        suspended = self.client.patch(
            f"/api/v1/tenant-assets/bindings/{binding['id']}",
            json={
                "status": "suspended",
                "expected_row_version": binding["row_version"],
                "reason": "租户暂时停止使用该资产",
            },
        )
        self.assertEqual(suspended.status_code, 200, suspended.text)
        blocked = self.client.get(f"/api/v1/tenant-assets/rule/{ASSET_CODE}/resolve")
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.json()["detail"]["code"], "ASSET_BINDING_SUSPENDED")


if __name__ == "__main__":
    unittest.main()
