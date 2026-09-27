from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import unittest
from copy import deepcopy

from fastapi.testclient import TestClient
from sqlalchemy import select

import backend.database as database
from backend.db_models import ApiClientRecord, DecisionJobRecord, DecisionWebhookDeliveryRecord
from backend.decision_jobs import job_rate_limiter
from backend.main import app
from backend.repository import clear_persistent_data
from scripts.seed_indicators import seed_from_pool_json
from scripts.seed_rule_center import seed_all
from tests.database_support import IsolatedTestDatabase


class DecisionJobApiTest(unittest.TestCase):
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
        job_rate_limiter.clear()
        self.headers = {"Authorization": "Bearer dev-integration"}
        self.item = {
            "request_id": "ERP-BATCH-ITEM-001",
            "counterparty_id": "cp_supplier_low_001",
            "input": None,
            "assets": {
                "model_key": "general", "model_version": "MCR-20260711-001",
                "pipeline_code": "PIPELINE-GENERAL", "pipeline_version": 1,
                "rule_set_versions": {}, "rule_versions": {},
            },
            "metadata": {"source_system": "ERP", "scenario": "supplier_admission"},
        }
        self.payload = {
            "job_key": "ERP-BATCH-20260903-001",
            "requests": [self.item],
            "callback": {
                "mode": "sandbox", "endpoint_url": "sandbox://customer-it/callback",
                "secret_reference": "sandbox-webhook-v1", "simulate_status_sequence": [503, 200], "max_attempts": 3,
            },
        }

    def create(self, payload: dict | None = None):
        return self.client.post("/api/v1/decision-jobs", json=payload or self.payload, headers=self.headers)

    def test_job_idempotency_and_conflict(self) -> None:
        first = self.create()
        second = self.create()
        self.assertEqual(first.status_code, 202, first.text)
        self.assertFalse(first.json()["idempotent"])
        self.assertTrue(second.json()["idempotent"])
        self.assertEqual(first.json()["id"], second.json()["id"])

        changed = deepcopy(self.payload)
        changed["requests"][0]["metadata"]["scenario"] = "credit_limit"
        conflict = self.create(changed)
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertEqual(conflict.json()["error"]["code"], "IDEMPOTENCY_CONFLICT")

    def test_same_job_key_and_records_are_isolated_between_tenants(self) -> None:
        primary = self.create()
        self.assertEqual(primary.status_code, 202, primary.text)

        alternate_headers = {"Authorization": "Bearer dev-integration-alt"}
        hidden = self.client.get(
            f"/api/v1/decision-jobs/{primary.json()['id']}",
            headers=alternate_headers,
        )
        self.assertEqual(hidden.status_code, 404, hidden.text)

        alternate = self.client.post(
            "/api/v1/decision-jobs",
            json=self.payload,
            headers=alternate_headers,
        )
        self.assertEqual(alternate.status_code, 202, alternate.text)
        self.assertEqual(alternate.json()["tenant_id"], "tenant-demo-alt")
        self.assertNotEqual(primary.json()["id"], alternate.json()["id"])

        listed = self.client.get("/api/v1/decision-jobs", headers=alternate_headers)
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual([item["id"] for item in listed.json()], [alternate.json()["id"]])

    def test_rejects_duplicate_request_ids_before_queueing(self) -> None:
        duplicate = deepcopy(self.item)
        payload = deepcopy(self.payload)
        payload["requests"].append(duplicate)
        response = self.create(payload)
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["error"]["code"], "DECISION_JOB_REQUEST_INVALID")

    def test_runs_partial_failure_without_losing_success_and_exports_csv(self) -> None:
        payload = deepcopy(self.payload)
        invalid = deepcopy(self.item)
        invalid["request_id"] = "ERP-BATCH-ITEM-002"
        invalid["counterparty_id"] = "not-found"
        payload["requests"].append(invalid)
        created = self.create(payload).json()

        response = self.client.post(f"/api/v1/decision-jobs/{created['id']}/run", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        job = response.json()
        self.assertEqual(job["status"], "completed_with_errors")
        self.assertEqual((job["succeeded_count"], job["failed_count"]), (1, 1))
        self.assertEqual(job["results"][0]["index"], 0)
        self.assertEqual(job["failures"][0]["index"], 1)
        self.assertEqual(len(job["evidence"]["evidence_hash"]), 64)

        downloaded = self.client.get(f"/api/v1/decision-jobs/{created['id']}/results.csv", headers=self.headers)
        self.assertEqual(downloaded.status_code, 200, downloaded.text)
        rows = list(csv.DictReader(io.StringIO(downloaded.content.decode("utf-8-sig"))))
        self.assertEqual([row["outcome"] for row in rows], ["success", "failed"])
        self.assertEqual(rows[1]["error_code"], "DECISION_INPUT_INVALID")

    def test_webhook_signature_can_be_recomputed_and_503_retries(self) -> None:
        job = self.create().json()
        self.client.post(f"/api/v1/decision-jobs/{job['id']}/run", headers=self.headers)
        delivery = self.client.get(f"/api/v1/decision-jobs/{job['id']}/webhooks", headers=self.headers).json()[0]
        self.assertEqual(delivery["status"], "retry_scheduled")
        self.assertEqual(delivery["last_status_code"], 503)
        self.assertIsNotNone(delivery["next_attempt_at"])
        canonical = json.dumps(delivery["payload"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        expected = hmac.new(
            b"sandbox-integration-secret",
            f"{delivery['signature_timestamp']}.{canonical}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(delivery["signature"], expected)

        retried = self.client.post(f"/api/v1/decision-webhooks/{delivery['id']}/retry", headers=self.headers)
        self.assertEqual(retried.status_code, 200, retried.text)
        self.assertEqual(retried.json()["status"], "delivered")
        self.assertEqual([row["status_code"] for row in retried.json()["history"]], [503, 200])

    def test_dead_letter_manual_redelivery_preserves_history(self) -> None:
        payload = deepcopy(self.payload)
        payload["callback"]["max_attempts"] = 1
        job = self.create(payload).json()
        self.client.post(f"/api/v1/decision-jobs/{job['id']}/run", headers=self.headers)
        delivery = self.client.get(f"/api/v1/decision-jobs/{job['id']}/webhooks", headers=self.headers).json()[0]
        self.assertEqual(delivery["status"], "dead_letter")

        redelivered = self.client.post(f"/api/v1/decision-webhooks/{delivery['id']}/redeliver", headers=self.headers)
        self.assertEqual(redelivered.status_code, 200, redelivered.text)
        body = redelivered.json()
        self.assertEqual(body["status"], "delivered")
        self.assertEqual(body["manual_redelivery_count"], 1)
        self.assertEqual(len(body["history"]), 2)
        self.assertTrue(body["history"][1]["manual"])

    def test_field_mapping_preview_handles_enum_multiplier_default_and_errors(self) -> None:
        payload = {
            "source": {"vendorNo": "V-100", "vendorName": "示例供应商", "vendorType": "SUP", "amountWan": 82.5},
            "mappings": [
                {"source_field": "vendorNo", "target_path": "id", "required": True},
                {"source_field": "vendorName", "target_path": "name", "required": True},
                {"source_field": "vendorType", "target_path": "counterparty_type", "enum_mapping": {"SUP": "supplier", "CUS": "customer"}, "required": True},
                {"source_field": "amountWan", "target_path": "requested_limit", "multiplier": 10000},
                {"source_field": "missing", "target_path": "internal.cooperation_years", "default_value": 0},
            ],
        }
        response = self.client.post("/api/v1/decisions/field-mapping/preview", json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "ready")
        self.assertEqual(body["normalized_input"]["counterparty_type"], "supplier")
        self.assertEqual(body["normalized_input"]["requested_limit"], 825000)
        self.assertEqual(body["coverage"]["coverage_rate"], 1)

        payload["source"]["vendorType"] = "UNKNOWN"
        blocked = self.client.post("/api/v1/decisions/field-mapping/preview", json=payload, headers=self.headers).json()
        self.assertEqual(blocked["status"], "blocked")
        self.assertIn("counterparty_type", blocked["missing_required"])
        self.assertEqual(blocked["errors"][0]["code"], "ENUM_VALUE_UNMAPPED")

    def test_permissions_and_client_profile_do_not_expose_secret(self) -> None:
        profile = self.client.get("/api/v1/decisions/client-profile", headers=self.headers)
        self.assertEqual(profile.status_code, 200, profile.text)
        self.assertEqual(profile.json()["tenant_name"], "恒信演示租户")
        self.assertEqual(profile.json()["deployment_mode"], "saas")
        self.assertEqual(profile.json()["qps_limit"], 20)
        self.assertFalse(profile.json()["production_secret_exposed"])
        self.assertNotIn("secret", profile.json())
        forbidden = self.client.post("/api/v1/decision-jobs", json=self.payload, headers={"Authorization": "Bearer dev-auditor"})
        self.assertEqual(forbidden.status_code, 403, forbidden.text)

        with database.SessionLocal() as session:
            job = session.scalars(select(DecisionJobRecord)).first()
            if job:
                self.assertNotIn("sandbox-integration-secret", json.dumps(job.request_json))
            delivery = session.scalars(select(DecisionWebhookDeliveryRecord)).first()
            if delivery:
                self.assertNotIn("sandbox-integration-secret", json.dumps(delivery.payload_json))

    def test_qps_concurrency_and_daily_quotas_return_retry_header(self) -> None:
        with database.SessionLocal() as session:
            profile = session.scalars(
                select(ApiClientRecord).where(
                    ApiClientRecord.tenant_id == "tenant-demo-hengxin",
                    ApiClientRecord.client_id == "erp-integration-sandbox",
                )
            ).one()
            original = (profile.qps_limit, profile.concurrent_job_limit, profile.daily_item_quota)
        try:
            with database.SessionLocal() as session:
                profile = session.get(ApiClientRecord, profile.id)
                profile.qps_limit = 1
                session.commit()
            self.assertEqual(self.create().status_code, 202)
            other = deepcopy(self.payload)
            other["job_key"] = "ERP-BATCH-QUOTA-QPS"
            qps = self.create(other)
            self.assertEqual(qps.status_code, 429, qps.text)
            self.assertEqual(qps.json()["error"]["details"]["limit_type"], "qps")
            self.assertEqual(qps.headers["Retry-After"], "1")

            job_rate_limiter.clear()
            with database.SessionLocal() as session:
                profile = session.get(ApiClientRecord, profile.id)
                profile.qps_limit = 20
                profile.concurrent_job_limit = 1
                queued = session.scalars(select(DecisionJobRecord)).one()
                queued.status = "running"
                session.commit()
            concurrent = self.create(other)
            self.assertEqual(concurrent.status_code, 429, concurrent.text)
            self.assertEqual(concurrent.json()["error"]["details"]["limit_type"], "concurrent_jobs")

            with database.SessionLocal() as session:
                running = session.scalars(select(DecisionJobRecord)).one()
                running.status = "completed"
                session.commit()
            job_rate_limiter.clear()
            with database.SessionLocal() as session:
                profile = session.get(ApiClientRecord, profile.id)
                profile.concurrent_job_limit = 3
                profile.daily_item_quota = 1
                session.commit()
            daily = self.create(other)
            self.assertEqual(daily.status_code, 429, daily.text)
            self.assertEqual(daily.json()["error"]["details"]["limit_type"], "daily_items")
        finally:
            with database.SessionLocal() as session:
                profile = session.get(ApiClientRecord, profile.id)
                profile.qps_limit, profile.concurrent_job_limit, profile.daily_item_quota = original
                session.commit()
            job_rate_limiter.clear()


if __name__ == "__main__":
    unittest.main()
