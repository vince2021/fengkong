"""Audited platform administration for tenants, memberships, and API clients."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from backend.db_models import ApiClientRecord, TenantMembershipRecord, TenantRecord
from backend.repository import AuditRepository

if TYPE_CHECKING:
    from backend.security import Principal


class TenantAdminError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class TenantAdminRepository:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit = AuditRepository(session)

    def list_tenants(self, limit: int, offset: int, status: str | None = None) -> dict:
        filters = [TenantRecord.status == status] if status else []
        total = self.session.scalar(select(func.count(TenantRecord.id)).where(*filters)) or 0
        membership_counts = (
            select(
                TenantMembershipRecord.tenant_id.label("tenant_id"),
                func.count(TenantMembershipRecord.id).label("membership_count"),
            )
            .group_by(TenantMembershipRecord.tenant_id)
            .subquery()
        )
        client_counts = (
            select(
                ApiClientRecord.tenant_id.label("tenant_id"),
                func.count(ApiClientRecord.id).label("api_client_count"),
            )
            .group_by(ApiClientRecord.tenant_id)
            .subquery()
        )
        rows = self.session.execute(
            select(
                TenantRecord,
                func.coalesce(membership_counts.c.membership_count, 0),
                func.coalesce(client_counts.c.api_client_count, 0),
            )
            .outerjoin(membership_counts, membership_counts.c.tenant_id == TenantRecord.id)
            .outerjoin(client_counts, client_counts.c.tenant_id == TenantRecord.id)
            .where(*filters)
            .order_by(TenantRecord.created_at.desc(), TenantRecord.id)
            .offset(offset)
            .limit(limit)
        ).all()
        return {
            "items": [self._tenant_view(row, memberships, clients) for row, memberships, clients in rows],
            "total": int(total),
            "limit": limit,
            "offset": offset,
        }

    def get_tenant(self, tenant_id: str) -> dict:
        return self._tenant_view(self._tenant(tenant_id))

    def create_tenant(self, payload: dict, principal: "Principal") -> dict:
        if self.session.get(TenantRecord, payload["tenant_id"]):
            raise TenantAdminError("TENANT_ALREADY_EXISTS", "租户标识已存在", 409)
        record = TenantRecord(
            id=payload["tenant_id"],
            name=payload["name"],
            deployment_mode=payload["deployment_mode"],
            status="active",
            data_region=payload["data_region"],
        )
        self.session.add(record)
        try:
            self.session.flush()
            self._audit(
                "tenant",
                record.id,
                "tenant_created",
                principal,
                payload["reason"],
                after=self._tenant_snapshot(record),
            )
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise TenantAdminError("TENANT_ALREADY_EXISTS", "租户标识已存在", 409) from exc
        self.session.refresh(record)
        return self._tenant_view(record)

    def update_tenant_status(self, tenant_id: str, payload: dict, principal: "Principal") -> dict:
        record = self._tenant(tenant_id)
        self._check_version(record.row_version, payload["expected_row_version"], "租户")
        if record.id == principal.tenant_id and payload["status"] != "active":
            raise TenantAdminError("CURRENT_TENANT_PROTECTED", "不能停用当前平台管理员所在租户", 422)
        if record.status == payload["status"]:
            raise TenantAdminError("TENANT_STATUS_UNCHANGED", "租户状态未发生变化", 422)
        before = self._tenant_snapshot(record)
        record.status = payload["status"]
        self._commit_change(
            "tenant",
            record.id,
            "tenant_status_changed",
            principal,
            payload["reason"],
            before,
            lambda: self._tenant_snapshot(record),
            "租户状态已被其他管理员更新，请刷新后重试",
        )
        return self._tenant_view(record)

    def list_memberships(self, tenant_id: str) -> list[dict]:
        self._tenant(tenant_id)
        rows = self.session.scalars(
            select(TenantMembershipRecord)
            .where(TenantMembershipRecord.tenant_id == tenant_id)
            .order_by(TenantMembershipRecord.created_at, TenantMembershipRecord.subject)
        ).all()
        return [self._membership_view(row) for row in rows]

    def create_membership(self, tenant_id: str, payload: dict, principal: "Principal") -> dict:
        self._tenant(tenant_id)
        self._validate_roles(tenant_id, payload["roles"])
        self._validate_future_expiry(payload.get("expires_at"))
        existing = self.session.scalars(
            select(TenantMembershipRecord).where(
                TenantMembershipRecord.tenant_id == tenant_id,
                TenantMembershipRecord.subject == payload["subject"],
            )
        ).first()
        if existing:
            raise TenantAdminError("TENANT_MEMBERSHIP_ALREADY_EXISTS", "该成员已登记到目标租户", 409)
        record = TenantMembershipRecord(
            id=str(uuid4()),
            tenant_id=tenant_id,
            subject=payload["subject"],
            display_name=payload["display_name"],
            roles_json=list(payload["roles"]),
            status="active",
            expires_at=payload.get("expires_at"),
        )
        self.session.add(record)
        try:
            self.session.flush()
            self._audit(
                "tenant_membership",
                f"{tenant_id}:{record.subject}",
                "tenant_membership_created",
                principal,
                payload["reason"],
                after=self._membership_snapshot(record),
            )
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise TenantAdminError("TENANT_MEMBERSHIP_ALREADY_EXISTS", "该成员已登记到目标租户", 409) from exc
        self.session.refresh(record)
        return self._membership_view(record)

    def update_membership(self, tenant_id: str, subject: str, payload: dict, principal: "Principal") -> dict:
        record = self._membership(tenant_id, subject)
        self._check_version(record.row_version, payload["expected_row_version"], "成员关系")
        roles = payload.get("roles")
        if roles is not None:
            self._validate_roles(tenant_id, roles)
        if payload.get("expires_at") is not None:
            self._validate_future_expiry(payload["expires_at"])
        next_status = payload.get("status", record.status)
        next_roles = set(roles if roles is not None else record.roles_json or [])
        if tenant_id == principal.tenant_id and subject == principal.subject:
            if next_status != "active" or "admin" not in next_roles:
                raise TenantAdminError("CURRENT_MEMBERSHIP_PROTECTED", "不能撤销当前平台管理员自己的有效管理权限", 422)

        before = self._membership_snapshot(record)
        for field in ("display_name", "status"):
            if payload.get(field) is not None:
                setattr(record, field, payload[field])
        if roles is not None:
            record.roles_json = list(roles)
        if payload.get("clear_expiry"):
            record.expires_at = None
        elif payload.get("expires_at") is not None:
            record.expires_at = payload["expires_at"]
        if self._membership_snapshot(record) == before:
            raise TenantAdminError("TENANT_MEMBERSHIP_UNCHANGED", "成员关系未发生变化", 422)
        self._commit_change(
            "tenant_membership",
            f"{tenant_id}:{subject}",
            "tenant_membership_updated",
            principal,
            payload["reason"],
            before,
            lambda: self._membership_snapshot(record),
            "成员关系已被其他管理员更新，请刷新后重试",
        )
        return self._membership_view(record)

    def list_clients(self, tenant_id: str) -> list[dict]:
        self._tenant(tenant_id)
        rows = self.session.scalars(
            select(ApiClientRecord)
            .where(ApiClientRecord.tenant_id == tenant_id)
            .order_by(ApiClientRecord.created_at, ApiClientRecord.client_id)
        ).all()
        return [self._client_view(row) for row in rows]

    def create_client(self, tenant_id: str, payload: dict, principal: "Principal") -> dict:
        self._tenant(tenant_id)
        self._validate_future_expiry(payload.get("expires_at"))
        existing = self.session.scalars(
            select(ApiClientRecord).where(
                ApiClientRecord.tenant_id == tenant_id,
                ApiClientRecord.client_id == payload["client_id"],
            )
        ).first()
        if existing:
            raise TenantAdminError("API_CLIENT_ALREADY_EXISTS", "客户端标识已在目标租户中登记", 409)
        record = ApiClientRecord(
            id=str(uuid4()),
            tenant_id=tenant_id,
            client_id=payload["client_id"],
            name=payload["name"],
            status="active",
            key_id=payload["key_id"],
            key_fingerprint=payload["key_fingerprint"],
            secret_reference=payload.get("secret_reference"),
            qps_limit=payload["qps_limit"],
            concurrent_job_limit=payload["concurrent_job_limit"],
            daily_item_quota=payload["daily_item_quota"],
            allowed_cidrs_json=list(payload["allowed_cidrs"]),
            expires_at=payload.get("expires_at"),
        )
        self.session.add(record)
        try:
            self.session.flush()
            self._audit(
                "api_client",
                f"{tenant_id}:{record.client_id}",
                "api_client_created",
                principal,
                payload["reason"],
                after=self._client_snapshot(record),
            )
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise TenantAdminError("API_CLIENT_ALREADY_EXISTS", "客户端标识已在目标租户中登记", 409) from exc
        self.session.refresh(record)
        return self._client_view(record)

    def update_client(self, tenant_id: str, client_id: str, payload: dict, principal: "Principal") -> dict:
        record = self._client(tenant_id, client_id)
        self._check_version(record.row_version, payload["expected_row_version"], "API 客户端")
        if payload.get("expires_at") is not None:
            self._validate_future_expiry(payload["expires_at"])
        next_status = payload.get("status", record.status)
        if tenant_id == principal.tenant_id and client_id == principal.client_id and next_status != "active":
            raise TenantAdminError("CURRENT_CLIENT_PROTECTED", "不能停用当前平台管理员正在使用的客户端", 422)

        before = self._client_snapshot(record)
        rotated = any(payload.get(field) is not None for field in ("key_id", "key_fingerprint", "secret_reference"))
        for field in ("name", "status", "key_id", "key_fingerprint", "qps_limit", "concurrent_job_limit", "daily_item_quota"):
            if payload.get(field) is not None:
                setattr(record, field, payload[field])
        if payload.get("allowed_cidrs") is not None:
            record.allowed_cidrs_json = list(payload["allowed_cidrs"])
        if payload.get("clear_secret_reference"):
            record.secret_reference = None
            rotated = True
        elif payload.get("secret_reference") is not None:
            record.secret_reference = payload["secret_reference"]
        if payload.get("clear_expiry"):
            record.expires_at = None
        elif payload.get("expires_at") is not None:
            record.expires_at = payload["expires_at"]
        if rotated:
            record.rotated_at = datetime.now(timezone.utc)
        if self._client_snapshot(record) == before:
            raise TenantAdminError("API_CLIENT_UNCHANGED", "API 客户端配置未发生变化", 422)
        self._commit_change(
            "api_client",
            f"{tenant_id}:{client_id}",
            "api_client_updated",
            principal,
            payload["reason"],
            before,
            lambda: self._client_snapshot(record),
            "API 客户端已被其他管理员更新，请刷新后重试",
        )
        return self._client_view(record)

    def _tenant(self, tenant_id: str) -> TenantRecord:
        record = self.session.get(TenantRecord, tenant_id)
        if record is None:
            raise TenantAdminError("TENANT_NOT_FOUND", "租户不存在", 404)
        return record

    def _membership(self, tenant_id: str, subject: str) -> TenantMembershipRecord:
        record = self.session.scalars(
            select(TenantMembershipRecord).where(
                TenantMembershipRecord.tenant_id == tenant_id,
                TenantMembershipRecord.subject == subject,
            )
        ).first()
        if record is None:
            raise TenantAdminError("TENANT_MEMBERSHIP_NOT_FOUND", "租户成员不存在", 404)
        return record

    def _client(self, tenant_id: str, client_id: str) -> ApiClientRecord:
        record = self.session.scalars(
            select(ApiClientRecord).where(
                ApiClientRecord.tenant_id == tenant_id,
                ApiClientRecord.client_id == client_id,
            )
        ).first()
        if record is None:
            raise TenantAdminError("API_CLIENT_NOT_FOUND", "API 客户端不存在", 404)
        return record

    def _tenant_view(
        self,
        record: TenantRecord,
        memberships: int | None = None,
        clients: int | None = None,
    ) -> dict:
        if memberships is None:
            memberships = self.session.scalar(
                select(func.count(TenantMembershipRecord.id)).where(TenantMembershipRecord.tenant_id == record.id)
            ) or 0
        if clients is None:
            clients = self.session.scalar(
                select(func.count(ApiClientRecord.id)).where(ApiClientRecord.tenant_id == record.id)
            ) or 0
        return {
            **self._tenant_snapshot(record),
            "membership_count": int(memberships),
            "api_client_count": int(clients),
            "created_at": _iso(record.created_at),
            "updated_at": _iso(record.updated_at),
        }

    @staticmethod
    def _tenant_snapshot(record: TenantRecord) -> dict:
        return {
            "id": record.id,
            "name": record.name,
            "deployment_mode": record.deployment_mode,
            "status": record.status,
            "data_region": record.data_region,
            "row_version": record.row_version,
        }

    @staticmethod
    def _membership_snapshot(record: TenantMembershipRecord) -> dict:
        return {
            "id": record.id,
            "tenant_id": record.tenant_id,
            "subject": record.subject,
            "display_name": record.display_name,
            "roles": list(record.roles_json or []),
            "status": record.status,
            "expires_at": _iso(record.expires_at),
            "row_version": record.row_version,
        }

    def _membership_view(self, record: TenantMembershipRecord) -> dict:
        return {
            **self._membership_snapshot(record),
            "created_at": _iso(record.created_at),
            "updated_at": _iso(record.updated_at),
        }

    @staticmethod
    def _client_snapshot(record: ApiClientRecord) -> dict:
        return {
            "id": record.id,
            "tenant_id": record.tenant_id,
            "client_id": record.client_id,
            "name": record.name,
            "status": record.status,
            "key_id": record.key_id,
            "key_fingerprint": record.key_fingerprint,
            "secret_reference": record.secret_reference,
            "qps_limit": record.qps_limit,
            "concurrent_job_limit": record.concurrent_job_limit,
            "daily_item_quota": record.daily_item_quota,
            "allowed_cidrs": list(record.allowed_cidrs_json or []),
            "rotated_at": _iso(record.rotated_at),
            "expires_at": _iso(record.expires_at),
            "last_used_at": _iso(record.last_used_at),
            "row_version": record.row_version,
        }

    def _client_view(self, record: ApiClientRecord) -> dict:
        return {
            **self._client_snapshot(record),
            "created_at": _iso(record.created_at),
            "updated_at": _iso(record.updated_at),
        }

    @staticmethod
    def _check_version(current: int, expected: int, subject: str) -> None:
        if current != expected:
            raise TenantAdminError("ROW_VERSION_CONFLICT", f"{subject}版本已变化，当前版本为 {current}", 409)

    @staticmethod
    def _validate_roles(tenant_id: str, roles: list[str]) -> None:
        if "admin" in roles and tenant_id != "tenant-platform-internal":
            raise TenantAdminError("PLATFORM_ADMIN_SCOPE_INVALID", "平台管理员角色只能授予平台内部租户成员", 422)

    @staticmethod
    def _validate_future_expiry(value: datetime | None) -> None:
        if value is None:
            return
        normalized = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if normalized <= datetime.now(timezone.utc):
            raise TenantAdminError("EXPIRY_INVALID", "有效期必须晚于当前时间", 422)

    def _audit(
        self,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        principal: "Principal",
        reason: str,
        before: dict | None = None,
        after: dict | None = None,
    ) -> None:
        self.audit.append(
            aggregate_type,
            aggregate_id,
            event_type,
            principal.name,
            {
                "actor_subject": principal.subject,
                "actor_tenant_id": principal.tenant_id,
                "actor_client_id": principal.client_id,
                "reason": reason,
                "before": deepcopy(before),
                "after": deepcopy(after),
            },
        )

    def _commit_change(
        self,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        principal: "Principal",
        reason: str,
        before: dict,
        after_factory,
        conflict_message: str,
    ) -> None:
        try:
            self.session.flush()
            self._audit(aggregate_type, aggregate_id, event_type, principal, reason, before, after_factory())
            self.session.commit()
        except (StaleDataError, IntegrityError) as exc:
            self.session.rollback()
            raise TenantAdminError("ROW_VERSION_CONFLICT", conflict_message, 409) from exc


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
