from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

import backend.database as database
from backend.database import Base
from backend.db_models import AuditEventRecord, RuleCenterReplayDataset, RuleCenterReplayDatasetSnapshot
from backend.main import app
from backend.security import Principal, ROLE_PERMISSIONS, get_current_principal
from tests.database_support import IsolatedTestDatabase


PRIMARY_TENANT = "tenant-demo-hengxin"
ALTERNATE_TENANT = "tenant-demo-alt"


def _principal(tenant_id: str, subject: str, role: str) -> Principal:
    return Principal(
        subject=subject,
        name=subject,
        roles=(role,),
        permissions=frozenset(ROLE_PERMISSIONS[role]),
        tenant_id=tenant_id,
        client_id=f"{tenant_id}-replay-tests",
    )


class TestRuleCenterReplayDatasets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = IsolatedTestDatabase()
        cls.db.start()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.db.stop()

    def setUp(self):
        Base.metadata.create_all(self.db.engine)
        self._clear()
        self.maker = {"Authorization": "Bearer dev-model-admin"}
        self.viewer = {"Authorization": "Bearer dev-auditor"}

    def tearDown(self):
        app.dependency_overrides.clear()
        self._clear()

    def _clear(self):
        with database.SessionLocal() as session:
            session.query(RuleCenterReplayDatasetSnapshot).delete()
            session.query(RuleCenterReplayDataset).delete()
            session.query(AuditEventRecord).delete()
            session.commit()

    def _dataset(self, code="HISTORY-2026"):
        response = self.client.post(
            "/api/v1/rule-center/governance/replay-datasets",
            json={
                "code": code,
                "name": "2026 历史审批样本",
                "description": "用于候选策略发布前回放的脱敏历史样本",
            },
            headers=self.maker,
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def _as(self, principal: Principal) -> None:
        app.dependency_overrides[get_current_principal] = lambda: principal

    @staticmethod
    def _records():
        return [
            {
                "source_id": "H-001", "company_name": "甲企业", "kind": "supplier",
                "decision": "approve", "observed_on": "2026-05-01",
                "financial": {"debt_ratio": 0.3},
            },
            {
                "source_id": "H-002", "company_name": "乙企业", "kind": "customer",
                "decision": "reject", "observed_on": "2026-06-15",
                "financial": {"debt_ratio": None},
            },
        ]

    def _snapshot_payload(self, records=None):
        return {
            "source_name": "risk-warehouse",
            "schema_version": "2026.1",
            "as_of_date": "2026-06-30",
            "evidence_reference": "warehouse://risk/replay/2026H1",
            "data_classification": "deidentified",
            "field_mapping": {
                "id": "source_id",
                "name": "company_name",
                "counterparty_type": "kind",
                "financial.debt_ratio": "financial.debt_ratio",
            },
            "label_field": "decision",
            "observed_at_field": "observed_on",
            "records": records or self._records(),
        }

    def test_import_builds_immutable_snapshot_and_coverage_report(self):
        dataset = self._dataset()
        imported = self.client.post(
            f"/api/v1/rule-center/governance/replay-datasets/{dataset['id']}/snapshots",
            json=self._snapshot_payload(),
            headers=self.maker,
        )
        self.assertEqual(imported.status_code, 201, imported.text)
        snapshot = imported.json()
        self.assertEqual(snapshot["version"], 1)
        self.assertEqual(snapshot["sample_count"], 2)
        self.assertEqual(snapshot["coverage"]["label_coverage_rate"], 1)
        self.assertEqual(snapshot["coverage"]["label_distribution"], {"approve": 1, "reject": 1})
        self.assertTrue(snapshot["coverage"]["deidentification"]["passed"])
        debt = next(item for item in snapshot["coverage"]["field_coverage"] if item["path"] == "financial.debt_ratio")
        self.assertEqual(debt["coverage_rate"], 0.5)
        self.assertEqual(len(snapshot["source_hash"]), 64)
        self.assertEqual(len(snapshot["content_hash"]), 64)

        listed = self.client.get(
            "/api/v1/rule-center/governance/replay-datasets", headers=self.viewer
        )
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()[0]["latest_snapshot"]["id"], snapshot["id"])

    def test_snapshot_versions_append_and_duplicate_source_is_rejected(self):
        dataset = self._dataset()
        url = f"/api/v1/rule-center/governance/replay-datasets/{dataset['id']}/snapshots"
        first_payload = self._snapshot_payload()
        first = self.client.post(url, json=first_payload, headers=self.maker)
        self.assertEqual(first.status_code, 201, first.text)
        duplicate = self.client.post(url, json=first_payload, headers=self.maker)
        self.assertEqual(duplicate.status_code, 422, duplicate.text)
        changed_records = self._records()
        changed_records[1]["decision"] = "manual_review"
        second = self.client.post(
            url, json=self._snapshot_payload(changed_records), headers=self.maker
        )
        self.assertEqual(second.status_code, 201, second.text)
        self.assertEqual(second.json()["version"], 2)
        versions = self.client.get(url, headers=self.viewer).json()
        self.assertEqual([item["version"] for item in versions], [2, 1])

    def test_sensitive_fields_and_future_observations_are_blocked(self):
        dataset = self._dataset()
        url = f"/api/v1/rule-center/governance/replay-datasets/{dataset['id']}/snapshots"
        sensitive_records = self._records()
        sensitive_records[0]["mobile"] = "13800000000"
        sensitive = self.client.post(
            url, json=self._snapshot_payload(sensitive_records), headers=self.maker
        )
        self.assertEqual(sensitive.status_code, 422, sensitive.text)
        self.assertIn("敏感字段", sensitive.text)

        future_records = self._records()
        future_records[0]["observed_on"] = "2026-07-01"
        future = self.client.post(
            url, json=self._snapshot_payload(future_records), headers=self.maker
        )
        self.assertEqual(future.status_code, 422, future.text)
        self.assertIn("晚于数据集时间截面", future.text)

    def test_duplicate_sample_ids_and_permissions_fail_closed(self):
        dataset = self._dataset()
        records = self._records()
        records[1]["source_id"] = records[0]["source_id"]
        duplicate = self.client.post(
            f"/api/v1/rule-center/governance/replay-datasets/{dataset['id']}/snapshots",
            json=self._snapshot_payload(records), headers=self.maker,
        )
        self.assertEqual(duplicate.status_code, 422, duplicate.text)
        self.assertIn("样本 ID 重复", duplicate.text)
        forbidden = self.client.post(
            "/api/v1/rule-center/governance/replay-datasets",
            json={"code": "NOPE", "name": "无权限", "description": "只读人员不能创建数据集"},
            headers=self.viewer,
        )
        self.assertEqual(forbidden.status_code, 403)

    def test_datasets_snapshots_and_source_deduplication_are_tenant_scoped(self):
        primary = self._dataset("SHARED-HISTORY")
        primary_snapshot = self.client.post(
            f"/api/v1/rule-center/governance/replay-datasets/{primary['id']}/snapshots",
            json=self._snapshot_payload(),
            headers=self.maker,
        )
        self.assertEqual(primary_snapshot.status_code, 201, primary_snapshot.text)

        self._as(_principal(ALTERNATE_TENANT, "alt-model", "model_admin"))
        alternate = self.client.post(
            "/api/v1/rule-center/governance/replay-datasets",
            json={
                "code": "SHARED-HISTORY",
                "name": "另一租户历史样本",
                "description": "验证相同编码和源数据可按租户独立固化",
            },
        )
        self.assertEqual(alternate.status_code, 201, alternate.text)
        alternate_snapshot = self.client.post(
            f"/api/v1/rule-center/governance/replay-datasets/{alternate.json()['id']}/snapshots",
            json=self._snapshot_payload(),
        )
        self.assertEqual(alternate_snapshot.status_code, 201, alternate_snapshot.text)
        self.assertNotEqual(
            primary_snapshot.json()["content_hash"],
            alternate_snapshot.json()["content_hash"],
        )
        self.assertEqual(
            [item["id"] for item in self.client.get(
                "/api/v1/rule-center/governance/replay-datasets"
            ).json()],
            [alternate.json()["id"]],
        )
        hidden = self.client.get(
            f"/api/v1/rule-center/governance/replay-datasets/{primary['id']}/snapshots"
        )
        self.assertEqual(hidden.status_code, 404, hidden.text)
        blocked_import = self.client.post(
            f"/api/v1/rule-center/governance/replay-datasets/{primary['id']}/snapshots",
            json=self._snapshot_payload(),
        )
        self.assertEqual(blocked_import.status_code, 404, blocked_import.text)


if __name__ == "__main__":
    unittest.main()
