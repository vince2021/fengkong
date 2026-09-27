from __future__ import annotations

import json
import unittest
from copy import deepcopy

from fastapi.testclient import TestClient
from sqlalchemy import func, select

import backend.database as database
from backend.db_models import AuditEventRecord, CounterpartyImportBatchRecord, CounterpartyRecord
from backend.main import app
from backend.repository import clear_persistent_data
from tests.database_support import IsolatedTestDatabase


class CounterpartyImportApiTest(unittest.TestCase):
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
            for row in session.scalars(
                select(CounterpartyRecord).where(CounterpartyRecord.counterparty_id.like("cp_import_%"))
            ).all():
                session.delete(row)
            session.commit()
        self.manager = {"Authorization": "Bearer dev-manager"}
        self.risk = {"Authorization": "Bearer dev-risk"}
        self.admin = {"Authorization": "Bearer dev-admin"}
        self.client_headers = {"Authorization": "Bearer dev-client"}

    @staticmethod
    def row(counterparty_id: str = "cp_import_001", credit_code: str = "91440300IMPORT001") -> dict:
        return {
            "id": counterparty_id,
            "credit_code": credit_code,
            "name": f"批量导入企业{counterparty_id[-3:]}",
            "counterparty_type": "supplier",
            "industry": "manufacturing",
            "cooperation_status": "active",
            "is_key_counterparty": False,
            "requested_limit": 1200000,
            "current_limit": 300000,
            "current_payment_term_days": 30,
            "external": {"registration_status": "存续"},
            "internal": {"orders_12m": 12},
            "financial": {"overdue_rate": 0.01},
            "custom_source_tag": "migration-wave-1",
        }

    def payload(self, import_key: str, rows: list[dict], **overrides) -> dict:
        payload = {
            "import_key": import_key,
            "file_name": f"{import_key}.json",
            "file_format": "json",
            "content": json.dumps(rows, ensure_ascii=False),
            "duplicate_strategy": "reject",
            "field_mapping": {},
            "reason": "客户首批客商主数据迁移预检",
        }
        payload.update(overrides)
        return payload

    def precheck(self, import_key: str, rows: list[dict], **overrides) -> dict:
        response = self.client.post(
            "/api/v1/counterparties/imports/precheck",
            headers=self.manager,
            json=self.payload(import_key, rows, **overrides),
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def commit(self, batch: dict, **overrides):
        payload = {
            "expected_row_version": batch["row_version"],
            "preview_hash": batch["preview_hash"],
            "reason": "确认预检结果并提交客户迁移批次",
        }
        payload.update(overrides)
        return self.client.post(
            f"/api/v1/counterparties/imports/{batch['id']}/commit",
            headers=self.manager,
            json=payload,
        )

    def test_json_precheck_is_idempotent_and_commit_is_atomic_and_audited(self) -> None:
        rows = [self.row(), self.row("cp_import_002", "91440300IMPORT002")]
        payload = self.payload("CP-IMPORT-JSON-001", rows)
        first = self.client.post("/api/v1/counterparties/imports/precheck", headers=self.manager, json=payload)
        replay = self.client.post("/api/v1/counterparties/imports/precheck", headers=self.manager, json=payload)
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(replay.status_code, 201, replay.text)
        batch = first.json()
        self.assertFalse(batch["idempotent"])
        self.assertTrue(replay.json()["idempotent"])
        self.assertEqual((batch["status"], batch["total_count"], batch["create_count"]), ("prechecked", 2, 2))
        self.assertEqual(len(batch["source_hash"]), 64)
        self.assertEqual(batch["row_receipts"][0]["action"], "create")

        changed = deepcopy(payload)
        changed["content"] = json.dumps([self.row("cp_import_003", "91440300IMPORT003")], ensure_ascii=False)
        conflict = self.client.post("/api/v1/counterparties/imports/precheck", headers=self.manager, json=changed)
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertEqual(conflict.json()["detail"]["code"], "COUNTERPARTY_IMPORT_KEY_CONFLICT")

        committed = self.commit(batch)
        self.assertEqual(committed.status_code, 200, committed.text)
        self.assertEqual((committed.json()["status"], committed.json()["committed_count"]), ("committed", 2))
        repeated = self.commit(batch)
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertTrue(repeated.json()["idempotent"])

        detail = self.client.get("/api/v1/counterparties/cp_import_001", headers=self.risk)
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["source_type"], "batch_import")
        self.assertEqual(detail.json()["custom_source_tag"], "migration-wave-1")
        with database.SessionLocal() as session:
            events = session.scalars(
                select(AuditEventRecord).where(
                    AuditEventRecord.aggregate_id == "tenant-demo-hengxin:CP-IMPORT-JSON-001"
                ).order_by(AuditEventRecord.created_at)
            ).all()
            self.assertEqual([event.event_type for event in events], [
                "counterparty_import_prechecked", "counterparty_import_committed",
            ])
            cp_event = session.scalars(select(AuditEventRecord).where(
                AuditEventRecord.aggregate_id == "tenant-demo-hengxin:cp_import_001"
            )).one()
            self.assertEqual(cp_event.payload["import_key"], "CP-IMPORT-JSON-001")
            self.assertEqual(cp_event.payload["preview_hash"], batch["preview_hash"])

    def test_blocked_precheck_returns_every_row_error_and_cannot_commit(self) -> None:
        duplicate = self.row()
        invalid = self.row("cp_import_003", "91440300IMPORT003")
        invalid["counterparty_type"] = "partner"
        batch = self.precheck("CP-IMPORT-BLOCKED-001", [duplicate, duplicate, invalid])
        self.assertEqual(batch["status"], "blocked")
        self.assertEqual(batch["invalid_count"], 3)
        self.assertEqual(batch["row_receipts"][0]["errors"][0]["code"], "DUPLICATE_IN_FILE")
        self.assertTrue(any(error["field"] == "counterparty_type" for error in batch["row_receipts"][2]["errors"]))

        response = self.commit(batch)
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["detail"]["code"], "COUNTERPARTY_IMPORT_BLOCKED")
        self.assertEqual(self.client.get("/api/v1/counterparties/cp_import_001", headers=self.risk).status_code, 404)

    def test_blocked_batch_can_export_receipt_and_copy_a_tenant_scoped_correction_draft(self) -> None:
        duplicate = self.row()
        batch = self.precheck("CP-IMPORT-CORRECT-001", [duplicate, duplicate])

        receipt = self.client.get(
            f"/api/v1/counterparties/imports/{batch['id']}/receipt.csv", headers=self.risk
        )
        self.assertEqual(receipt.status_code, 200, receipt.text)
        self.assertTrue(receipt.content.startswith(b"\xef\xbb\xbf"))
        decoded = receipt.content.decode("utf-8-sig")
        self.assertIn("行号,客商编号,统一社会信用代码,处理动作", decoded)
        self.assertIn("DUPLICATE_IN_FILE", decoded)
        self.assertIn("attachment", receipt.headers["content-disposition"])

        draft = self.client.get(
            f"/api/v1/counterparties/imports/{batch['id']}/correction-draft", headers=self.manager
        )
        self.assertEqual(draft.status_code, 200, draft.text)
        self.assertEqual(draft.json()["source_batch_id"], batch["id"])
        self.assertEqual(draft.json()["content"], json.dumps([duplicate, duplicate], ensure_ascii=False))
        self.assertNotEqual(draft.json()["suggested_import_key"], batch["import_key"])
        self.assertEqual(
            self.client.get(
                f"/api/v1/counterparties/imports/{batch['id']}/correction-draft", headers=self.risk
            ).status_code,
            403,
        )

        ready = self.precheck("CP-IMPORT-CORRECT-READY", [self.row("cp_import_ready", "91440300IMPORTRDY1")])
        denied = self.client.get(
            f"/api/v1/counterparties/imports/{ready['id']}/correction-draft", headers=self.manager
        )
        self.assertEqual(denied.status_code, 422, denied.text)
        self.assertEqual(denied.json()["detail"]["code"], "COUNTERPARTY_IMPORT_NOT_BLOCKED")

    def test_csv_field_mapping_coerces_types_and_preserves_nested_values(self) -> None:
        content = (
            "vendor_id,license,company,kind,limit,key_flag,registration\n"
            "cp_import_csv_001,91440300IMPORTCSV1,CSV映射企业,supplier,2500000,是,存续\n"
        )
        response = self.client.post(
            "/api/v1/counterparties/imports/precheck",
            headers=self.manager,
            json={
                "import_key": "CP-IMPORT-CSV-001", "file_name": "customer-master.csv", "file_format": "csv",
                "content": content, "duplicate_strategy": "reject",
                "field_mapping": {
                    "vendor_id": "counterparty_id", "license": "credit_code", "company": "name",
                    "kind": "counterparty_type", "limit": "requested_limit", "key_flag": "is_key_counterparty",
                    "registration": "external.registration_status",
                },
                "reason": "校验客户 CSV 字段映射配置",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        batch = response.json()
        self.assertEqual((batch["status"], batch["create_count"], batch["row_receipts"][0]["row_number"]), ("prechecked", 1, 2))
        committed = self.commit(batch)
        self.assertEqual(committed.status_code, 200, committed.text)
        counterparty = self.client.get("/api/v1/counterparties/cp_import_csv_001", headers=self.risk).json()
        self.assertEqual(counterparty["requested_limit"], 2500000)
        self.assertTrue(counterparty["is_key_counterparty"])
        self.assertEqual(counterparty["external"]["registration_status"], "存续")

    def test_duplicate_strategies_skip_and_update_are_explicit(self) -> None:
        existing = self.row("cp_supplier_low_001", "91440300MA5STABLE1")
        existing["name"] = "不应覆盖的名称"
        skip = self.precheck("CP-IMPORT-SKIP-001", [existing], duplicate_strategy="skip")
        self.assertEqual((skip["skip_count"], skip["row_receipts"][0]["action"]), (1, "skip"))
        self.assertEqual(self.commit(skip).status_code, 200)
        unchanged = self.client.get("/api/v1/counterparties/cp_supplier_low_001", headers=self.risk).json()
        self.assertNotEqual(unchanged["name"], "不应覆盖的名称")

        existing["name"] = "批量更新后的稳健电子"
        existing["current_limit"] = 880000
        update = self.precheck("CP-IMPORT-UPDATE-001", [existing], duplicate_strategy="update")
        self.assertEqual(update["update_count"], 1)
        committed = self.commit(update)
        self.assertEqual(committed.status_code, 200, committed.text)
        changed = self.client.get("/api/v1/counterparties/cp_supplier_low_001", headers=self.risk).json()
        self.assertEqual((changed["name"], changed["current_limit"]), ("批量更新后的稳健电子", 880000))
        self.assertEqual(changed["source_type"], "batch_import")

    def test_stale_precheck_rolls_back_the_entire_batch(self) -> None:
        update = self.row("cp_supplier_low_001", "91440300MA5STABLE1")
        update["current_limit"] = 770000
        batch = self.precheck(
            "CP-IMPORT-STALE-001",
            [self.row("cp_import_atomic_001", "91440300IMPORTATOM1"), update],
            duplicate_strategy="update",
        )
        with database.SessionLocal() as session:
            existing = session.scalars(select(CounterpartyRecord).where(
                CounterpartyRecord.tenant_id == "tenant-demo-hengxin",
                CounterpartyRecord.counterparty_id == "cp_supplier_low_001",
            )).one()
            existing.current_limit = 660000
            session.commit()

        response = self.commit(batch)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["code"], "COUNTERPARTY_IMPORT_STALE")
        self.assertEqual(self.client.get("/api/v1/counterparties/cp_import_atomic_001", headers=self.risk).status_code, 404)
        with database.SessionLocal() as session:
            persisted = session.get(CounterpartyImportBatchRecord, batch["id"])
            self.assertEqual(persisted.status, "prechecked")

    def test_preview_tampering_is_detected_before_any_write(self) -> None:
        batch = self.precheck("CP-IMPORT-TAMPER-001", [self.row()])
        with database.SessionLocal() as session:
            record = session.get(CounterpartyImportBatchRecord, batch["id"])
            rows = deepcopy(record.normalized_rows_json)
            rows[0]["name"] = "数据库篡改后的名称"
            record.normalized_rows_json = rows
            session.commit()
        response = self.commit(batch, expected_row_version=batch["row_version"] + 1)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["code"], "COUNTERPARTY_IMPORT_PREVIEW_TAMPERED")

    def test_permissions_and_tenant_isolation_apply_to_batches(self) -> None:
        denied = self.client.post(
            "/api/v1/counterparties/imports/precheck", headers=self.risk,
            json=self.payload("CP-IMPORT-SCOPE-001", [self.row()]),
        )
        self.assertEqual(denied.status_code, 403, denied.text)
        hidden_from_client = self.client.get("/api/v1/counterparties/imports", headers=self.client_headers)
        self.assertEqual(hidden_from_client.status_code, 403, hidden_from_client.text)
        self.assertEqual(self.client.get("/api/v1/counterparties/imports", headers=self.risk).status_code, 200)
        primary = self.precheck("CP-IMPORT-SCOPE-001", [self.row()])

        admin_payload = self.payload(
            "CP-IMPORT-SCOPE-001", [self.row("cp_import_admin_001", "91440300IMPORTADM1")]
        )
        alternate = self.client.post("/api/v1/counterparties/imports/precheck", headers=self.admin, json=admin_payload)
        self.assertEqual(alternate.status_code, 201, alternate.text)
        self.assertNotEqual(primary["tenant_id"], alternate.json()["tenant_id"])
        self.assertEqual(
            self.client.get(f"/api/v1/counterparties/imports/{alternate.json()['id']}", headers=self.manager).status_code,
            404,
        )
        page = self.client.get("/api/v1/counterparties/imports", headers=self.manager)
        self.assertEqual(page.status_code, 200, page.text)
        self.assertEqual(page.json()["total"], 1)
        self.assertEqual(page.json()["items"][0]["id"], primary["id"])

    def test_mapping_templates_are_versioned_audited_and_tenant_scoped(self) -> None:
        payload = {
            "template_key": "ERP-SUPPLIER-V1",
            "name": "ERP 供应商主数据映射",
            "file_format": "csv",
            "mapping": {"vendor_id": "counterparty_id", "company": "name", "license": "credit_code"},
            "description": "用于 ERP 供应商主数据首批迁移",
            "reason": "建立已核验的 ERP 字段映射模板",
        }
        created = self.client.post(
            "/api/v1/counterparties/import-mapping-templates", headers=self.manager, json=payload
        )
        self.assertEqual(created.status_code, 201, created.text)
        template = created.json()
        self.assertEqual((template["status"], template["row_version"]), ("active", 1))
        self.assertEqual(len(template["mapping_hash"]), 64)

        visible = self.client.get("/api/v1/counterparties/import-mapping-templates", headers=self.risk)
        self.assertEqual(visible.status_code, 200, visible.text)
        self.assertEqual(visible.json()[0]["template_key"], payload["template_key"])
        self.assertEqual(
            self.client.get("/api/v1/counterparties/import-mapping-templates", headers=self.client_headers).status_code,
            403,
        )

        updated = self.client.patch(
            f"/api/v1/counterparties/import-mapping-templates/{template['id']}",
            headers=self.manager,
            json={
                "mapping": {**payload["mapping"], "amount": "requested_limit"},
                "description": "用于 ERP 供应商主数据首批迁移及额度转换",
                "expected_row_version": template["row_version"],
                "reason": "补充申请额度字段并完成业务确认",
            },
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["row_version"], 2)
        conflict = self.client.patch(
            f"/api/v1/counterparties/import-mapping-templates/{template['id']}",
            headers=self.manager,
            json={"name": "过期版本更新", "expected_row_version": 1, "reason": "模拟并发版本冲突测试"},
        )
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertEqual(conflict.json()["detail"]["code"], "COUNTERPARTY_MAPPING_VERSION_CONFLICT")

        archived = self.client.post(
            f"/api/v1/counterparties/import-mapping-templates/{template['id']}/archive",
            headers=self.manager,
            json={"expected_row_version": 2, "reason": "ERP 接口字段版本下线后归档"},
        )
        self.assertEqual(archived.status_code, 200, archived.text)
        self.assertEqual(archived.json()["status"], "archived")
        self.assertEqual(self.client.get(
            "/api/v1/counterparties/import-mapping-templates", headers=self.manager
        ).json(), [])
        self.assertEqual(len(self.client.get(
            "/api/v1/counterparties/import-mapping-templates?status=archived", headers=self.manager
        ).json()), 1)

        other_tenant = self.client.post(
            "/api/v1/counterparties/import-mapping-templates", headers=self.admin, json=payload
        )
        self.assertEqual(other_tenant.status_code, 201, other_tenant.text)
        self.assertNotEqual(other_tenant.json()["tenant_id"], template["tenant_id"])
        with database.SessionLocal() as session:
            events = session.scalars(
                select(AuditEventRecord).where(
                    AuditEventRecord.aggregate_id == "tenant-demo-hengxin:ERP-SUPPLIER-V1"
                ).order_by(AuditEventRecord.created_at)
            ).all()
            self.assertEqual([event.event_type for event in events], [
                "counterparty_import_mapping_created",
                "counterparty_import_mapping_updated",
                "counterparty_import_mapping_archived",
            ])


if __name__ == "__main__":
    unittest.main()
