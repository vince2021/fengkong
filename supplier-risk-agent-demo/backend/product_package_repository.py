"""Governed product packages, tenant entitlement ledger, and activation controls."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from backend.db_models import (
    ApiClientRecord,
    NotificationRecord,
    ProductPackageRecord,
    TenantAssetBindingRecord,
    TenantEntitlementLifecycleRunRecord,
    TenantEntitlementRecord,
    TenantRecord,
)
from backend.repository import AuditRepository, NotificationRepository, PLATFORM_INTERNAL_TENANT_ID, content_hash
from backend.tenant_asset_repository import TenantAssetError, TenantAssetRepository

if TYPE_CHECKING:
    from backend.security import Principal


DEFAULT_ENTITLEMENT_SCAN_INTERVAL_MINUTES = 5


class ProductPackageError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class ProductPackageRepository:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit = AuditRepository(session)
        self.assets = TenantAssetRepository(session)

    def list_packages(self, status: str | None = None) -> list[dict]:
        statement = select(ProductPackageRecord)
        if status:
            statement = statement.where(ProductPackageRecord.status == status)
        rows = self.session.scalars(statement.order_by(ProductPackageRecord.code, ProductPackageRecord.version.desc())).all()
        return [self._package_view(row) for row in rows]

    def create_package(self, payload: dict, principal: "Principal") -> dict:
        assets = self._validate_assets(payload["assets"])
        version = int(self.session.scalar(
            select(func.max(ProductPackageRecord.version)).where(ProductPackageRecord.code == payload["code"])
        ) or 0) + 1
        snapshot = self._package_config(payload, assets)
        record = ProductPackageRecord(
            id=str(uuid4()), code=payload["code"], version=version, name=payload["name"],
            description=payload["description"], status="draft", is_active=False,
            environment_scopes_json=list(payload["environment_scopes"]), asset_catalog_json=assets,
            quotas_json=deepcopy(payload["quotas"]), expiry_policy=payload["expiry_policy"],
            config_hash=content_hash(snapshot), change_reason=payload["reason"],
            created_by=principal.subject, created_by_name=principal.name,
        )
        self.session.add(record)
        return self._commit_new(record, "product_package", "product_package_created", principal, payload["reason"], self._package_snapshot)

    def submit_package(self, package_id: str, payload: dict, principal: "Principal") -> dict:
        record = self._package(package_id)
        self._check(record.row_version, payload["expected_row_version"], "产品包")
        if record.status not in {"draft", "rejected"}:
            raise ProductPackageError("PACKAGE_STATUS_INVALID", "只有草稿或已驳回产品包可以提交复核", 409)
        before = self._package_snapshot(record)
        record.status = "pending_review"
        record.submitted_at = self._now()
        record.reviewed_by = record.reviewed_by_name = record.review_comment = None
        record.reviewed_at = None
        record.change_reason = payload["reason"]
        return self._commit_change(record, "product_package", "product_package_submitted", principal, payload["reason"], before, self._package_snapshot)

    def review_package(self, package_id: str, payload: dict, principal: "Principal") -> dict:
        record = self._package(package_id)
        self._check(record.row_version, payload["expected_row_version"], "产品包")
        if record.status != "pending_review":
            raise ProductPackageError("PACKAGE_STATUS_INVALID", "只有待复核产品包可以审核", 409)
        if record.created_by == principal.subject:
            raise ProductPackageError("FOUR_EYES_REQUIRED", "创建人与产品包复核人必须为不同人员", 409)
        before = self._package_snapshot(record)
        now = self._now()
        record.reviewed_by = principal.subject
        record.reviewed_by_name = principal.name
        record.reviewed_at = now
        record.review_comment = payload["comment"]
        if payload["decision"] == "reject":
            record.status = "rejected"
            event = "product_package_rejected"
        else:
            active_rows = self.session.scalars(select(ProductPackageRecord).where(
                ProductPackageRecord.code == record.code,
                ProductPackageRecord.is_active.is_(True),
            )).all()
            for active in active_rows:
                if active.id != record.id:
                    active.status = "retired"
                    active.is_active = False
            self.session.flush()
            record.status = "published"
            record.is_active = True
            record.published_at = now
            event = "product_package_published"
        return self._commit_change(record, "product_package", event, principal, payload["comment"], before, self._package_snapshot)

    def list_entitlements(self, tenant_id: str | None = None, status: str | None = None) -> list[dict]:
        statement = select(TenantEntitlementRecord)
        if tenant_id:
            statement = statement.where(TenantEntitlementRecord.tenant_id == tenant_id)
        if status:
            statement = statement.where(TenantEntitlementRecord.status == status)
        rows = self.session.scalars(statement.order_by(TenantEntitlementRecord.created_at.desc())).all()
        return [self._entitlement_view(row) for row in rows]

    def preview_entitlement(self, payload: dict) -> dict:
        tenant = self.session.get(TenantRecord, payload["tenant_id"])
        if tenant is None:
            raise ProductPackageError("TENANT_NOT_FOUND", "租户不存在", 404)
        package = self._published_package(payload["product_package_id"])
        quotas = self._effective_quotas(package.quotas_json, payload.get("quota_overrides"))
        if len(package.asset_catalog_json) > quotas["max_asset_bindings"]:
            raise ProductPackageError("ASSET_QUOTA_EXCEEDED", "产品包资产数量超过本次授权的资产配额", 422)
        if self._as_utc(payload["expires_at"]) <= self._now():
            raise ProductPackageError("ENTITLEMENT_EXPIRED", "授权结束时间必须晚于当前时间", 422)
        existing = self.session.scalars(select(TenantAssetBindingRecord).where(
            TenantAssetBindingRecord.tenant_id == tenant.id
        )).all()
        existing_map = {(item.asset_type, item.asset_code): item for item in existing}
        desired = {(item["asset_type"], item["asset_code"]): item for item in package.asset_catalog_json}
        creates = [deepcopy(item) for key, item in desired.items() if key not in existing_map]
        updates = [
            {**deepcopy(item), "current_status": existing_map[key].status}
            for key, item in desired.items()
            if key in existing_map and self._binding_differs(existing_map[key], item)
        ]
        suspends = [
            {"asset_type": item.asset_type, "asset_code": item.asset_code}
            for key, item in existing_map.items() if key not in desired and item.status == "active"
        ]
        warnings: list[str] = []
        current = self._current_entitlement(tenant.id)
        if current:
            warnings.append(f"激活后将替代授权 {current.package_code} v{current.package_version}")
        if payload["starts_at"] > self._now():
            warnings.append("授权将在开始时间到达后才允许激活")
        preview = {
            "tenant_id": tenant.id, "package_code": package.code, "package_version": package.version,
            "package_config_hash": package.config_hash, "effective_quotas": quotas,
            "assets_to_create": creates, "assets_to_update": updates, "assets_to_suspend": suspends,
            "clients_to_update": int(self.session.scalar(select(func.count(ApiClientRecord.id)).where(ApiClientRecord.tenant_id == tenant.id)) or 0),
            "warnings": warnings,
        }
        preview["preview_hash"] = content_hash(preview)
        return preview

    def create_entitlement(self, payload: dict, principal: "Principal") -> dict:
        preview = self.preview_entitlement(payload)
        package = self._published_package(payload["product_package_id"])
        package_snapshot = self._package_config_from_record(package)
        record = TenantEntitlementRecord(
            id=str(uuid4()), tenant_id=payload["tenant_id"], product_package_id=package.id,
            package_code=package.code, package_version=package.version, package_config_hash=package.config_hash,
            package_snapshot_json=package_snapshot, effective_quotas_json=preview["effective_quotas"],
            initialized_assets_json=[], status="draft", starts_at=payload["starts_at"], expires_at=payload["expires_at"],
            change_reason=payload["reason"], created_by=principal.subject, created_by_name=principal.name,
        )
        self.session.add(record)
        return self._commit_new(record, "tenant_entitlement", "tenant_entitlement_created", principal, payload["reason"], self._entitlement_snapshot)

    def submit_entitlement(self, entitlement_id: str, payload: dict, principal: "Principal") -> dict:
        record = self._entitlement(entitlement_id)
        self._check(record.row_version, payload["expected_row_version"], "租户授权")
        if record.status != "draft":
            raise ProductPackageError("ENTITLEMENT_STATUS_INVALID", "只有草稿授权可以提交复核", 409)
        if self._as_utc(record.expires_at) <= self._now():
            raise ProductPackageError("ENTITLEMENT_EXPIRED", "授权结束时间已过，不能提交复核", 409)
        before = self._entitlement_snapshot(record)
        record.status = "pending_review"
        record.submitted_at = self._now()
        record.change_reason = payload["reason"]
        return self._commit_change(record, "tenant_entitlement", "tenant_entitlement_submitted", principal, payload["reason"], before, self._entitlement_snapshot)

    def review_entitlement(self, entitlement_id: str, payload: dict, principal: "Principal") -> dict:
        record = self._entitlement(entitlement_id)
        self._check(record.row_version, payload["expected_row_version"], "租户授权")
        if record.status != "pending_review":
            raise ProductPackageError("ENTITLEMENT_STATUS_INVALID", "只有待复核授权可以审核", 409)
        if record.created_by == principal.subject:
            raise ProductPackageError("FOUR_EYES_REQUIRED", "授权申请人与复核人必须为不同人员", 409)
        if content_hash(record.package_snapshot_json) != record.package_config_hash:
            raise ProductPackageError("PACKAGE_SNAPSHOT_INTEGRITY_FAILED", "授权中的产品包快照哈希不一致", 409)
        before = self._entitlement_snapshot(record)
        now = self._now()
        record.reviewed_by = principal.subject
        record.reviewed_by_name = principal.name
        record.reviewed_at = now
        record.review_comment = payload["comment"]
        if payload["decision"] == "reject":
            record.status = "terminated"
            record.terminated_at = now
            event = "tenant_entitlement_rejected"
        elif self._as_utc(record.starts_at) > now:
            record.status = "scheduled"
            event = "tenant_entitlement_scheduled"
        else:
            self._activate(record, principal, payload["comment"])
            event = "tenant_entitlement_activated"
        return self._commit_change(record, "tenant_entitlement", event, principal, payload["comment"], before, self._entitlement_snapshot)

    def change_entitlement_status(self, entitlement_id: str, payload: dict, principal: "Principal") -> dict:
        record = self._entitlement(entitlement_id)
        self._check(record.row_version, payload["expected_row_version"], "租户授权")
        before = self._entitlement_snapshot(record)
        now = self._now()
        action = payload["action"]
        if action == "activate":
            if record.status not in {"scheduled", "suspended"}:
                raise ProductPackageError("ENTITLEMENT_STATUS_INVALID", "只有已排期或已暂停授权可以激活", 409)
            if self._as_utc(record.starts_at) > now:
                raise ProductPackageError("ENTITLEMENT_NOT_STARTED", "授权尚未到开始时间", 409)
            self._activate(record, principal, payload["reason"])
            event = "tenant_entitlement_activated"
        elif action == "suspend":
            if record.status != "active":
                raise ProductPackageError("ENTITLEMENT_STATUS_INVALID", "只有生效授权可以暂停", 409)
            record.status = "suspended"
            record.suspended_at = now
            event = "tenant_entitlement_suspended"
        else:
            if record.status in {"terminated", "expired"}:
                raise ProductPackageError("ENTITLEMENT_STATUS_INVALID", "授权已经结束", 409)
            record.status = "terminated"
            record.terminated_at = now
            event = "tenant_entitlement_terminated"
        record.change_reason = payload["reason"]
        return self._commit_change(record, "tenant_entitlement", event, principal, payload["reason"], before, self._entitlement_snapshot)

    def list_entitlement_lifecycle_runs(self, limit: int = 100) -> list[dict]:
        rows = self.session.scalars(
            select(TenantEntitlementLifecycleRunRecord)
            .order_by(TenantEntitlementLifecycleRunRecord.created_at.desc())
            .limit(limit)
        ).all()
        return [self._lifecycle_run_view(row) for row in rows]

    def entitlement_lifecycle_status(self, now: datetime | None = None) -> dict:
        observed_at = self._as_utc(now or self._now())
        latest = self.session.scalars(
            select(TenantEntitlementLifecycleRunRecord)
            .where(TenantEntitlementLifecycleRunRecord.trigger_type == "scheduler")
            .order_by(TenantEntitlementLifecycleRunRecord.scan_at.desc())
        ).first()
        open_incidents = int(self.session.scalar(
            select(func.count(TenantEntitlementLifecycleRunRecord.id)).where(
                TenantEntitlementLifecycleRunRecord.incident_status.in_(("open", "acknowledged"))
            )
        ) or 0)
        due_activations = int(self.session.scalar(select(func.count(TenantEntitlementRecord.id)).where(
            TenantEntitlementRecord.status == "scheduled",
            TenantEntitlementRecord.starts_at <= observed_at,
            TenantEntitlementRecord.expires_at > observed_at,
        )) or 0)
        due_expirations = int(self.session.scalar(select(func.count(TenantEntitlementRecord.id)).where(
            TenantEntitlementRecord.status.in_(("scheduled", "active", "suspended")),
            TenantEntitlementRecord.expires_at <= observed_at,
        )) or 0)
        if open_incidents:
            health = "incident"
        elif latest is None:
            health = "not_started"
        elif observed_at - self._as_utc(latest.scan_at) > timedelta(minutes=DEFAULT_ENTITLEMENT_SCAN_INTERVAL_MINUTES * 3):
            health = "stale"
        else:
            health = "healthy"
        return {
            "health": health,
            "observed_at": observed_at.isoformat(),
            "scan_interval_minutes": DEFAULT_ENTITLEMENT_SCAN_INTERVAL_MINUTES,
            "next_scan_at": _next_entitlement_scan_at(observed_at).isoformat(),
            "due_activations": due_activations,
            "due_expirations": due_expirations,
            "open_incidents": open_incidents,
            "latest_scheduler_run": self._lifecycle_run_view(latest) if latest else None,
        }

    def run_entitlement_lifecycle(
        self,
        principal: "Principal",
        now: datetime | None = None,
        run_key: str | None = None,
        trigger_type: str = "manual",
        retry_of_run_id: str | None = None,
        resolution_note: str | None = None,
    ) -> dict:
        if trigger_type not in {"scheduler", "manual", "retry"}:
            raise ProductPackageError("ENTITLEMENT_RUN_TRIGGER_INVALID", "授权调度触发类型无效", 422)
        scan_at = self._as_utc(now or self._now())
        stable_key = run_key or entitlement_lifecycle_run_key(scan_at)
        existing = self.session.scalars(select(TenantEntitlementLifecycleRunRecord).where(
            TenantEntitlementLifecycleRunRecord.run_key == stable_key
        )).first()
        if existing:
            if existing.trigger_type != trigger_type or existing.retry_of_run_id != retry_of_run_id:
                raise ProductPackageError("ENTITLEMENT_RUN_KEY_CONFLICT", "运行任务键已被其他触发类型使用", 409)
            return {"idempotent": True, "run": self._lifecycle_run_view(existing), "status": self.entitlement_lifecycle_status(scan_at)}

        run = TenantEntitlementLifecycleRunRecord(
            id=str(uuid4()), run_key=stable_key, trigger_type=trigger_type, status="no_due",
            scan_at=scan_at, activated_count=0, expired_count=0, superseded_count=0,
            failed_count=0, results_json=[], evidence_hash=content_hash({"run_key": stable_key}),
            incident_status="not_applicable", retry_of_run_id=retry_of_run_id,
            actor_subject=principal.subject, actor_name=principal.name, started_at=scan_at,
        )
        self.session.add(run)
        try:
            self.session.flush()
        except IntegrityError as exc:
            self.session.rollback()
            duplicate = self.session.scalars(select(TenantEntitlementLifecycleRunRecord).where(
                TenantEntitlementLifecycleRunRecord.run_key == stable_key
            )).first()
            if duplicate:
                return {"idempotent": True, "run": self._lifecycle_run_view(duplicate), "status": self.entitlement_lifecycle_status(scan_at)}
            raise ProductPackageError("ENTITLEMENT_RUN_CONFLICT", "授权生命周期任务发生并发冲突", 409) from exc

        results: list[dict] = []
        expired_rows = list(self.session.scalars(select(TenantEntitlementRecord).where(
            TenantEntitlementRecord.status.in_(("scheduled", "active", "suspended")),
            TenantEntitlementRecord.expires_at <= scan_at,
        ).order_by(TenantEntitlementRecord.expires_at, TenantEntitlementRecord.id)).all())
        scheduled_rows = list(self.session.scalars(select(TenantEntitlementRecord).where(
            TenantEntitlementRecord.status == "scheduled",
            TenantEntitlementRecord.starts_at <= scan_at,
            TenantEntitlementRecord.expires_at > scan_at,
        ).order_by(TenantEntitlementRecord.tenant_id, TenantEntitlementRecord.starts_at, TenantEntitlementRecord.created_at)).all())

        for record in expired_rows:
            try:
                with self.session.begin_nested():
                    before = self._entitlement_snapshot(record)
                    record.status = "expired"
                    record.expired_at = scan_at
                    record.change_reason = "授权到期，自动归档并停止运行时授权"
                    self.audit.append("tenant_entitlement", record.id, "tenant_entitlement_expired", principal.name, {
                        "tenant_id": record.tenant_id, "run_id": run.id, "run_key": stable_key,
                        "before": before, "expired_at": scan_at.isoformat(),
                    })
                    self.session.flush()
                run.expired_count += 1
                results.append(self._lifecycle_result(record, "expire", "completed"))
            except Exception as exc:
                run.failed_count += 1
                results.append(self._lifecycle_result(record, "expire", "failed", self._safe_error(exc)))

        latest_due_by_tenant: dict[str, TenantEntitlementRecord] = {}
        superseded: list[TenantEntitlementRecord] = []
        for record in scheduled_rows:
            previous = latest_due_by_tenant.get(record.tenant_id)
            if previous is not None:
                superseded.append(previous)
            latest_due_by_tenant[record.tenant_id] = record

        for record in superseded:
            try:
                with self.session.begin_nested():
                    record.status = "terminated"
                    record.terminated_at = scan_at
                    record.change_reason = "存在同租户更晚生效的授权，自动关闭过期排期"
                    self.audit.append("tenant_entitlement", record.id, "tenant_entitlement_schedule_superseded", principal.name, {
                        "tenant_id": record.tenant_id, "run_id": run.id, "run_key": stable_key,
                        "terminated_at": scan_at.isoformat(),
                    })
                    self.session.flush()
                run.superseded_count += 1
                results.append(self._lifecycle_result(record, "supersede", "completed"))
            except Exception as exc:
                run.failed_count += 1
                results.append(self._lifecycle_result(record, "supersede", "failed", self._safe_error(exc)))

        for record in latest_due_by_tenant.values():
            try:
                with self.session.begin_nested():
                    before = self._entitlement_snapshot(record)
                    self._activate(record, principal, "预约开始时间已到，自动激活租户授权", now=scan_at)
                    record.change_reason = "预约开始时间已到，自动激活租户授权"
                    self.audit.append("tenant_entitlement", record.id, "tenant_entitlement_scheduled_activated", principal.name, {
                        "tenant_id": record.tenant_id, "run_id": run.id, "run_key": stable_key,
                        "before": before, "after": self._entitlement_snapshot(record),
                    })
                    self.session.flush()
                run.activated_count += 1
                results.append(self._lifecycle_result(record, "activate", "completed"))
            except Exception as exc:
                run.failed_count += 1
                results.append(self._lifecycle_result(record, "activate", "failed", self._safe_error(exc)))

        completed_count = run.activated_count + run.expired_count + run.superseded_count
        run.status = "no_due" if not results else "failed" if run.failed_count and not completed_count else "partial" if run.failed_count else "completed"
        run.incident_status = "open" if run.failed_count else "not_applicable"
        run.results_json = results
        run.error_summary = f"{run.failed_count} 个授权动作失败，请确认后重试" if run.failed_count else None
        run.completed_at = self._now()
        run.evidence_hash = content_hash({
            "run_key": run.run_key, "trigger_type": run.trigger_type, "scan_at": scan_at.isoformat(),
            "activated_count": run.activated_count, "expired_count": run.expired_count,
            "superseded_count": run.superseded_count, "failed_count": run.failed_count, "results": results,
        })
        self.audit.append("tenant_entitlement_lifecycle_run", run.id, f"tenant_entitlement_lifecycle_{run.status}", principal.name, {
            "run_key": stable_key, "trigger_type": trigger_type, "evidence_hash": run.evidence_hash,
            "activated_count": run.activated_count, "expired_count": run.expired_count,
            "superseded_count": run.superseded_count, "failed_count": run.failed_count,
        })
        if run.failed_count:
            self._create_lifecycle_failure_notifications(run, results)
        elif retry_of_run_id:
            original = self.session.get(TenantEntitlementLifecycleRunRecord, retry_of_run_id)
            if original and original.incident_status in {"open", "acknowledged"}:
                original.incident_status = "resolved"
                original.resolved_by = principal.subject
                original.resolved_by_name = principal.name
                original.resolved_at = run.completed_at
                original.resolution_note = resolution_note or "授权生命周期重试已恢复"
                original.resolved_by_run_id = run.id
                self._resolve_lifecycle_notifications(original)
        try:
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise ProductPackageError("ENTITLEMENT_RUN_CONFLICT", "授权生命周期运行被并发更新，请刷新后重试", 409) from exc
        self.session.refresh(run)
        return {"idempotent": False, "run": self._lifecycle_run_view(run), "status": self.entitlement_lifecycle_status(scan_at)}

    def acknowledge_entitlement_lifecycle_run(self, run_id: str, payload: dict, principal: "Principal") -> dict:
        run = self._lifecycle_run(run_id, payload["expected_row_version"])
        if run.incident_status != "open":
            raise ProductPackageError("ENTITLEMENT_INCIDENT_STATUS_INVALID", "只有未确认的授权运行异常可以确认", 409)
        run.incident_status = "acknowledged"
        run.acknowledged_by = principal.subject
        run.acknowledged_by_name = principal.name
        run.acknowledged_at = self._now()
        run.acknowledgement_note = payload["reason"]
        self.audit.append("tenant_entitlement_lifecycle_run", run.id, "tenant_entitlement_lifecycle_incident_acknowledged", principal.name, {
            "run_key": run.run_key, "reason": payload["reason"], "evidence_hash": run.evidence_hash,
        })
        return self._commit_lifecycle_run(run)

    def retry_entitlement_lifecycle_run(self, run_id: str, payload: dict, principal: "Principal") -> dict:
        run = self._lifecycle_run(run_id, payload["expected_row_version"])
        if run.incident_status != "acknowledged":
            raise ProductPackageError("ENTITLEMENT_INCIDENT_NOT_ACKNOWLEDGED", "请先确认授权运行异常，再发起补偿重试", 409)
        retry_key = payload.get("run_key") or f"tenant-entitlement:retry:{run.id}:{run.row_version}"
        return self.run_entitlement_lifecycle(
            principal=principal, now=self._now(), run_key=retry_key, trigger_type="retry",
            retry_of_run_id=run.id, resolution_note=payload["reason"],
        )

    def _activate(self, record: TenantEntitlementRecord, principal: "Principal", reason: str, now: datetime | None = None) -> None:
        now = self._as_utc(now or self._now())
        if self._as_utc(record.expires_at) <= now:
            raise ProductPackageError("ENTITLEMENT_EXPIRED", "授权已到期，不能激活", 409)
        if content_hash(record.package_snapshot_json) != record.package_config_hash:
            raise ProductPackageError("PACKAGE_SNAPSHOT_INTEGRITY_FAILED", "授权中的产品包快照哈希不一致", 409)
        for current in self.session.scalars(select(TenantEntitlementRecord).where(
            TenantEntitlementRecord.tenant_id == record.tenant_id,
            TenantEntitlementRecord.status == "active",
        )).all():
            if current.id != record.id:
                current.status = "terminated"
                current.terminated_at = now
        self.session.flush()
        record.status = "active"
        record.activated_at = now
        record.suspended_at = None
        try:
            initialized = self.assets.initialize_from_entitlement(
                record.tenant_id, record.package_snapshot_json["assets"], principal, reason
            )
        except TenantAssetError as exc:
            raise ProductPackageError(exc.code, exc.message, exc.status_code, exc.details) from exc
        record.initialized_assets_json = initialized
        quotas = record.effective_quotas_json
        for client in self.session.scalars(select(ApiClientRecord).where(ApiClientRecord.tenant_id == record.tenant_id)).all():
            client.qps_limit = quotas["qps_limit"]
            client.concurrent_job_limit = quotas["concurrent_job_limit"]
            client.daily_item_quota = quotas["daily_item_quota"]
        record.activation_hash = content_hash({
            "tenant_id": record.tenant_id, "entitlement_id": record.id,
            "package_config_hash": record.package_config_hash, "effective_quotas": quotas,
            "initialized_assets": initialized, "activated_at": now.isoformat(),
        })

    def _validate_assets(self, assets: list[dict]) -> list[dict]:
        validated: list[dict] = []
        for item in assets:
            try:
                platform = self.assets._require_platform_asset(item["asset_type"], item["asset_code"], item.get("pinned_version"))
            except TenantAssetError as exc:
                raise ProductPackageError(exc.code, exc.message, exc.status_code, exc.details) from exc
            validated.append({
                "asset_type": item["asset_type"], "asset_code": item["asset_code"],
                "asset_name": platform["name"], "binding_mode": item["binding_mode"],
                "pinned_version": item.get("pinned_version"),
                "allow_tenant_override": bool(item.get("allow_tenant_override")),
            })
        return validated

    @staticmethod
    def _package_config(payload: dict, assets: list[dict]) -> dict:
        return {
            "code": payload["code"], "name": payload["name"], "description": payload["description"],
            "environment_scopes": list(payload["environment_scopes"]), "assets": deepcopy(assets),
            "quotas": deepcopy(payload["quotas"]), "expiry_policy": payload["expiry_policy"],
        }

    def _package_config_from_record(self, record: ProductPackageRecord) -> dict:
        return {
            "code": record.code, "name": record.name, "description": record.description,
            "environment_scopes": list(record.environment_scopes_json or []),
            "assets": deepcopy(record.asset_catalog_json or []), "quotas": deepcopy(record.quotas_json or {}),
            "expiry_policy": record.expiry_policy,
        }

    @staticmethod
    def _effective_quotas(base: dict, override: dict | None) -> dict:
        result = deepcopy(override or base)
        for key, value in result.items():
            if key not in base or value > base[key]:
                raise ProductPackageError("QUOTA_OVERRIDE_EXCEEDS_PACKAGE", "租户配额不能超过产品包上限", 422, {"quota": key})
        return result

    @staticmethod
    def _binding_differs(record: TenantAssetBindingRecord, item: dict) -> bool:
        return any((
            record.status != "active", record.binding_mode != item["binding_mode"],
            record.pinned_version != item.get("pinned_version"),
            record.allow_tenant_override != bool(item.get("allow_tenant_override")),
        ))

    def _package(self, package_id: str) -> ProductPackageRecord:
        record = self.session.get(ProductPackageRecord, package_id)
        if record is None:
            raise ProductPackageError("PACKAGE_NOT_FOUND", "产品包不存在", 404)
        return record

    def _published_package(self, package_id: str) -> ProductPackageRecord:
        record = self._package(package_id)
        if record.status != "published" or not record.is_active:
            raise ProductPackageError("PACKAGE_NOT_PUBLISHED", "只能为租户授权当前已发布产品包", 409)
        if content_hash(self._package_config_from_record(record)) != record.config_hash:
            raise ProductPackageError("PACKAGE_INTEGRITY_FAILED", "产品包配置哈希不一致", 409)
        return record

    def _entitlement(self, entitlement_id: str) -> TenantEntitlementRecord:
        record = self.session.get(TenantEntitlementRecord, entitlement_id)
        if record is None:
            raise ProductPackageError("ENTITLEMENT_NOT_FOUND", "租户授权不存在", 404)
        return record

    def _current_entitlement(self, tenant_id: str) -> TenantEntitlementRecord | None:
        now = self._now()
        return self.session.scalars(select(TenantEntitlementRecord).where(
            TenantEntitlementRecord.tenant_id == tenant_id,
            TenantEntitlementRecord.status == "active",
            TenantEntitlementRecord.starts_at <= now,
            TenantEntitlementRecord.expires_at > now,
        )).first()

    @staticmethod
    def _package_snapshot(record: ProductPackageRecord) -> dict:
        return {
            "id": record.id, "code": record.code, "version": record.version, "name": record.name,
            "status": record.status, "is_active": record.is_active, "config_hash": record.config_hash,
            "change_reason": record.change_reason, "created_by": record.created_by,
            "submitted_at": _iso(record.submitted_at), "reviewed_by": record.reviewed_by,
            "reviewed_at": _iso(record.reviewed_at), "published_at": _iso(record.published_at),
            "row_version": record.row_version,
        }

    def _package_view(self, record: ProductPackageRecord) -> dict:
        return {
            **self._package_snapshot(record), "description": record.description,
            "environment_scopes": list(record.environment_scopes_json or []),
            "assets": deepcopy(record.asset_catalog_json or []), "quotas": deepcopy(record.quotas_json or {}),
            "expiry_policy": record.expiry_policy, "created_by_name": record.created_by_name,
            "reviewed_by_name": record.reviewed_by_name, "review_comment": record.review_comment,
            "created_at": _iso(record.created_at), "updated_at": _iso(record.updated_at),
        }

    def _entitlement_snapshot(self, record: TenantEntitlementRecord) -> dict:
        return {
            "id": record.id, "tenant_id": record.tenant_id, "product_package_id": record.product_package_id,
            "package_code": record.package_code, "package_version": record.package_version,
            "package_config_hash": record.package_config_hash, "effective_quotas": deepcopy(record.effective_quotas_json),
            "initialized_assets": deepcopy(record.initialized_assets_json or []), "activation_hash": record.activation_hash,
            "status": record.status, "starts_at": _iso(record.starts_at), "expires_at": _iso(record.expires_at),
            "change_reason": record.change_reason, "created_by": record.created_by,
            "submitted_at": _iso(record.submitted_at), "reviewed_by": record.reviewed_by,
            "reviewed_at": _iso(record.reviewed_at), "activated_at": _iso(record.activated_at),
            "suspended_at": _iso(record.suspended_at), "expired_at": _iso(record.expired_at),
            "terminated_at": _iso(record.terminated_at),
            "row_version": record.row_version,
        }

    def _entitlement_view(self, record: TenantEntitlementRecord) -> dict:
        now = self._now()
        effective_status = record.status
        if record.status == "active" and self._as_utc(record.expires_at) <= now:
            effective_status = "expired"
        elif record.status == "scheduled" and self._as_utc(record.starts_at) <= now:
            effective_status = "ready_to_activate"
        return {
            **self._entitlement_snapshot(record), "effective_status": effective_status,
            "package_snapshot": deepcopy(record.package_snapshot_json), "created_by_name": record.created_by_name,
            "reviewed_by_name": record.reviewed_by_name, "review_comment": record.review_comment,
            "created_at": _iso(record.created_at), "updated_at": _iso(record.updated_at),
        }

    def _lifecycle_run(self, run_id: str, expected_row_version: int) -> TenantEntitlementLifecycleRunRecord:
        run = self.session.get(TenantEntitlementLifecycleRunRecord, run_id)
        if run is None:
            raise ProductPackageError("ENTITLEMENT_RUN_NOT_FOUND", "授权生命周期运行不存在", 404)
        self._check(run.row_version, expected_row_version, "授权生命周期运行")
        return run

    def _commit_lifecycle_run(self, run: TenantEntitlementLifecycleRunRecord) -> dict:
        try:
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise ProductPackageError("ENTITLEMENT_RUN_CONFLICT", "授权生命周期运行被并发更新，请刷新后重试", 409) from exc
        self.session.refresh(run)
        return self._lifecycle_run_view(run)

    def _create_lifecycle_failure_notifications(self, run: TenantEntitlementLifecycleRunRecord, results: list[dict]) -> None:
        failed = [item for item in results if item["status"] == "failed"]
        notifier = NotificationRepository(self.session)
        notifier.create_if_absent(PLATFORM_INTERNAL_TENANT_ID, {
            "case_id": None, "counterparty_id": None, "recipient_role": "admin", "recipient_subject": None,
            "category": "tenant_entitlement", "level": "critical", "severity": "critical",
            "title": "租户授权自动执行失败",
            "message": f"运行 {run.run_key} 有 {len(failed)} 个授权动作失败，请进入租户产品运行控制台确认并重试。",
            "action_json": {"view": "tenant-products", "tab": "operations", "run_id": run.id},
            "dedup_key": f"tenant-entitlement-lifecycle:{run.id}:admin:failed",
        })
        for tenant_id in sorted({item["tenant_id"] for item in failed}):
            notifier.create_if_absent(tenant_id, {
                "case_id": None, "counterparty_id": None, "recipient_role": "model_admin", "recipient_subject": None,
                "category": "tenant_entitlement", "level": "critical", "severity": "critical",
                "title": "本租户产品授权执行异常",
                "message": "产品授权自动激活或到期归档失败，平台运营正在处理；异常解除前运行时门禁保持原状态。",
                "action_json": {"view": "model-governance", "run_id": run.id},
                "dedup_key": f"tenant-entitlement-lifecycle:{run.id}:{tenant_id}:failed",
            })

    def _resolve_lifecycle_notifications(self, original: TenantEntitlementLifecycleRunRecord) -> None:
        rows = self.session.scalars(select(NotificationRecord).where(
            NotificationRecord.dedup_key.like(f"tenant-entitlement-lifecycle:{original.id}:%:failed"),
            NotificationRecord.status != "resolved",
        )).all()
        for notification in rows:
            notification.status = "resolved"
            notification.read_at = notification.read_at or self._now()

    @staticmethod
    def _lifecycle_result(record: TenantEntitlementRecord, action: str, status: str, error: str | None = None) -> dict:
        return {
            "entitlement_id": record.id, "tenant_id": record.tenant_id,
            "package_code": record.package_code, "package_version": record.package_version,
            "action": action, "status": status, "error": error,
        }

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        if isinstance(exc, ProductPackageError):
            return f"{exc.code}: {exc.message}"
        return f"{type(exc).__name__}: {str(exc) or '授权动作执行失败'}"[:1000]

    @staticmethod
    def _lifecycle_run_view(record: TenantEntitlementLifecycleRunRecord) -> dict:
        return {
            "id": record.id, "run_key": record.run_key, "trigger_type": record.trigger_type,
            "status": record.status, "scan_at": _iso(record.scan_at),
            "activated_count": record.activated_count, "expired_count": record.expired_count,
            "superseded_count": record.superseded_count, "failed_count": record.failed_count,
            "results": deepcopy(record.results_json or []), "evidence_hash": record.evidence_hash,
            "error_summary": record.error_summary, "incident_status": record.incident_status,
            "acknowledged_by": record.acknowledged_by, "acknowledged_by_name": record.acknowledged_by_name,
            "acknowledged_at": _iso(record.acknowledged_at), "acknowledgement_note": record.acknowledgement_note,
            "resolved_by": record.resolved_by, "resolved_by_name": record.resolved_by_name,
            "resolved_at": _iso(record.resolved_at), "resolution_note": record.resolution_note,
            "retry_of_run_id": record.retry_of_run_id, "resolved_by_run_id": record.resolved_by_run_id,
            "actor_subject": record.actor_subject, "actor_name": record.actor_name,
            "started_at": _iso(record.started_at), "completed_at": _iso(record.completed_at),
            "row_version": record.row_version, "created_at": _iso(record.created_at),
        }

    def _commit_new(self, record, aggregate_type: str, event: str, principal: "Principal", reason: str, snapshot_factory) -> dict:
        try:
            self.session.flush()
            self._audit(aggregate_type, record.id, event, principal, reason, after=snapshot_factory(record))
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise ProductPackageError("ROW_VERSION_CONFLICT", "配置发生并发冲突，请刷新后重试", 409) from exc
        self.session.refresh(record)
        return self._package_view(record) if isinstance(record, ProductPackageRecord) else self._entitlement_view(record)

    def _commit_change(self, record, aggregate_type: str, event: str, principal: "Principal", reason: str, before: dict, snapshot_factory) -> dict:
        try:
            self.session.flush()
            self._audit(aggregate_type, record.id, event, principal, reason, before=before, after=snapshot_factory(record))
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise ProductPackageError("ROW_VERSION_CONFLICT", "配置发生并发冲突，请刷新后重试", 409) from exc
        self.session.refresh(record)
        return self._package_view(record) if isinstance(record, ProductPackageRecord) else self._entitlement_view(record)

    def _audit(self, aggregate_type: str, aggregate_id: str, event: str, principal: "Principal", reason: str, before=None, after=None) -> None:
        self.audit.append(aggregate_type, aggregate_id, event, principal.name, {
            "tenant_id": after.get("tenant_id") if aggregate_type == "tenant_entitlement" and after else None,
            "actor_subject": principal.subject, "actor_tenant_id": principal.tenant_id,
            "actor_client_id": principal.client_id, "reason": reason,
            "before": deepcopy(before), "after": deepcopy(after),
        })

    @staticmethod
    def _check(current: int, expected: int, subject: str) -> None:
        if current != expected:
            raise ProductPackageError("ROW_VERSION_CONFLICT", f"{subject}版本已变化，当前版本为 {current}", 409)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def entitlement_lifecycle_run_key(
    run_at: datetime | None = None,
    interval_minutes: int = DEFAULT_ENTITLEMENT_SCAN_INTERVAL_MINUTES,
) -> str:
    if interval_minutes <= 0:
        raise ValueError("授权调度间隔必须大于 0")
    observed_at = ProductPackageRepository._as_utc(run_at or datetime.now(timezone.utc))
    bucket_minute = observed_at.minute - observed_at.minute % interval_minutes
    bucket = observed_at.replace(minute=bucket_minute, second=0, microsecond=0)
    return f"tenant-entitlement:{bucket.strftime('%Y%m%dT%H%MZ')}"


def _next_entitlement_scan_at(
    observed_at: datetime,
    interval_minutes: int = DEFAULT_ENTITLEMENT_SCAN_INTERVAL_MINUTES,
) -> datetime:
    current_key_time = observed_at.replace(
        minute=observed_at.minute - observed_at.minute % interval_minutes,
        second=0,
        microsecond=0,
    )
    return current_key_time + timedelta(minutes=interval_minutes)
