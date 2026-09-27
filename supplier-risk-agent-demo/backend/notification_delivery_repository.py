"""Tenant-scoped notification channels and auditable outbound delivery."""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import math
import os
import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from backend.db_models import AuditEventRecord, NotificationRecord, TenantNotificationChannelRecord, TenantNotificationDeliveryRecord
from backend.repository import AuditRepository, content_hash


SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}
SECRET_REFERENCE_PATTERN = re.compile(r"^env:[A-Z][A-Z0-9_]{2,127}$")
CHANNEL_TEST_EVENT = "tenant.notification.channel_test"
DEAD_LETTER_SLA_MINUTES = 30


class NotificationDeliveryError(ValueError):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class NotificationDeliveryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit = AuditRepository(session)

    def list_channels(self, tenant_id: str) -> list[dict]:
        rows = self.session.scalars(select(TenantNotificationChannelRecord).where(
            TenantNotificationChannelRecord.tenant_id == tenant_id,
        ).order_by(TenantNotificationChannelRecord.status, TenantNotificationChannelRecord.created_at.desc())).all()
        return [self._channel_view(row) for row in rows]

    def create_channel(self, tenant_id: str, payload: dict, actor_subject: str, actor_name: str) -> dict:
        config = self._validate_channel(payload)
        if config["delivery_mode"] == "live":
            config["status"] = "disabled"
        record = TenantNotificationChannelRecord(
            id=str(uuid4()), tenant_id=tenant_id, created_by=actor_subject, created_by_name=actor_name,
            **config,
        )
        self.session.add(record)
        try:
            self.session.flush()
            self.audit.append("tenant_notification_channel", record.id, "tenant_notification_channel_created", actor_subject, {
                "tenant_id": tenant_id, "name": record.name, "delivery_mode": record.delivery_mode,
                "endpoint_url": record.endpoint_url, "secret_reference": record.secret_reference,
                "categories": record.subscribed_categories_json, "roles": record.recipient_roles_json,
            })
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise NotificationDeliveryError("CHANNEL_NAME_CONFLICT", "当前租户已存在同名通知渠道", 409) from exc
        self.session.refresh(record)
        return self._channel_view(record)

    def update_channel(self, tenant_id: str, channel_id: str, expected_row_version: int, payload: dict, actor_subject: str) -> dict:
        record = self._channel(tenant_id, channel_id)
        if record.row_version != expected_row_version:
            raise NotificationDeliveryError("ROW_VERSION_CONFLICT", "通知渠道已被更新，请刷新后重试", 409)
        config = self._validate_channel(payload)
        proposed_hash = content_hash(self._channel_snapshot_from_config(channel_id, config))
        if config["delivery_mode"] == "live" and config["status"] == "active" and not self._has_successful_preflight(
            tenant_id, channel_id, proposed_hash,
        ):
            raise NotificationDeliveryError(
                "LIVE_PREFLIGHT_REQUIRED", "正式渠道的当前配置尚未通过测试投递，不能启用", 409,
            )
        prior_status = record.status
        for key, value in config.items():
            setattr(record, key, value)
        try:
            self.session.flush()
            if prior_status != "disabled" and record.status == "disabled":
                pending = self.session.scalars(select(TenantNotificationDeliveryRecord).where(
                    TenantNotificationDeliveryRecord.tenant_id == tenant_id,
                    TenantNotificationDeliveryRecord.channel_id == record.id,
                    TenantNotificationDeliveryRecord.status.in_(["pending", "retry_scheduled"]),
                )).all()
                for delivery in pending:
                    delivery.status = "cancelled"
                    delivery.next_attempt_at = None
                    delivery.last_error = "通知渠道已停用，未完成投递已取消"
            self.audit.append("tenant_notification_channel", record.id, "tenant_notification_channel_updated", actor_subject, {
                "tenant_id": tenant_id, "status": record.status, "delivery_mode": record.delivery_mode,
                "endpoint_url": record.endpoint_url, "categories": record.subscribed_categories_json,
                "roles": record.recipient_roles_json,
            })
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise NotificationDeliveryError("CONCURRENT_UPDATE", "通知渠道更新发生并发冲突", 409) from exc
        self.session.refresh(record)
        return self._channel_view(record)

    def test_channel(self, tenant_id: str, channel_id: str, expected_row_version: int, actor_subject: str) -> dict:
        channel = self._channel(tenant_id, channel_id)
        if channel.row_version != expected_row_version:
            raise NotificationDeliveryError("ROW_VERSION_CONFLICT", "通知渠道已被更新，请刷新后重试", 409)
        now = self._as_utc(datetime.now(timezone.utc))
        notification = NotificationRecord(
            id=str(uuid4()), tenant_id=tenant_id, case_id=None, counterparty_id=None,
            recipient_role="integration_admin", recipient_subject=actor_subject,
            category="notification_channel_test", level="preflight", severity="info",
            title=f"通知渠道测试：{channel.name}", message="验证端点连通性、签名、幂等键和业务回执。",
            action_json={"page": "operations", "target": "notification-delivery-operations"},
            dedup_key=f"notification-channel-test:{channel.id}:{uuid4()}", status="resolved",
        )
        self.session.add(notification)
        self.session.flush()
        delivery = self._create_delivery(channel, notification, actor_subject, now, event_type=CHANNEL_TEST_EVENT)
        self._attempt_delivery(delivery, actor_subject, now, manual=True)
        self.audit.append("tenant_notification_channel", channel.id, "tenant_notification_channel_tested", actor_subject, {
            "tenant_id": tenant_id, "delivery_id": delivery.id, "status": delivery.status,
            "channel_config_hash": delivery.channel_config_hash, "receipt_verified": bool(delivery.receipt_json.get("verified")),
        })
        self.session.commit()
        self.session.refresh(delivery)
        return {
            "channel_id": channel.id, "passed": delivery.status == "delivered",
            "channel_config_hash": delivery.channel_config_hash, "delivery": self._delivery_view(delivery),
        }

    def list_deliveries(self, tenant_id: str, status: str | None = None, limit: int = 100) -> dict:
        statement = select(TenantNotificationDeliveryRecord).where(
            TenantNotificationDeliveryRecord.tenant_id == tenant_id,
        )
        if status:
            statement = statement.where(TenantNotificationDeliveryRecord.status == status)
        rows = self.session.scalars(statement.order_by(
            TenantNotificationDeliveryRecord.created_at.desc(), TenantNotificationDeliveryRecord.id.desc(),
        ).limit(limit)).all()
        counts = dict(self.session.execute(select(
            TenantNotificationDeliveryRecord.status, func.count(TenantNotificationDeliveryRecord.id),
        ).where(
            TenantNotificationDeliveryRecord.tenant_id == tenant_id,
        ).group_by(TenantNotificationDeliveryRecord.status)).all())
        return {
            "counts": {key: int(counts.get(key, 0)) for key in ("pending", "retry_scheduled", "delivered", "dead_letter", "cancelled")},
            "items": [self._delivery_view(row) for row in rows],
        }

    def delivery_operations(self, tenant_id: str, window_hours: int = 24, now: datetime | None = None) -> dict:
        observed_at = self._as_utc(now or datetime.now(timezone.utc))
        window_start = observed_at - timedelta(hours=window_hours)
        channels = self.session.scalars(select(TenantNotificationChannelRecord).where(
            TenantNotificationChannelRecord.tenant_id == tenant_id,
        ).order_by(TenantNotificationChannelRecord.created_at, TenantNotificationChannelRecord.id)).all()
        deliveries = self.session.scalars(select(TenantNotificationDeliveryRecord).where(
            TenantNotificationDeliveryRecord.tenant_id == tenant_id,
            TenantNotificationDeliveryRecord.created_at >= window_start,
        ).order_by(TenantNotificationDeliveryRecord.created_at.desc())).all()
        business = [row for row in deliveries if row.event_type != CHANNEL_TEST_EVENT]
        attempted = [row for row in business if row.attempt_count > 0]
        delivered = [row for row in business if row.status == "delivered"]
        dead_letters = [row for row in business if row.status == "dead_letter"]
        open_rows = [row for row in business if row.status in {"pending", "retry_scheduled"}]
        retry_due = [row for row in business if row.status == "retry_scheduled" and row.next_attempt_at and self._as_utc(row.next_attempt_at) <= observed_at]
        dead_letter_breaches = [row for row in dead_letters if self._age_seconds(row.updated_at or row.created_at, observed_at) >= DEAD_LETTER_SLA_MINUTES * 60]
        terminal_count = len(delivered) + len(dead_letters)
        delivery_rate = round(len(delivered) / terminal_count, 4) if terminal_count else None
        latencies = sorted(
            self._age_seconds(row.created_at, self._as_utc(row.delivered_at)) * 1000
            for row in delivered if row.created_at and row.delivered_at
        )
        p95_latency_ms = round(latencies[max(0, math.ceil(len(latencies) * 0.95) - 1)], 2) if latencies else None
        oldest_open_seconds = max((self._age_seconds(row.created_at, observed_at) for row in open_rows), default=0)
        latest_dispatch = self.session.scalar(select(AuditEventRecord).where(
            AuditEventRecord.tenant_id == tenant_id,
            AuditEventRecord.aggregate_type == "notification_delivery_dispatch",
        ).order_by(AuditEventRecord.created_at.desc(), AuditEventRecord.id.desc()).limit(1))
        recent_failures = [row for row in attempted if row.last_error][:10]
        per_channel = []
        for channel in channels:
            channel_rows = [row for row in business if row.channel_id == channel.id]
            channel_delivered = sum(row.status == "delivered" for row in channel_rows)
            channel_dead = sum(row.status == "dead_letter" for row in channel_rows)
            channel_terminal = channel_delivered + channel_dead
            latest_failure = next((row for row in channel_rows if row.last_error), None)
            latest_success = next((row for row in channel_rows if row.status == "delivered"), None)
            preflight = self._preflight_view(channel)
            per_channel.append({
                "channel_id": channel.id, "name": channel.name, "status": channel.status,
                "delivery_mode": channel.delivery_mode, "preflight_status": preflight["status"],
                "attempted": sum(row.attempt_count > 0 for row in channel_rows),
                "delivered": channel_delivered, "dead_letter": channel_dead,
                "retry_scheduled": sum(row.status == "retry_scheduled" for row in channel_rows),
                "delivery_rate": round(channel_delivered / channel_terminal, 4) if channel_terminal else None,
                "latest_success_at": latest_success.delivered_at.isoformat() if latest_success and latest_success.delivered_at else None,
                "latest_error": latest_failure.last_error if latest_failure else None,
            })
        active_channels = sum(row.status == "active" for row in channels)
        if not channels:
            health = "not_configured"
        elif dead_letter_breaches:
            health = "incident"
        elif not active_channels or dead_letters or retry_due:
            health = "degraded"
        else:
            health = "healthy"
        return {
            "schema_version": "notification-delivery-operations-v1", "tenant_id": tenant_id,
            "observed_at": observed_at.isoformat(), "window_hours": window_hours, "health": health,
            "sla": {"dead_letter_minutes": DEAD_LETTER_SLA_MINUTES},
            "channels": {"total": len(channels), "active": active_channels, "items": per_channel},
            "deliveries": {
                "created": len(business), "attempted": len(attempted), "delivered": len(delivered),
                "pending": sum(row.status == "pending" for row in business),
                "retry_scheduled": sum(row.status == "retry_scheduled" for row in business),
                "retry_due": len(retry_due), "dead_letter": len(dead_letters),
                "dead_letter_sla_breaches": len(dead_letter_breaches),
                "cancelled": sum(row.status == "cancelled" for row in business),
                "delivery_rate": delivery_rate, "p95_end_to_end_latency_ms": p95_latency_ms,
                "oldest_open_seconds": oldest_open_seconds,
            },
            "last_dispatch_at": latest_dispatch.created_at.isoformat() if latest_dispatch else None,
            "recent_failures": [{
                "delivery_id": row.id, "channel_id": row.channel_id, "status": row.status,
                "status_code": row.last_status_code, "error": row.last_error,
                "attempt_count": row.attempt_count, "occurred_at": (row.updated_at or row.created_at).isoformat(),
            } for row in recent_failures],
        }

    def scan_and_dispatch(self, tenant_id: str, actor_subject: str, limit: int = 100, now: datetime | None = None) -> dict:
        scan_at = self._as_utc(now or datetime.now(timezone.utc))
        channels = self.session.scalars(select(TenantNotificationChannelRecord).where(
            TenantNotificationChannelRecord.tenant_id == tenant_id,
            TenantNotificationChannelRecord.status == "active",
        ).order_by(TenantNotificationChannelRecord.created_at, TenantNotificationChannelRecord.id)).all()
        notifications = self.session.scalars(select(NotificationRecord).where(
            NotificationRecord.tenant_id == tenant_id,
            NotificationRecord.status != "resolved",
        ).order_by(NotificationRecord.created_at, NotificationRecord.id).limit(limit)).all()
        channel_ids = [row.id for row in channels]
        notification_ids = [row.id for row in notifications]
        existing_pairs = set()
        if channel_ids and notification_ids:
            existing_pairs = set(self.session.execute(select(
                TenantNotificationDeliveryRecord.channel_id,
                TenantNotificationDeliveryRecord.notification_id,
            ).where(
                TenantNotificationDeliveryRecord.tenant_id == tenant_id,
                TenantNotificationDeliveryRecord.channel_id.in_(channel_ids),
                TenantNotificationDeliveryRecord.notification_id.in_(notification_ids),
            )).all())
        created = 0
        for notification in notifications:
            for channel in channels:
                if (channel.id, notification.id) in existing_pairs or not self._matches(channel, notification):
                    continue
                self._create_delivery(channel, notification, actor_subject, scan_at)
                created += 1
        due = self.session.scalars(select(TenantNotificationDeliveryRecord).where(
            TenantNotificationDeliveryRecord.tenant_id == tenant_id,
            TenantNotificationDeliveryRecord.status.in_(["pending", "retry_scheduled"]),
            or_(
                TenantNotificationDeliveryRecord.next_attempt_at.is_(None),
                TenantNotificationDeliveryRecord.next_attempt_at <= scan_at,
            ),
        ).order_by(TenantNotificationDeliveryRecord.created_at, TenantNotificationDeliveryRecord.id).limit(limit)).all()
        attempted = delivered = retry_scheduled = dead_letter = 0
        for delivery in due:
            self._attempt_delivery(delivery, actor_subject, scan_at, manual=False)
            attempted += 1
            delivered += int(delivery.status == "delivered")
            retry_scheduled += int(delivery.status == "retry_scheduled")
            dead_letter += int(delivery.status == "dead_letter")
        self.audit.append("notification_delivery_dispatch", f"{tenant_id}:{scan_at.isoformat()}", "tenant_notification_delivery_dispatched", actor_subject, {
            "tenant_id": tenant_id, "channels": len(channels), "notifications_scanned": len(notifications),
            "deliveries_created": created, "attempted": attempted, "delivered": delivered,
            "retry_scheduled": retry_scheduled, "dead_letter": dead_letter,
        })
        self.session.commit()
        return {
            "scanned_at": scan_at.isoformat(), "channels": len(channels), "notifications_scanned": len(notifications),
            "deliveries_created": created, "attempted": attempted, "delivered": delivered,
            "retry_scheduled": retry_scheduled, "dead_letter": dead_letter,
        }

    def retry_delivery(self, tenant_id: str, delivery_id: str, expected_row_version: int, actor_subject: str, redeliver: bool = False) -> dict:
        record = self._delivery(tenant_id, delivery_id)
        if record.row_version != expected_row_version:
            raise NotificationDeliveryError("ROW_VERSION_CONFLICT", "投递记录已变化，请刷新后重试", 409)
        if redeliver:
            if record.status != "dead_letter":
                raise NotificationDeliveryError("REDELIVERY_NOT_ALLOWED", "只有死信记录可以人工重放", 409)
            record.manual_redelivery_count += 1
            record.attempt_count = 0
        elif record.status != "retry_scheduled":
            raise NotificationDeliveryError("RETRY_NOT_ALLOWED", "只有等待重试的记录可以立即重试", 409)
        record.status = "pending"
        record.next_attempt_at = None
        self._attempt_delivery(record, actor_subject, self._as_utc(datetime.now(timezone.utc)), manual=True)
        try:
            self.session.commit()
        except StaleDataError as exc:
            self.session.rollback()
            raise NotificationDeliveryError("CONCURRENT_UPDATE", "投递记录重放发生并发冲突", 409) from exc
        self.session.refresh(record)
        return self._delivery_view(record)

    def _create_delivery(self, channel: TenantNotificationChannelRecord, notification: NotificationRecord, actor_subject: str, now: datetime, event_type: str = "tenant.notification.created") -> TenantNotificationDeliveryRecord:
        channel_snapshot = self._channel_snapshot(channel)
        payload = {
            "schema_version": "tenant-notification-event-v1",
            "event": event_type,
            "tenant_id": notification.tenant_id,
            "notification": {
                "id": notification.id, "category": notification.category, "level": notification.level,
                "severity": notification.severity, "title": notification.title, "message": notification.message,
                "recipient_role": notification.recipient_role, "recipient_subject": notification.recipient_subject,
                "action": deepcopy(notification.action_json or {}),
                "created_at": notification.created_at.isoformat() if notification.created_at else now.isoformat(),
            },
        }
        delivery_id = str(uuid4())
        timestamp = str(int(now.timestamp()))
        signature = self._sign(timestamp, payload, self._resolve_secret(channel.secret_reference, channel.delivery_mode))
        record = TenantNotificationDeliveryRecord(
            id=delivery_id, tenant_id=notification.tenant_id, channel_id=channel.id, notification_id=notification.id,
            idempotency_key=f"notification:{notification.id}:channel:{channel.id}",
            event_type=event_type, endpoint_url=channel.endpoint_url,
            delivery_mode=channel.delivery_mode, secret_reference=channel.secret_reference,
            require_receipt=channel.require_receipt, transport_config_json=channel_snapshot,
            channel_config_hash=content_hash(channel_snapshot), payload_json=payload, payload_hash=content_hash(payload),
            signature_timestamp=timestamp, signature=signature, attempt_count=0, max_attempts=channel.max_attempts,
            status="pending", delivery_history_json=[], receipt_json={}, manual_redelivery_count=0,
        )
        self.session.add(record)
        self.session.flush()
        self.audit.append("tenant_notification_delivery", record.id, "tenant_notification_delivery_created", actor_subject, {
            "tenant_id": record.tenant_id, "notification_id": record.notification_id, "channel_id": record.channel_id,
            "payload_hash": record.payload_hash, "channel_config_hash": record.channel_config_hash,
        })
        return record

    def _attempt_delivery(self, record: TenantNotificationDeliveryRecord, actor_subject: str, now: datetime, manual: bool) -> None:
        history = list(record.delivery_history_json or [])
        attempt_number = record.attempt_count + 1
        status_code: int | None = None
        error: str | None = None
        receipt: dict = {}
        try:
            if record.delivery_mode == "sandbox":
                sequence = list((record.transport_config_json or {}).get("sandbox_status_sequence") or [200])
                status_code = int(sequence[min(record.attempt_count, len(sequence) - 1)])
                receipt = {
                    "verified": 200 <= status_code < 300,
                    "event_id": record.id if 200 <= status_code < 300 else None,
                    "acknowledged_at": now.isoformat() if 200 <= status_code < 300 else None,
                    "mode": "sandbox",
                }
                if not 200 <= status_code < 300:
                    error = f"沙箱端点返回 HTTP {status_code}"
            else:
                headers = {
                    "Content-Type": "application/json",
                    "X-Hengxin-Webhook-Id": record.id,
                    "X-Hengxin-Timestamp": record.signature_timestamp,
                    "X-Hengxin-Signature": f"sha256={record.signature}",
                    "Idempotency-Key": record.idempotency_key,
                }
                response = httpx.post(
                    record.endpoint_url, json=record.payload_json, headers=headers,
                    timeout=float((record.transport_config_json or {}).get("timeout_seconds") or 5),
                    follow_redirects=False,
                )
                status_code = response.status_code
                echoed_event_id = response.headers.get("X-Hengxin-Event-Id")
                verified = not record.require_receipt or echoed_event_id == record.id
                receipt = {
                    "verified": verified, "event_id": echoed_event_id,
                    "acknowledged_at": now.isoformat() if verified and 200 <= status_code < 300 else None,
                    "response_hash": hashlib.sha256(response.content).hexdigest(), "mode": "live",
                }
                if 200 <= status_code < 300 and not verified:
                    error = "端点未返回匹配的 X-Hengxin-Event-Id 回执"
                elif not 200 <= status_code < 300:
                    error = f"端点返回 HTTP {status_code}"
        except Exception as exc:
            error = f"{type(exc).__name__}: {str(exc)[:300]}"
        delivered = status_code is not None and 200 <= status_code < 300 and bool(receipt.get("verified"))
        retryable = status_code is None or status_code in {408, 425, 429} or status_code >= 500 or (200 <= status_code < 300 and not delivered)
        record.attempt_count = attempt_number
        record.last_status_code = status_code
        record.last_error = None if delivered else error or "投递未获得有效回执"
        record.receipt_json = receipt
        history.append({
            "attempt": attempt_number, "attempted_at": now.isoformat(), "status_code": status_code,
            "outcome": "delivered" if delivered else "failed", "manual": manual,
            "receipt_verified": bool(receipt.get("verified")), "error": record.last_error,
        })
        record.delivery_history_json = history
        if delivered:
            record.status = "delivered"
            record.delivered_at = now
            record.next_attempt_at = None
        elif retryable and attempt_number < record.max_attempts:
            record.status = "retry_scheduled"
            record.next_attempt_at = now + timedelta(seconds=min(3600, 30 * (2 ** (attempt_number - 1))))
        else:
            record.status = "dead_letter"
            record.next_attempt_at = None
        self.session.flush()
        self.audit.append("tenant_notification_delivery", record.id, "tenant_notification_delivery_attempted", actor_subject, {
            "tenant_id": record.tenant_id, "attempt": attempt_number, "manual": manual,
            "status": record.status, "status_code": status_code, "receipt_verified": bool(receipt.get("verified")),
            "payload_hash": record.payload_hash, "channel_config_hash": record.channel_config_hash,
        })

    def _validate_channel(self, payload: dict) -> dict:
        mode = payload["delivery_mode"]
        endpoint = payload["endpoint_url"].strip()
        parsed = urlparse(endpoint)
        if mode == "sandbox":
            if parsed.scheme != "sandbox" or not (parsed.netloc or parsed.path):
                raise NotificationDeliveryError("SANDBOX_ENDPOINT_INVALID", "沙箱渠道地址必须使用 sandbox:// 标识")
        else:
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise NotificationDeliveryError("LIVE_ENDPOINT_INVALID", "正式渠道必须使用不含账号信息的 HTTPS 地址")
            self._reject_private_host(parsed.hostname)
        secret_reference = payload["secret_reference"].strip()
        if not SECRET_REFERENCE_PATTERN.fullmatch(secret_reference):
            raise NotificationDeliveryError("SECRET_REFERENCE_INVALID", "密钥必须使用 env:VARIABLE_NAME 引用，不能保存明文")
        if mode == "live" and not os.getenv(secret_reference[4:]):
            raise NotificationDeliveryError("SECRET_NOT_CONFIGURED", "正式渠道引用的环境密钥尚未配置", 409)
        categories = sorted(set(value.strip() for value in payload.get("subscribed_categories", []) if value.strip()))
        roles = sorted(set(value.strip() for value in payload.get("recipient_roles", []) if value.strip()))
        if not categories:
            raise NotificationDeliveryError("CHANNEL_CATEGORIES_REQUIRED", "至少选择一个通知类别")
        sandbox_sequence = [int(value) for value in payload.get("sandbox_status_sequence", [200])]
        if not sandbox_sequence or any(value < 100 or value > 599 for value in sandbox_sequence):
            raise NotificationDeliveryError("SANDBOX_STATUS_INVALID", "沙箱状态序列必须是 100 至 599 的 HTTP 状态码")
        return {
            "name": payload["name"].strip(), "channel_type": "webhook", "delivery_mode": mode,
            "endpoint_url": endpoint, "secret_reference": secret_reference,
            "subscribed_categories_json": categories, "recipient_roles_json": roles,
            "minimum_severity": payload["minimum_severity"], "max_attempts": int(payload["max_attempts"]),
            "timeout_seconds": int(payload["timeout_seconds"]), "require_receipt": bool(payload["require_receipt"]),
            "sandbox_status_sequence_json": sandbox_sequence, "status": payload.get("status", "active"),
        }

    @staticmethod
    def _matches(channel: TenantNotificationChannelRecord, notification: NotificationRecord) -> bool:
        categories = set(channel.subscribed_categories_json or [])
        roles = set(channel.recipient_roles_json or [])
        return (
            ("*" in categories or notification.category in categories)
            and (not roles or notification.recipient_role in roles)
            and SEVERITY_RANK.get(notification.severity, 0) >= SEVERITY_RANK[channel.minimum_severity]
        )

    @staticmethod
    def _resolve_secret(reference: str, mode: str) -> str:
        secret = os.getenv(reference[4:])
        if secret:
            return secret
        if mode == "sandbox":
            return "sandbox-notification-secret"
        raise NotificationDeliveryError("SECRET_NOT_CONFIGURED", "正式渠道引用的环境密钥不可用", 409)

    @staticmethod
    def _sign(timestamp: str, payload: dict, secret: str) -> str:
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hmac.new(secret.encode("utf-8"), f"{timestamp}.{canonical}".encode("utf-8"), hashlib.sha256).hexdigest()

    @staticmethod
    def _reject_private_host(hostname: str) -> None:
        if hostname.lower() in {"localhost", "localhost.localdomain"} or hostname.lower().endswith(".local"):
            raise NotificationDeliveryError("LIVE_ENDPOINT_PRIVATE", "正式渠道不能指向本机或本地域名")
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            return
        if not address.is_global:
            raise NotificationDeliveryError("LIVE_ENDPOINT_PRIVATE", "正式渠道不能指向私网、回环或保留地址")

    def _channel(self, tenant_id: str, channel_id: str) -> TenantNotificationChannelRecord:
        record = self.session.scalar(select(TenantNotificationChannelRecord).where(
            TenantNotificationChannelRecord.tenant_id == tenant_id,
            TenantNotificationChannelRecord.id == channel_id,
        ))
        if record is None:
            raise NotificationDeliveryError("CHANNEL_NOT_FOUND", "通知渠道不存在", 404)
        return record

    def _delivery(self, tenant_id: str, delivery_id: str) -> TenantNotificationDeliveryRecord:
        record = self.session.scalar(select(TenantNotificationDeliveryRecord).where(
            TenantNotificationDeliveryRecord.tenant_id == tenant_id,
            TenantNotificationDeliveryRecord.id == delivery_id,
        ))
        if record is None:
            raise NotificationDeliveryError("DELIVERY_NOT_FOUND", "通知投递记录不存在", 404)
        return record

    def _channel_view(self, record: TenantNotificationChannelRecord) -> dict:
        preflight = self._preflight_view(record)
        return {
            "id": record.id, "tenant_id": record.tenant_id, "name": record.name,
            "channel_type": record.channel_type, "delivery_mode": record.delivery_mode,
            "endpoint_url": record.endpoint_url, "secret_reference": record.secret_reference,
            "subscribed_categories": deepcopy(record.subscribed_categories_json or []),
            "recipient_roles": deepcopy(record.recipient_roles_json or []),
            "minimum_severity": record.minimum_severity, "max_attempts": record.max_attempts,
            "timeout_seconds": record.timeout_seconds, "require_receipt": record.require_receipt,
            "sandbox_status_sequence": deepcopy(record.sandbox_status_sequence_json or []),
            "status": record.status, "created_by": record.created_by, "created_by_name": record.created_by_name,
            "row_version": record.row_version,
            "preflight_status": preflight["status"], "last_test_delivery_id": preflight["delivery_id"],
            "last_tested_at": preflight["tested_at"],
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        }

    def _preflight_view(self, record: TenantNotificationChannelRecord) -> dict:
        if record.delivery_mode != "live":
            return {"status": "not_required", "delivery_id": None, "tested_at": None}
        config_hash = content_hash(self._channel_snapshot(record))
        test = self.session.scalar(select(TenantNotificationDeliveryRecord).where(
            TenantNotificationDeliveryRecord.tenant_id == record.tenant_id,
            TenantNotificationDeliveryRecord.channel_id == record.id,
            TenantNotificationDeliveryRecord.event_type == CHANNEL_TEST_EVENT,
            TenantNotificationDeliveryRecord.channel_config_hash == config_hash,
        ).order_by(TenantNotificationDeliveryRecord.created_at.desc(), TenantNotificationDeliveryRecord.id.desc()).limit(1))
        if not test:
            return {"status": "required", "delivery_id": None, "tested_at": None}
        return {
            "status": "passed" if test.status == "delivered" else "failed",
            "delivery_id": test.id, "tested_at": (test.updated_at or test.created_at).isoformat(),
        }

    def _has_successful_preflight(self, tenant_id: str, channel_id: str, config_hash: str) -> bool:
        return self.session.scalar(select(TenantNotificationDeliveryRecord.id).where(
            TenantNotificationDeliveryRecord.tenant_id == tenant_id,
            TenantNotificationDeliveryRecord.channel_id == channel_id,
            TenantNotificationDeliveryRecord.event_type == CHANNEL_TEST_EVENT,
            TenantNotificationDeliveryRecord.channel_config_hash == config_hash,
            TenantNotificationDeliveryRecord.status == "delivered",
        ).limit(1)) is not None

    @staticmethod
    def _channel_snapshot(record: TenantNotificationChannelRecord) -> dict:
        return {
            "channel_id": record.id, "channel_type": record.channel_type,
            "delivery_mode": record.delivery_mode, "endpoint_url": record.endpoint_url,
            "secret_reference": record.secret_reference, "require_receipt": record.require_receipt,
            "timeout_seconds": record.timeout_seconds,
            "sandbox_status_sequence": list(record.sandbox_status_sequence_json or [200]),
        }

    @staticmethod
    def _channel_snapshot_from_config(channel_id: str, config: dict) -> dict:
        return {
            "channel_id": channel_id, "channel_type": config["channel_type"],
            "delivery_mode": config["delivery_mode"], "endpoint_url": config["endpoint_url"],
            "secret_reference": config["secret_reference"], "require_receipt": config["require_receipt"],
            "timeout_seconds": config["timeout_seconds"],
            "sandbox_status_sequence": list(config["sandbox_status_sequence_json"] or [200]),
        }

    @staticmethod
    def _delivery_view(record: TenantNotificationDeliveryRecord) -> dict:
        return {
            "id": record.id, "tenant_id": record.tenant_id, "channel_id": record.channel_id,
            "notification_id": record.notification_id, "idempotency_key": record.idempotency_key,
            "event_type": record.event_type, "endpoint_url": record.endpoint_url,
            "delivery_mode": record.delivery_mode, "secret_reference": record.secret_reference,
            "payload": deepcopy(record.payload_json), "payload_hash": record.payload_hash,
            "channel_config_hash": record.channel_config_hash, "signature_timestamp": record.signature_timestamp,
            "signature": record.signature,
            "signature_headers": {
                "X-Hengxin-Webhook-Id": record.id, "X-Hengxin-Timestamp": record.signature_timestamp,
                "X-Hengxin-Signature": f"sha256={record.signature}", "Idempotency-Key": record.idempotency_key,
            },
            "attempt_count": record.attempt_count, "max_attempts": record.max_attempts,
            "status": record.status, "last_status_code": record.last_status_code, "last_error": record.last_error,
            "next_attempt_at": record.next_attempt_at.isoformat() if record.next_attempt_at else None,
            "history": deepcopy(record.delivery_history_json or []), "receipt": deepcopy(record.receipt_json or {}),
            "manual_redelivery_count": record.manual_redelivery_count,
            "delivered_at": record.delivered_at.isoformat() if record.delivered_at else None,
            "row_version": record.row_version,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        }

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    @classmethod
    def _age_seconds(cls, started_at: datetime, ended_at: datetime) -> float:
        return max(0.0, (cls._as_utc(ended_at) - cls._as_utc(started_at)).total_seconds())
