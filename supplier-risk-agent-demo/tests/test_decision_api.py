from __future__ import annotations

import unittest
from copy import deepcopy

from fastapi.testclient import TestClient
from sqlalchemy import func, select

import backend.database as database
from backend.db_models import ApiClientRecord, DecisionExecutionRecord, TenantMembershipRecord, TenantRecord
from backend.main import app
from backend.repository import clear_persistent_data
from scripts.seed_indicators import seed_from_pool_json
from scripts.seed_rule_center import seed_all
from tests.database_support import IsolatedTestDatabase


class DecisionApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.test_database = IsolatedTestDatabase()
        cls.test_database.start()
        with database.SessionLocal() as session:
            seed_from_pool_json(session)
            seed_all(session=session)
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.test_database.stop()

    def setUp(self) -> None:
        with database.SessionLocal() as session:
            clear_persistent_data(session)
        self.headers = {"Authorization": "Bearer dev-integration"}
        self.payload = {
            "request_id": "ERP-DECISION-20260903-001",
            "counterparty_id": "cp_supplier_low_001",
            "input": None,
            "assets": {
                "model_key": "general",
                "model_version": "MCR-20260711-001",
                "pipeline_code": "PIPELINE-GENERAL",
                "pipeline_version": 1,
                "rule_set_versions": {
                    "STRONG-RULES-GENERAL": 1,
                    "RISK-SCREENING-DEFAULT": 1,
                },
                "rule_versions": {},
            },
            "metadata": {"source_system": "ERP", "scenario": "supplier_admission"},
        }

    def restore_integration_access(self) -> None:
        with database.SessionLocal() as session:
            tenant = session.get(TenantRecord, "tenant-demo-hengxin")
            tenant.status = "active"
            membership = session.scalars(
                select(TenantMembershipRecord).where(
                    TenantMembershipRecord.tenant_id == tenant.id,
                    TenantMembershipRecord.subject == "integration-demo",
                )
            ).one()
            membership.status = "active"
            membership.roles_json = ["integration_admin"]
            client = session.scalars(
                select(ApiClientRecord).where(
                    ApiClientRecord.tenant_id == tenant.id,
                    ApiClientRecord.client_id == "erp-integration-sandbox",
                )
            ).one()
            client.status = "active"
            session.commit()

    def test_executes_and_persists_version_pinned_evidence(self) -> None:
        response = self.client.post("/api/v1/decisions", json=self.payload, headers=self.headers)

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["tenant_id"], "tenant-demo-hengxin")
        self.assertEqual(body["client_id"], "erp-integration-sandbox")
        self.assertEqual(body["request_id"], self.payload["request_id"])
        self.assertFalse(body["idempotent"])
        self.assertTrue(body["decision"]["ok"])
        self.assertEqual(body["assets"]["model"]["version"], "MCR-20260711-001")
        self.assertEqual(body["assets"]["pipeline"]["version"], 1)
        self.assertEqual(
            {item["code"] for item in body["assets"]["rule_sets"]},
            {"STRONG-RULES-GENERAL", "RISK-SCREENING-DEFAULT"},
        )
        self.assertGreater(len(body["assets"]["rules"]), 1)
        self.assertEqual(body["trace"]["pipeline"]["pipeline_code"], "PIPELINE-GENERAL")
        self.assertEqual(len(body["evidence"]["evidence_hash"]), 64)
        self.assertEqual(len(set(body["evidence"].values())), 6)

        with database.SessionLocal() as session:
            record = session.scalars(select(DecisionExecutionRecord)).one()
            self.assertEqual(record.tenant_id, "tenant-demo-hengxin")
            self.assertEqual(record.client_id, "erp-integration-sandbox")
            self.assertEqual(record.request_id, self.payload["request_id"])
            self.assertEqual(record.asset_snapshot_json["pipeline"]["definition"]["version"], 1)
            self.assertTrue(record.asset_snapshot_json["rules"][0]["definition"]["conditions_json"])

    def test_replays_identically_without_creating_a_second_execution(self) -> None:
        first = self.client.post("/api/v1/decisions", json=self.payload, headers=self.headers)
        second = self.client.post("/api/v1/decisions", json=self.payload, headers=self.headers)

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertFalse(first.json()["idempotent"])
        self.assertTrue(second.json()["idempotent"])
        self.assertEqual(first.json()["trace_id"], second.json()["trace_id"])
        self.assertEqual(first.json()["evidence"], second.json()["evidence"])
        with database.SessionLocal() as session:
            self.assertEqual(session.scalar(select(func.count(DecisionExecutionRecord.id))), 1)

    def test_rejects_changed_payload_for_same_request_id(self) -> None:
        self.assertEqual(self.client.post("/api/v1/decisions", json=self.payload, headers=self.headers).status_code, 200)
        changed = deepcopy(self.payload)
        changed["metadata"]["scenario"] = "credit_limit"

        response = self.client.post("/api/v1/decisions", json=changed, headers=self.headers)

        self.assertEqual(response.status_code, 409, response.text)
        error = response.json()["error"]
        self.assertEqual(error["code"], "IDEMPOTENCY_CONFLICT")
        self.assertEqual(len(error["trace_id"]), 36)
        self.assertNotEqual(error["details"]["original_request_hash"], error["details"]["incoming_request_hash"])

    def test_same_request_id_is_isolated_between_tenants(self) -> None:
        primary = self.client.post("/api/v1/decisions", json=self.payload, headers=self.headers)
        self.assertEqual(primary.status_code, 200, primary.text)

        alternate_headers = {"Authorization": "Bearer dev-integration-alt"}
        hidden = self.client.get(
            f"/api/v1/decisions/{self.payload['request_id']}",
            headers=alternate_headers,
        )
        self.assertEqual(hidden.status_code, 404, hidden.text)

        alternate = self.client.post(
            "/api/v1/decisions",
            json=self.payload,
            headers=alternate_headers,
        )
        self.assertEqual(alternate.status_code, 200, alternate.text)
        self.assertEqual(alternate.json()["tenant_id"], "tenant-demo-alt")
        self.assertNotEqual(primary.json()["trace_id"], alternate.json()["trace_id"])

        replay = self.client.get(
            f"/api/v1/decisions/{self.payload['request_id']}",
            headers=alternate_headers,
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json()["trace_id"], alternate.json()["trace_id"])
        with database.SessionLocal() as session:
            rows = session.scalars(
                select(DecisionExecutionRecord).order_by(DecisionExecutionRecord.tenant_id)
            ).all()
            self.assertEqual(
                [(row.tenant_id, row.request_id) for row in rows],
                [
                    ("tenant-demo-alt", self.payload["request_id"]),
                    ("tenant-demo-hengxin", self.payload["request_id"]),
                ],
            )

    def test_authentication_rejects_suspended_tenant_member_role_and_client(self) -> None:
        self.addCleanup(self.restore_integration_access)
        with database.SessionLocal() as session:
            tenant = session.get(TenantRecord, "tenant-demo-hengxin")
            tenant.status = "suspended"
            session.commit()
        denied = self.client.post("/api/v1/decisions", json=self.payload, headers=self.headers)
        self.assertEqual(denied.status_code, 403, denied.text)

        with database.SessionLocal() as session:
            tenant = session.get(TenantRecord, "tenant-demo-hengxin")
            tenant.status = "active"
            membership = session.scalars(
                select(TenantMembershipRecord).where(
                    TenantMembershipRecord.tenant_id == tenant.id,
                    TenantMembershipRecord.subject == "integration-demo",
                )
            ).one()
            membership.roles_json = []
            session.commit()
        denied = self.client.post("/api/v1/decisions", json=self.payload, headers=self.headers)
        self.assertEqual(denied.status_code, 403, denied.text)

        with database.SessionLocal() as session:
            membership = session.scalars(
                select(TenantMembershipRecord).where(
                    TenantMembershipRecord.tenant_id == "tenant-demo-hengxin",
                    TenantMembershipRecord.subject == "integration-demo",
                )
            ).one()
            membership.roles_json = ["integration_admin"]
            client = session.scalars(
                select(ApiClientRecord).where(
                    ApiClientRecord.tenant_id == "tenant-demo-hengxin",
                    ApiClientRecord.client_id == "erp-integration-sandbox",
                )
            ).one()
            client.status = "disabled"
            session.commit()
        denied = self.client.post("/api/v1/decisions", json=self.payload, headers=self.headers)
        self.assertEqual(denied.status_code, 403, denied.text)

        with database.SessionLocal() as session:
            client = session.scalars(
                select(ApiClientRecord).where(
                    ApiClientRecord.tenant_id == "tenant-demo-hengxin",
                    ApiClientRecord.client_id == "erp-integration-sandbox",
                )
            ).one()
            client.status = "active"
            session.commit()

    def test_accepts_normalized_inline_input(self) -> None:
        sample = self.client.get("/api/v1/decisions/sandbox", headers=self.headers).json()["samples"][0]["input"]
        payload = deepcopy(self.payload)
        payload["request_id"] = "ERP-DECISION-INLINE-001"
        payload["counterparty_id"] = None
        payload["input"] = sample

        response = self.client.post("/api/v1/decisions", json=payload, headers=self.headers)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["trace"]["input"]["source"], "inline_input")

    def test_returns_standard_errors_for_invalid_requests_and_assets(self) -> None:
        invalid = deepcopy(self.payload)
        invalid["input"] = {"id": "external-1"}
        response = self.client.post("/api/v1/decisions", json=invalid, headers=self.headers)
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["error"]["code"], "DECISION_REQUEST_INVALID")

        missing_asset = deepcopy(self.payload)
        missing_asset["request_id"] = "ERP-DECISION-MISSING-001"
        missing_asset["assets"]["pipeline_version"] = 999
        response = self.client.post("/api/v1/decisions", json=missing_asset, headers=self.headers)
        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(response.json()["error"]["code"], "ASSET_VERSION_NOT_FOUND")
        self.assertEqual(response.json()["error"]["details"]["asset_type"], "pipeline")

    def test_contract_query_and_read_permissions(self) -> None:
        contract = self.client.get("/api/v1/decisions/contract", headers=self.headers)
        self.assertEqual(contract.status_code, 200, contract.text)
        self.assertEqual(contract.json()["tenant_id"], "tenant-demo-hengxin")
        self.assertIn("IDEMPOTENCY_CONFLICT", contract.json()["error_codes"])
        self.assertIn("ASSET_VERSION_NOT_ALLOWED", contract.json()["error_codes"])
        self.assertTrue(any(item["code"] == "PIPELINE-GENERAL" for item in contract.json()["pipelines"]))
        general = next(item for item in contract.json()["models"] if item["key"] == "general")
        self.assertEqual(general["versions"], [next(item for item in general["versions"] if item["version"] == general["active_version"])])
        self.assertEqual(len(general["resolution_hash"]), 64)
        self.assertEqual(general["source_scope"], "implicit_platform_default")

        created = self.client.post("/api/v1/decisions", json=self.payload, headers=self.headers)
        read = self.client.get(f"/api/v1/decisions/{self.payload['request_id']}", headers={"Authorization": "Bearer dev-auditor"})
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(read.status_code, 200, read.text)
        self.assertFalse(read.json()["idempotent"])

        forbidden = self.client.post("/api/v1/decisions", json=self.payload, headers={"Authorization": "Bearer dev-auditor"})
        self.assertEqual(forbidden.status_code, 403, forbidden.text)

        missing = self.client.get("/api/v1/decisions/NOT-FOUND", headers=self.headers)
        self.assertEqual(missing.status_code, 404, missing.text)
        self.assertEqual(missing.json()["error"]["code"], "DECISION_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
