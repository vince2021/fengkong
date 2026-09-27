"""Auditable batch decision jobs, sandbox webhooks, and integration governance."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from collections import defaultdict, deque
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import Lock
from time import monotonic
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.counterparty_repository import CounterpartyRepository
from backend.db_models import DecisionJobRecord, DecisionWebhookDeliveryRecord
from backend.decision_api import DecisionApiError, execute_decision
from backend.repository import AuditRepository, DemoRepository, ModelGovernanceRepository, content_hash
from backend.schemas import DecisionFieldMappingPreview, DecisionJobCreate
from backend.security import Principal
from backend.tenant_asset_repository import TenantAssetError, TenantAssetRepository
from backend.tenant_runtime_assets import TenantRuntimeAssetResolver
from backend.tenant_registry import TenantRegistry


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, client_id: str, limit: int, now: float | None = None) -> None:
        current = monotonic() if now is None else now
        with self._lock:
            events = self._events[client_id]
            while events and current - events[0] >= 1:
                events.popleft()
            if len(events) >= limit:
                raise DecisionApiError(
                    "RATE_LIMIT_EXCEEDED", "客户端 QPS 已达到接入配额", 429,
                    {"limit_type": "qps", "limit": limit, "retry_after_seconds": 1},
                )
            events.append(current)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


job_rate_limiter = SlidingWindowLimiter()


def client_profile(principal: Principal, session: Session) -> dict:
    profile = TenantRegistry(session).client_profile(principal.tenant_id, principal.client_id)
    profile.update(
        {
            "environment": "sandbox",
            "production_secret_exposed": False,
            "authentication": "Bearer token (development identity only)",
            "signature_algorithm": "HMAC-SHA256",
            "signature_input": "timestamp.canonical_json_body",
            "signature_headers": ["X-Hengxin-Webhook-Id", "X-Hengxin-Timestamp", "X-Hengxin-Signature"],
        }
    )
    return profile


class DecisionJobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit = AuditRepository(session)

    def create(self, request: DecisionJobCreate, principal: Principal, demo_repository: DemoRepository) -> tuple[dict, bool]:
        profile = client_profile(principal, self.session)
        job_rate_limiter.check(f"{profile['tenant_id']}:{profile['client_id']}", profile["qps_limit"])
        canonical = request.model_dump(mode="json", exclude_none=False)
        request_hash = content_hash(canonical)
        existing = self.session.scalars(
            select(DecisionJobRecord).where(
                DecisionJobRecord.tenant_id == profile["tenant_id"],
                DecisionJobRecord.job_key == request.job_key,
            )
        ).first()
        if existing:
            if existing.request_hash != request_hash:
                raise DecisionApiError(
                    "IDEMPOTENCY_CONFLICT", "job_key 已被不同批次请求占用", 409,
                    {"job_key": request.job_key, "original_request_hash": existing.request_hash, "incoming_request_hash": request_hash},
                )
            return serialize_job(existing, idempotent=True), True

        self._check_capacity(profile, len(request.requests))
        resolver = TenantRuntimeAssetResolver(TenantAssetRepository(self.session), demo_repository)
        frozen_items = []
        try:
            for item in request.requests:
                selection = item.assets
                frozen_items.append({
                    "request_id": item.request_id,
                    "assets": resolver.resolve_routed_graph(
                        principal.tenant_id, selection.model_key,
                        item.counterparty_id or str((item.input or {}).get("id") or item.request_id),
                        "decision_job", f"{request.job_key}:{item.request_id}",
                        model_version=selection.model_version,
                        pipeline_code=selection.pipeline_code,
                        pipeline_version=selection.pipeline_version,
                        rule_set_versions=selection.rule_set_versions,
                        rule_versions=selection.rule_versions,
                    ),
                })
        except TenantAssetError as exc:
            raise DecisionApiError(exc.code, exc.message, exc.status_code, exc.details) from exc
        asset_snapshot = {
            "schema_version": "tenant-runtime-assets-v1",
            "capture_status": "frozen_at_queue",
            "items": frozen_items,
        }
        asset_snapshot["resolution_hash"] = content_hash([
            {"request_id": item["request_id"], "resolution_hash": item["assets"]["resolution_hash"]}
            for item in frozen_items
        ])
        assets_hash = content_hash(asset_snapshot)
        callback = deepcopy(canonical["callback"])
        callback.pop("simulate_status_sequence", None)
        callback["simulation_plan_hash"] = content_hash(request.callback.simulate_status_sequence)
        record = DecisionJobRecord(
            id=str(uuid4()), job_key=request.job_key, request_hash=request_hash,
            tenant_id=profile["tenant_id"], client_id=profile["client_id"], status="queued",
            total_count=len(request.requests), succeeded_count=0, failed_count=0,
            request_json=canonical, results_json=[], failures_json=[], callback_json=callback,
            asset_snapshot_json=asset_snapshot, assets_hash=assets_hash,
            created_by=principal.subject, created_by_name=principal.name,
        )
        self.session.add(record)
        try:
            self.session.flush()
            self.audit.append(
                "decision_job", record.id, "decision_job_queued", principal.subject,
                {"job_key": record.job_key, "tenant_id": record.tenant_id, "total_count": record.total_count, "request_hash": record.request_hash, "assets_hash": assets_hash, "asset_resolution_hash": asset_snapshot["resolution_hash"]},
            )
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            existing = self.session.scalars(
                select(DecisionJobRecord).where(
                    DecisionJobRecord.tenant_id == profile["tenant_id"],
                    DecisionJobRecord.job_key == request.job_key,
                )
            ).first()
            if existing and existing.request_hash == request_hash:
                return serialize_job(existing, idempotent=True), True
            if existing:
                raise DecisionApiError(
                    "IDEMPOTENCY_CONFLICT", "job_key 已被不同批次请求占用", 409,
                    {"job_key": request.job_key, "original_request_hash": existing.request_hash, "incoming_request_hash": request_hash},
                )
            raise
        self.session.refresh(record)
        return serialize_job(record), False

    def _check_capacity(self, profile: dict, requested_count: int) -> None:
        running = self.session.scalar(
            select(func.count(DecisionJobRecord.id)).where(
                DecisionJobRecord.tenant_id == profile["tenant_id"], DecisionJobRecord.status == "running"
            )
        ) or 0
        if running >= profile["concurrent_job_limit"]:
            raise DecisionApiError(
                "RATE_LIMIT_EXCEEDED", "并行批量任务数已达到接入配额", 429,
                {"limit_type": "concurrent_jobs", "limit": profile["concurrent_job_limit"], "retry_after_seconds": 5},
            )
        today = datetime.now(timezone.utc).date().isoformat()
        used = self.session.scalar(
            select(func.coalesce(func.sum(DecisionJobRecord.total_count), 0)).where(
                DecisionJobRecord.tenant_id == profile["tenant_id"],
                func.date(DecisionJobRecord.created_at) == today,
            )
        ) or 0
        if used + requested_count > profile["daily_item_quota"]:
            raise DecisionApiError(
                "RATE_LIMIT_EXCEEDED", "当日决策笔数将超过接入配额", 429,
                {"limit_type": "daily_items", "limit": profile["daily_item_quota"], "used": int(used), "requested": requested_count, "retry_after_seconds": 3600},
            )

    def get(self, job_id: str, principal: Principal) -> DecisionJobRecord:
        record = self.session.get(DecisionJobRecord, job_id)
        if record is None:
            raise DecisionApiError("DECISION_JOB_NOT_FOUND", "批量决策任务不存在", 404, {"job_id": job_id})
        if not _can_access_tenant(principal, record.tenant_id):
            raise DecisionApiError("DECISION_JOB_NOT_FOUND", "批量决策任务不存在", 404, {"job_id": job_id})
        return record

    def list(self, principal: Principal, limit: int = 50) -> list[dict]:
        statement = (
            select(DecisionJobRecord)
            .where(DecisionJobRecord.tenant_id == principal.tenant_id)
            .order_by(DecisionJobRecord.created_at.desc())
            .limit(limit)
        )
        return [serialize_job(row) for row in self.session.scalars(statement).all()]

    def run(
        self,
        job_id: str,
        principal: Principal,
        demo_repository: DemoRepository,
        counterparty_repository: CounterpartyRepository,
        governance: ModelGovernanceRepository,
    ) -> dict:
        record = self.get(job_id, principal)
        if record.status in {"completed", "completed_with_errors"}:
            return serialize_job(record, idempotent=True)
        if record.status == "running":
            raise DecisionApiError("DECISION_JOB_ALREADY_RUNNING", "批量任务正在执行", 409, {"job_id": job_id})
        if content_hash(record.asset_snapshot_json) != record.assets_hash:
            raise DecisionApiError("ASSET_INTEGRITY_FAILED", "批量任务冻结资产快照哈希不一致", 409, {"job_id": record.id})

        record.status = "running"
        record.started_at = datetime.now(timezone.utc)
        self.session.commit()
        results: list[dict] = []
        failures: list[dict] = []
        requests = DecisionJobCreate.model_validate(record.request_json).requests
        frozen_by_request = {
            item["request_id"]: item["assets"]
            for item in record.asset_snapshot_json.get("items", [])
        }
        for index, request in enumerate(requests):
            try:
                frozen_assets = frozen_by_request.get(request.request_id)
                if frozen_assets is None:
                    raise DecisionApiError("ASSET_SNAPSHOT_MISSING", "批量任务缺少请求对应的冻结资产快照", 409, {"request_id": request.request_id})
                response, item_idempotent = execute_decision(
                    request, self.session, demo_repository, counterparty_repository, governance, principal, frozen_assets=frozen_assets
                )
                results.append(
                    {
                        "index": index, "request_id": request.request_id, "counterparty_id": response["counterparty_id"],
                        "rating": response["decision"].get("rating"), "final_admission": response["decision"].get("final_admission"),
                        "total_score": response["decision"].get("total_score"), "trace_id": response["trace_id"],
                        "evidence_hash": response["evidence"]["evidence_hash"], "idempotent": item_idempotent,
                    }
                )
            except DecisionApiError as exc:
                self.session.rollback()
                failures.append(
                    {"index": index, "request_id": request.request_id, "code": exc.code, "message": exc.message, "details": exc.details}
                )
            except Exception:
                self.session.rollback()
                failures.append(
                    {"index": index, "request_id": request.request_id, "code": "DECISION_EXECUTION_FAILED", "message": "决策执行发生未预期错误", "details": {}}
                )

        record = self.get(job_id, principal)
        completed_at = datetime.now(timezone.utc)
        record.results_json = results
        record.failures_json = failures
        record.succeeded_count = len(results)
        record.failed_count = len(failures)
        record.status = "completed" if not failures else "completed_with_errors" if results else "failed"
        record.completed_at = completed_at
        record.result_hash = content_hash({"results": results, "failures": failures})
        record.evidence_hash = content_hash(
            {"job_id": record.id, "request_hash": record.request_hash, "assets_hash": record.assets_hash, "result_hash": record.result_hash, "completed_at": completed_at.isoformat()}
        )
        self.audit.append(
            "decision_job", record.id, "decision_job_completed", principal.subject,
            {"status": record.status, "succeeded_count": len(results), "failed_count": len(failures), "assets_hash": record.assets_hash, "asset_resolution_hash": record.asset_snapshot_json.get("resolution_hash"), "result_hash": record.result_hash, "evidence_hash": record.evidence_hash},
        )
        self.session.commit()
        self.session.refresh(record)
        if record.request_json.get("callback", {}).get("mode") == "sandbox":
            self._create_and_attempt_webhook(record, principal)
        return serialize_job(record)

    def _create_and_attempt_webhook(self, job: DecisionJobRecord, principal: Principal) -> None:
        callback = job.request_json["callback"]
        payload = {
            "event": "decision.job.completed", "job_id": job.id, "job_key": job.job_key,
            "tenant_id": job.tenant_id, "client_id": job.client_id,
            "status": job.status, "total_count": job.total_count, "succeeded_count": job.succeeded_count,
            "failed_count": job.failed_count, "result_hash": job.result_hash, "evidence_hash": job.evidence_hash,
        }
        timestamp = str(int(datetime.now(timezone.utc).timestamp()))
        delivery = DecisionWebhookDeliveryRecord(
            id=str(uuid4()), job_id=job.id, event_type="decision.job.completed",
            endpoint_url=callback["endpoint_url"], secret_reference=callback["secret_reference"],
            payload_json=payload, payload_hash=content_hash(payload), signature_timestamp=timestamp,
            signature=sign_webhook(timestamp, payload, callback["secret_reference"]),
            attempt_count=0, max_attempts=callback["max_attempts"], status="pending",
            delivery_history_json=[], manual_redelivery_count=0,
        )
        self.session.add(delivery)
        self.session.flush()
        self._attempt_delivery(delivery, callback.get("simulate_status_sequence", [200]), principal, manual=False)

    def retry_webhook(self, delivery_id: str, principal: Principal, redeliver: bool = False) -> dict:
        delivery = self.session.get(DecisionWebhookDeliveryRecord, delivery_id)
        if delivery is None:
            raise DecisionApiError("WEBHOOK_DELIVERY_NOT_FOUND", "Webhook 投递记录不存在", 404, {"delivery_id": delivery_id})
        job = self.get(delivery.job_id, principal)
        if redeliver:
            if delivery.status != "dead_letter":
                raise DecisionApiError("WEBHOOK_REDELIVERY_NOT_ALLOWED", "只有死信记录可以人工补发", 409, {"status": delivery.status})
            delivery.manual_redelivery_count += 1
            delivery.attempt_count = 0
            delivery.status = "pending"
            delivery.next_attempt_at = None
        elif delivery.status != "retry_scheduled":
            raise DecisionApiError("WEBHOOK_RETRY_NOT_ALLOWED", "当前投递状态不允许重试", 409, {"status": delivery.status})
        callback = job.request_json.get("callback", {})
        self._attempt_delivery(delivery, callback.get("simulate_status_sequence", [200]), principal, manual=redeliver)
        return serialize_webhook(delivery)

    def _attempt_delivery(self, delivery: DecisionWebhookDeliveryRecord, sequence: list[int], principal: Principal, manual: bool) -> None:
        now = datetime.now(timezone.utc)
        history = list(delivery.delivery_history_json or [])
        status_code = sequence[min(len(history), len(sequence) - 1)]
        delivery.attempt_count += 1
        delivered = 200 <= status_code < 300
        history.append(
            {
                "attempt": delivery.attempt_count, "attempted_at": now.isoformat(), "status_code": status_code,
                "outcome": "delivered" if delivered else "failed", "manual": manual,
            }
        )
        delivery.delivery_history_json = history
        delivery.last_status_code = status_code
        delivery.last_error = None if delivered else f"沙箱端点返回 HTTP {status_code}"
        if delivered:
            delivery.status = "delivered"
            delivery.delivered_at = now
            delivery.next_attempt_at = None
        elif delivery.attempt_count >= delivery.max_attempts:
            delivery.status = "dead_letter"
            delivery.next_attempt_at = None
        else:
            delivery.status = "retry_scheduled"
            delivery.next_attempt_at = now + timedelta(seconds=30 * (2 ** (delivery.attempt_count - 1)))
        self.audit.append(
            "decision_webhook", delivery.id, "decision_webhook_attempted", principal.subject,
            {"job_id": delivery.job_id, "attempt_count": delivery.attempt_count, "status": delivery.status, "status_code": status_code, "payload_hash": delivery.payload_hash, "signature": delivery.signature},
        )
        self.session.commit()
        self.session.refresh(delivery)

    def list_webhooks(self, job_id: str, principal: Principal) -> list[dict]:
        self.get(job_id, principal)
        rows = self.session.scalars(
            select(DecisionWebhookDeliveryRecord).where(DecisionWebhookDeliveryRecord.job_id == job_id).order_by(DecisionWebhookDeliveryRecord.created_at)
        ).all()
        return [serialize_webhook(row) for row in rows]


def sign_webhook(timestamp: str, payload: dict, secret_reference: str) -> str:
    secret = os.getenv("DECISION_WEBHOOK_SECRET", "sandbox-integration-secret")
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    message = f"{timestamp}.{canonical}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def serialize_job(record: DecisionJobRecord, idempotent: bool = False) -> dict:
    return {
        "id": record.id, "job_key": record.job_key, "tenant_id": record.tenant_id, "client_id": record.client_id,
        "status": record.status, "total_count": record.total_count, "succeeded_count": record.succeeded_count,
        "failed_count": record.failed_count, "results": deepcopy(record.results_json or []),
        "failures": deepcopy(record.failures_json or []), "callback": deepcopy(record.callback_json or {}),
        "asset_resolution": {
            "schema_version": record.asset_snapshot_json.get("schema_version"),
            "capture_status": record.asset_snapshot_json.get("capture_status"),
            "item_count": len(record.asset_snapshot_json.get("items", [])),
            "resolution_hash": record.asset_snapshot_json.get("resolution_hash"),
        },
        "evidence": {"request_hash": record.request_hash, "assets_hash": record.assets_hash, "result_hash": record.result_hash, "evidence_hash": record.evidence_hash},
        "idempotent": idempotent, "started_at": _iso(record.started_at), "completed_at": _iso(record.completed_at),
        "created_by": record.created_by, "created_by_name": record.created_by_name,
        "row_version": record.row_version, "created_at": _iso(record.created_at),
    }


def serialize_webhook(record: DecisionWebhookDeliveryRecord) -> dict:
    return {
        "id": record.id, "job_id": record.job_id, "event_type": record.event_type,
        "endpoint_url": record.endpoint_url, "secret_reference": record.secret_reference,
        "payload": deepcopy(record.payload_json), "payload_hash": record.payload_hash,
        "signature_timestamp": record.signature_timestamp, "signature": record.signature,
        "signature_headers": {
            "X-Hengxin-Webhook-Id": record.id,
            "X-Hengxin-Timestamp": record.signature_timestamp,
            "X-Hengxin-Signature": f"sha256={record.signature}",
        },
        "attempt_count": record.attempt_count, "max_attempts": record.max_attempts,
        "status": record.status, "last_status_code": record.last_status_code, "last_error": record.last_error,
        "next_attempt_at": _iso(record.next_attempt_at), "history": deepcopy(record.delivery_history_json or []),
        "manual_redelivery_count": record.manual_redelivery_count, "delivered_at": _iso(record.delivered_at),
        "created_at": _iso(record.created_at), "updated_at": _iso(record.updated_at),
    }


def preview_field_mapping(request: DecisionFieldMappingPreview) -> dict:
    normalized: dict = {}
    transformations: list[dict] = []
    errors: list[dict] = []
    required_targets = {"id", "name", "counterparty_type"}
    required_targets.update(item.target_path for item in request.mappings if item.required)
    mapped_targets: set[str] = set()
    for item in request.mappings:
        value, found = _read_path(request.source, item.source_field)
        operation: list[str] = []
        if not found or value is None or value == "":
            if item.default_value is None:
                if item.required or item.target_path in required_targets:
                    errors.append({"source_field": item.source_field, "target_path": item.target_path, "code": "REQUIRED_SOURCE_MISSING", "message": "必填源字段缺失且未配置默认值"})
                continue
            value = deepcopy(item.default_value)
            operation.append("default")
        if item.enum_mapping:
            key = str(value)
            if key not in item.enum_mapping:
                errors.append({"source_field": item.source_field, "target_path": item.target_path, "code": "ENUM_VALUE_UNMAPPED", "message": f"枚举值 {key} 未配置映射"})
                continue
            value = item.enum_mapping[key]
            operation.append("enum")
        if item.multiplier != 1:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                errors.append({"source_field": item.source_field, "target_path": item.target_path, "code": "NUMERIC_CONVERSION_FAILED", "message": "倍率换算仅支持数值"})
                continue
            value *= item.multiplier
            operation.append(f"multiply:{item.multiplier:g}")
        _write_path(normalized, item.target_path, value)
        mapped_targets.add(item.target_path)
        transformations.append(
            {"source_field": item.source_field, "target_path": item.target_path, "operations": operation or ["copy"], "output_value": value}
        )
    missing_required = sorted(required_targets - mapped_targets)
    for target in missing_required:
        if not any(error["target_path"] == target for error in errors):
            errors.append({"source_field": None, "target_path": target, "code": "REQUIRED_TARGET_MISSING", "message": "必填目标字段未完成映射"})
    required_count = len(required_targets)
    covered = required_count - len(missing_required)
    return {
        "status": "ready" if not errors else "blocked",
        "normalized_input": normalized,
        "coverage": {"required_count": required_count, "mapped_required_count": covered, "coverage_rate": round(covered / required_count, 4) if required_count else 1},
        "missing_required": missing_required, "transformations": transformations, "errors": errors,
        "preview_hash": content_hash({"normalized_input": normalized, "transformations": transformations, "errors": errors}),
    }


def _read_path(source: dict, path: str) -> tuple[object, bool]:
    value: object = source
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None, False
        value = value[part]
    return value, True


def _write_path(target: dict, path: str, value: object) -> None:
    parts = path.split(".")
    current = target
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


def _can_access_tenant(principal: Principal, tenant_id: str) -> bool:
    return principal.tenant_id == tenant_id


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
