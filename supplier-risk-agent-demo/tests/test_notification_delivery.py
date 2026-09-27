from __future__ import annotations

import hashlib
import hmac
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import backend.database as database
from backend.db_models import AuditEventRecord, NotificationRecord, TenantNotificationChannelRecord, TenantNotificationDeliveryRecord
from backend.jobs.notification_delivery_dispatch import run_notification_delivery_dispatch
from backend.main import app
from backend.repository import NotificationRepository
from fastapi.testclient import TestClient
from tests.database_support import IsolatedTestDatabase


TENANT_ID = "tenant-demo-hengxin"
HEADERS = {"Authorization": "Bearer dev-risk"}


class TestTenantNotificationDelivery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = IsolatedTestDatabase()
        cls.db.start()

    @classmethod
    def tearDownClass(cls):
        cls.db.stop()

    def setUp(self):
        with database.SessionLocal() as session:
            session.query(AuditEventRecord).filter(AuditEventRecord.aggregate_type.in_([
                "tenant_notification_channel", "tenant_notification_delivery", "notification_delivery_dispatch",
            ])).delete(synchronize_session=False)
            session.query(TenantNotificationDeliveryRecord).delete()
            session.query(TenantNotificationChannelRecord).delete()
            session.query(NotificationRecord).filter(NotificationRecord.tenant_id == TENANT_ID).delete()
            session.commit()

    @staticmethod
    def _channel(**overrides) -> dict:
        payload = {
            "name": "模型风险通知沙箱", "delivery_mode": "sandbox",
            "endpoint_url": "sandbox://enterprise-message/model-risk",
            "secret_reference": "env:TENANT_NOTIFICATION_WEBHOOK_SECRET",
            "subscribed_categories": ["model_risk_assignment", "model_risk_delegation", "monitoring_diff_case_sla"],
            "recipient_roles": ["risk_manager"], "minimum_severity": "warning",
            "max_attempts": 3, "timeout_seconds": 5, "require_receipt": True,
            "sandbox_status_sequence": [503, 200], "status": "active",
        }
        payload.update(overrides)
        return payload

    @staticmethod
    def _notification(category: str = "model_risk_assignment", severity: str = "warning") -> str:
        with database.SessionLocal() as session:
            notification, _ = NotificationRepository(session).create_if_absent(TENANT_ID, {
                "case_id": None, "counterparty_id": None,
                "recipient_role": "risk_manager", "recipient_subject": "risk-demo",
                "category": category, "level": "handoff", "severity": severity,
                "title": "模型风险事项已交接", "message": "一条待复核事项已交接给当前值班人员。",
                "action_json": {"page": "model-governance", "target": "model-risk-policy"},
                "dedup_key": f"notification-delivery-test:{category}:{severity}", "status": "unread",
            })
            session.commit()
            return notification["id"]

    def test_signed_outbox_retries_and_is_idempotent(self):
        notification_id = self._notification()
        with TestClient(app) as client:
            created = client.post("/api/v1/notifications/channels", json=self._channel(), headers=HEADERS)
            self.assertEqual(created.status_code, 201, created.text)
            dispatched = client.post("/api/v1/notifications/deliveries/dispatch", json={"limit": 100}, headers=HEADERS)
            self.assertEqual(dispatched.status_code, 200, dispatched.text)
            self.assertEqual(dispatched.json()["deliveries_created"], 1)
            self.assertEqual(dispatched.json()["retry_scheduled"], 1)

            ledger = client.get("/api/v1/notifications/deliveries", headers=HEADERS).json()
            self.assertEqual(ledger["counts"]["retry_scheduled"], 1)
            delivery = ledger["items"][0]
            self.assertEqual(delivery["notification_id"], notification_id)
            self.assertEqual(delivery["payload_hash"], hashlib.sha256(json.dumps(
                delivery["payload"], ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")).hexdigest())
            expected_signature = hmac.new(
                b"sandbox-notification-secret",
                f"{delivery['signature_timestamp']}.{json.dumps(delivery['payload'], ensure_ascii=False, sort_keys=True, separators=(',', ':'))}".encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            self.assertEqual(delivery["signature"], expected_signature)

            retried = client.post(
                f"/api/v1/notifications/deliveries/{delivery['id']}/retry",
                json={"expected_row_version": delivery["row_version"]}, headers=HEADERS,
            )
            self.assertEqual(retried.status_code, 200, retried.text)
            self.assertEqual(retried.json()["status"], "delivered")
            self.assertTrue(retried.json()["receipt"]["verified"])
            self.assertEqual(retried.json()["attempt_count"], 2)

            repeated = client.post("/api/v1/notifications/deliveries/dispatch", json={"limit": 100}, headers=HEADERS)
            self.assertEqual(repeated.json()["deliveries_created"], 0)
            self.assertEqual(repeated.json()["attempted"], 0)

    def test_channel_filters_permissions_and_tenant_isolation(self):
        self._notification(severity="info")
        with TestClient(app) as client:
            blocked = client.post("/api/v1/notifications/channels", json=self._channel(), headers={"Authorization": "Bearer dev-client"})
            self.assertEqual(blocked.status_code, 403)
            created = client.post("/api/v1/notifications/channels", json=self._channel(minimum_severity="warning"), headers=HEADERS)
            self.assertEqual(created.status_code, 201)
            result = client.post("/api/v1/notifications/deliveries/dispatch", json={"limit": 100}, headers=HEADERS).json()
            self.assertEqual(result["deliveries_created"], 0)
            alternate = client.get("/api/v1/notifications/channels", headers={"Authorization": "Bearer dev-integration-alt"})
            self.assertEqual(alternate.status_code, 200)
            self.assertEqual(alternate.json(), [])

    def test_disabling_channel_cancels_pending_delivery(self):
        self._notification()
        with TestClient(app) as client:
            channel = client.post("/api/v1/notifications/channels", json=self._channel(), headers=HEADERS).json()
            client.post("/api/v1/notifications/deliveries/dispatch", json={"limit": 100}, headers=HEADERS)
            update = {**self._channel(status="disabled"), "expected_row_version": channel["row_version"]}
            disabled = client.put(f"/api/v1/notifications/channels/{channel['id']}", json=update, headers=HEADERS)
            self.assertEqual(disabled.status_code, 200, disabled.text)
            ledger = client.get("/api/v1/notifications/deliveries", headers=HEADERS).json()
            self.assertEqual(ledger["counts"]["cancelled"], 1)

    def test_dead_letter_manual_replay_and_scheduler_scope(self):
        self._notification()
        with TestClient(app) as client:
            client.post("/api/v1/notifications/channels", json=self._channel(max_attempts=1, sandbox_status_sequence=[400]), headers=HEADERS)
            dispatched = client.post("/api/v1/notifications/deliveries/dispatch", json={"limit": 100}, headers=HEADERS).json()
            self.assertEqual(dispatched["dead_letter"], 1)
            delivery = client.get("/api/v1/notifications/deliveries?status=dead_letter", headers=HEADERS).json()["items"][0]
            replayed = client.post(
                f"/api/v1/notifications/deliveries/{delivery['id']}/redeliver",
                json={"expected_row_version": delivery["row_version"]}, headers=HEADERS,
            )
            self.assertEqual(replayed.status_code, 200, replayed.text)
            self.assertEqual(replayed.json()["status"], "dead_letter")
            self.assertEqual(replayed.json()["manual_redelivery_count"], 1)
        with database.SessionLocal() as session:
            result = run_notification_delivery_dispatch(session, tenant_id=TENANT_ID)
            self.assertEqual(result["tenant_count"], 1)
            self.assertEqual(result["failed_count"], 0)

    def test_live_channel_requires_current_successful_preflight(self):
        live = self._channel(
            name="企业消息正式渠道", delivery_mode="live",
            endpoint_url="https://hooks.example.com/model-risk", sandbox_status_sequence=[200],
        )

        class Response:
            status_code = 200
            content = b'{"accepted":true}'

            def __init__(self, event_id: str):
                self.headers = {"X-Hengxin-Event-Id": event_id}

        def respond(*_args, **kwargs):
            return Response(kwargs["headers"]["X-Hengxin-Webhook-Id"])

        with patch.dict(os.environ, {"TENANT_NOTIFICATION_WEBHOOK_SECRET": "live-test-secret"}), patch(
            "backend.notification_delivery_repository.httpx.post", side_effect=respond,
        ):
            with TestClient(app) as client:
                channel = client.post("/api/v1/notifications/channels", json=live, headers=HEADERS).json()
                self.assertEqual(channel["status"], "disabled")
                self.assertEqual(channel["preflight_status"], "required")

                blocked = client.put(
                    f"/api/v1/notifications/channels/{channel['id']}",
                    json={**live, "status": "active", "expected_row_version": channel["row_version"]}, headers=HEADERS,
                )
                self.assertEqual(blocked.status_code, 409)

                tested = client.post(
                    f"/api/v1/notifications/channels/{channel['id']}/test",
                    json={"expected_row_version": channel["row_version"]}, headers=HEADERS,
                )
                self.assertEqual(tested.status_code, 200, tested.text)
                self.assertTrue(tested.json()["passed"])
                self.assertEqual(tested.json()["delivery"]["event_type"], "tenant.notification.channel_test")

                enabled = client.put(
                    f"/api/v1/notifications/channels/{channel['id']}",
                    json={**live, "status": "active", "expected_row_version": channel["row_version"]}, headers=HEADERS,
                )
                self.assertEqual(enabled.status_code, 200, enabled.text)
                self.assertEqual(enabled.json()["status"], "active")
                self.assertEqual(enabled.json()["preflight_status"], "passed")

                changed = client.put(
                    f"/api/v1/notifications/channels/{channel['id']}",
                    json={**live, "endpoint_url": "https://hooks.example.com/model-risk-v2", "status": "active", "expected_row_version": enabled.json()["row_version"]},
                    headers=HEADERS,
                )
                self.assertEqual(changed.status_code, 409)

    def test_operations_summary_detects_dead_letter_sla_incident(self):
        self._notification()
        with TestClient(app) as client:
            client.post(
                "/api/v1/notifications/channels",
                json=self._channel(max_attempts=1, sandbox_status_sequence=[400]), headers=HEADERS,
            )
            client.post("/api/v1/notifications/deliveries/dispatch", json={"limit": 100}, headers=HEADERS)
        with database.SessionLocal() as session:
            delivery = session.query(TenantNotificationDeliveryRecord).filter_by(tenant_id=TENANT_ID).one()
            delivery.updated_at = datetime.now(timezone.utc) - timedelta(minutes=31)
            session.commit()
        with TestClient(app) as client:
            operations = client.get("/api/v1/notifications/deliveries/operations?window_hours=24", headers=HEADERS)
            self.assertEqual(operations.status_code, 200, operations.text)
            body = operations.json()
            self.assertEqual(body["health"], "incident")
            self.assertEqual(body["deliveries"]["dead_letter"], 1)
            self.assertEqual(body["deliveries"]["dead_letter_sla_breaches"], 1)
            self.assertEqual(body["recent_failures"][0]["status_code"], 400)


if __name__ == "__main__":
    unittest.main()
