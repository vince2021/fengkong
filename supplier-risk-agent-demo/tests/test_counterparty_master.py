from __future__ import annotations

import unittest
from copy import deepcopy

from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

import backend.database as database
from backend.db_models import AuditEventRecord, CounterpartyRecord
from backend.main import app
from backend.repository import clear_persistent_data
from scripts.seed_counterparties import seed_development_counterparties
from scripts.seed_indicators import seed_from_pool_json
from scripts.seed_rule_center import seed_all
from tests.database_support import IsolatedTestDatabase


class CounterpartyMasterApiTest(unittest.TestCase):
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
            session.execute(delete(AuditEventRecord).where(AuditEventRecord.aggregate_id.like("%:cp_test_%")))
            session.execute(delete(CounterpartyRecord).where(CounterpartyRecord.counterparty_id.like("cp_test_%")))
            session.commit()
        self.manager = {"Authorization": "Bearer dev-manager"}
        self.risk = {"Authorization": "Bearer dev-risk"}
        self.client_headers = {"Authorization": "Bearer dev-client"}
        self.integration_alt = {"Authorization": "Bearer dev-integration-alt"}

    @staticmethod
    def payload(counterparty_id: str = "cp_test_master_001", credit_code: str = "91440300TESTMASTER1") -> dict:
        return {
            "counterparty_id": counterparty_id,
            "credit_code": credit_code,
            "name": "测试企业主数据有限公司",
            "counterparty_type": "supplier",
            "industry": "manufacturing",
            "cooperation_status": "active",
            "is_key_counterparty": True,
            "requested_limit": 1800000,
            "current_limit": 600000,
            "current_payment_term_days": 45,
            "current_rating": "BBB",
            "current_segment": "关注客商",
            "external": {"registration_status": "存续"},
            "internal": {"orders_12m": 18},
            "financial": {"overdue_rate": 0.02},
            "extensions": {"data_quality": {"recommended_model": "general"}, "custom_label": "试点"},
            "reason": "建立客户试点客商主数据",
        }

    def create(self, **overrides) -> dict:
        payload = self.payload()
        payload.update(overrides)
        response = self.client.post("/api/v1/counterparties", headers=self.manager, json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_seed_is_idempotent_and_legacy_list_preserves_profile_shape(self) -> None:
        with database.SessionLocal() as session:
            before = session.scalar(select(func.count(CounterpartyRecord.id)))
            self.assertEqual(seed_development_counterparties(session), 0)
            self.assertEqual(seed_development_counterparties(session), 0)
            self.assertEqual(session.scalar(select(func.count(CounterpartyRecord.id))), before)
            self.assertEqual(before, 42)

        response = self.client.get("/api/v1/counterparties", headers=self.risk)
        self.assertEqual(response.status_code, 200, response.text)
        sample = next(item for item in response.json() if item["id"] == "cp_inalfa_guangzhou_001")
        self.assertIn("data_quality", sample)
        self.assertIn("corporate_profile", sample)
        self.assertEqual(sample["tenant_id"], "tenant-demo-hengxin")
        self.assertEqual(len(sample["profile_hash"]), 64)

    def test_create_requires_manager_permission_and_enforces_tenant_uniqueness(self) -> None:
        forbidden = self.client.post("/api/v1/counterparties", headers=self.risk, json=self.payload())
        self.assertEqual(forbidden.status_code, 403, forbidden.text)

        created = self.create()
        self.assertEqual(created["source_type"], "manual")
        self.assertEqual(created["custom_label"], "试点")
        self.assertEqual(created["row_version"], 1)

        duplicate_id = self.client.post(
            "/api/v1/counterparties", headers=self.manager,
            json=self.payload(credit_code="91440300TESTMASTER2"),
        )
        self.assertEqual(duplicate_id.status_code, 409, duplicate_id.text)
        duplicate_code = self.client.post(
            "/api/v1/counterparties", headers=self.manager,
            json=self.payload(counterparty_id="cp_test_master_002"),
        )
        self.assertEqual(duplicate_code.status_code, 409, duplicate_code.text)

    def test_search_pagination_update_archive_and_audit(self) -> None:
        created = self.create()
        page = self.client.get(
            "/api/v1/counterparties/page?q=测试企业主数据&counterparty_type=supplier&status=active&limit=5",
            headers=self.risk,
        )
        self.assertEqual(page.status_code, 200, page.text)
        self.assertEqual(page.json()["total"], 1)
        self.assertEqual(page.json()["items"][0]["id"], created["id"])

        stale = self.client.patch(
            f"/api/v1/counterparties/{created['id']}", headers=self.manager,
            json={"current_limit": 900000, "expected_row_version": 99, "reason": "验证并发版本冲突保护"},
        )
        self.assertEqual(stale.status_code, 409, stale.text)

        updated = self.client.patch(
            f"/api/v1/counterparties/{created['id']}", headers=self.manager,
            json={
                "current_limit": 900000, "clear_current_rating": True,
                "expected_row_version": created["row_version"], "reason": "客户最新授信台账完成同步",
            },
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["current_limit"], 900000)
        self.assertIsNone(updated.json()["current_rating"])
        self.assertEqual(updated.json()["row_version"], 2)

        history = self.client.get(
            f"/api/v1/counterparties/{created['id']}/history?limit=10", headers=self.manager,
        )
        self.assertEqual(history.status_code, 200, history.text)
        self.assertEqual([event["event_type"] for event in history.json()], [
            "counterparty_updated", "counterparty_created",
        ])
        self.assertIn("current_limit", history.json()[0]["changed_fields"])
        self.assertEqual(history.json()[0]["actor_name"], "客户经理")
        self.assertEqual(history.json()[0]["row_version"], 2)
        self.assertEqual(len(history.json()[0]["event_hash"]), 64)

        archived = self.client.post(
            f"/api/v1/counterparties/{created['id']}/archive", headers=self.manager,
            json={"expected_row_version": updated.json()["row_version"], "reason": "合作终止后归档客商主数据"},
        )
        self.assertEqual(archived.status_code, 200, archived.text)
        self.assertEqual(archived.json()["status"], "archived")
        self.assertEqual(self.client.get(f"/api/v1/counterparties/{created['id']}", headers=self.risk).status_code, 404)
        archived_detail = self.client.get(
            f"/api/v1/counterparties/{created['id']}?include_archived=true", headers=self.manager
        )
        self.assertEqual(archived_detail.status_code, 200, archived_detail.text)
        self.assertEqual(archived_detail.json()["status"], "archived")
        archived_page = self.client.get(
            "/api/v1/counterparties/page?q=测试企业主数据&status=archived&limit=5", headers=self.manager
        )
        self.assertEqual(archived_page.status_code, 200, archived_page.text)
        self.assertEqual(archived_page.json()["items"][0]["id"], created["id"])
        archived_history = self.client.get(
            f"/api/v1/counterparties/{created['id']}/history", headers=self.manager,
        )
        self.assertEqual(archived_history.status_code, 200, archived_history.text)
        self.assertEqual(archived_history.json()[0]["event_type"], "counterparty_archived")
        self.assertIn("status", archived_history.json()[0]["changed_fields"])
        repeated = self.client.post(
            f"/api/v1/counterparties/{created['id']}/archive", headers=self.manager,
            json={"expected_row_version": archived.json()["row_version"], "reason": "验证禁止重复归档客商"},
        )
        self.assertEqual(repeated.status_code, 409, repeated.text)

        with database.SessionLocal() as session:
            events = session.scalars(
                select(AuditEventRecord)
                .where(AuditEventRecord.aggregate_id == f"tenant-demo-hengxin:{created['id']}")
                .order_by(AuditEventRecord.created_at)
            ).all()
            self.assertEqual([event.event_type for event in events], [
                "counterparty_created", "counterparty_updated", "counterparty_archived",
            ])
            self.assertEqual(events[1].payload["before"]["current_limit"], 600000)
            self.assertEqual(events[1].payload["after"]["current_limit"], 900000)
            self.assertEqual(events[2].payload["reason"], "合作终止后归档客商主数据")

    def test_client_only_sees_own_counterparty_and_cross_tenant_is_hidden(self) -> None:
        client_list = self.client.get("/api/v1/counterparties", headers=self.client_headers)
        self.assertEqual(client_list.status_code, 200, client_list.text)
        self.assertEqual([item["id"] for item in client_list.json()], ["cp_supplier_low_001"])
        self.assertEqual(
            self.client.get("/api/v1/counterparties/cp_supplier_mid_001", headers=self.client_headers).status_code,
            404,
        )

        created = self.create()
        hidden = self.client.get(f"/api/v1/counterparties/{created['id']}", headers=self.integration_alt)
        self.assertEqual(hidden.status_code, 404, hidden.text)
        hidden_history = self.client.get(
            f"/api/v1/counterparties/{created['id']}/history", headers=self.integration_alt,
        )
        self.assertEqual(hidden_history.status_code, 404, hidden_history.text)

    def test_same_business_id_can_exist_in_different_tenants(self) -> None:
        created = self.create()
        with database.SessionLocal() as session:
            primary = session.scalars(
                select(CounterpartyRecord).where(
                    CounterpartyRecord.tenant_id == "tenant-demo-hengxin",
                    CounterpartyRecord.counterparty_id == created["id"],
                )
            ).one()
            alternate = CounterpartyRecord(
                id="cp-record-alt-test", tenant_id="tenant-demo-alt", counterparty_id=primary.counterparty_id,
                credit_code="91440300TESTALT001", name=primary.name, counterparty_type=primary.counterparty_type,
                industry=primary.industry, cooperation_status="active", is_key_counterparty=False,
                requested_limit=0, current_limit=0, current_payment_term_days=0,
                external_json={}, internal_json={}, financial_json={}, extensions_json={},
                profile_hash="0" * 64, status="active", source_type="manual",
                created_by="test", updated_by="test",
            )
            session.add(alternate)
            session.commit()
            count = session.scalar(select(func.count(CounterpartyRecord.id)).where(CounterpartyRecord.counterparty_id == created["id"]))
            self.assertEqual(count, 2)

    def test_decision_rejects_counterparty_that_only_exists_in_another_tenant(self) -> None:
        created = self.create()
        payload = {
            "request_id": "ALT-CP-SCOPE-20260907-001",
            "counterparty_id": created["id"],
            "assets": {"model_key": "general", "model_version": "MCR-20260711-001", "pipeline_code": "PIPELINE-GENERAL", "pipeline_version": 1},
            "metadata": {"source_system": "ERP", "scenario": "supplier_admission"},
        }
        response = self.client.post("/api/v1/decisions", headers=self.integration_alt, json=payload)
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["error"]["code"], "DECISION_INPUT_INVALID")


if __name__ == "__main__":
    unittest.main()
