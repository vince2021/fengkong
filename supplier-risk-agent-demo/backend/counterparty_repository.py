"""Tenant-scoped, audited counterparty master data repository."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from backend.db_models import AuditEventRecord, CounterpartyRecord
from backend.repository import AuditRepository, content_hash

if TYPE_CHECKING:
    from backend.security import Principal


class CounterpartyError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class CounterpartyRepository:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit = AuditRepository(session)

    def list_legacy(self, tenant_id: str, counterparty_id: str | None = None) -> list[dict]:
        statement = select(CounterpartyRecord).where(
            CounterpartyRecord.tenant_id == tenant_id,
            CounterpartyRecord.status == "active",
        )
        if counterparty_id:
            statement = statement.where(CounterpartyRecord.counterparty_id == counterparty_id)
        rows = self.session.scalars(statement.order_by(CounterpartyRecord.name, CounterpartyRecord.counterparty_id)).all()
        return [self._view(row) for row in rows]

    def page(
        self,
        tenant_id: str,
        *,
        q: str | None,
        counterparty_type: str | None,
        status: str | None,
        limit: int,
        offset: int,
        counterparty_id: str | None = None,
    ) -> dict:
        filters = [CounterpartyRecord.tenant_id == tenant_id]
        if counterparty_id:
            filters.append(CounterpartyRecord.counterparty_id == counterparty_id)
        if q:
            keyword = f"%{q.strip()}%"
            filters.append(
                or_(
                    CounterpartyRecord.counterparty_id.ilike(keyword),
                    CounterpartyRecord.credit_code.ilike(keyword),
                    CounterpartyRecord.name.ilike(keyword),
                )
            )
        if counterparty_type:
            filters.append(CounterpartyRecord.counterparty_type == counterparty_type)
        if status:
            filters.append(CounterpartyRecord.status == status)
        total = self.session.scalar(select(func.count(CounterpartyRecord.id)).where(*filters)) or 0
        rows = self.session.scalars(
            select(CounterpartyRecord)
            .where(*filters)
            .order_by(CounterpartyRecord.updated_at.desc(), CounterpartyRecord.counterparty_id)
            .offset(offset)
            .limit(limit)
        ).all()
        return {"items": [self._view(row) for row in rows], "total": int(total), "limit": limit, "offset": offset}

    def get(self, tenant_id: str, counterparty_id: str, *, include_archived: bool = False) -> dict:
        return self._view(self._record(tenant_id, counterparty_id, include_archived=include_archived))

    def history(self, tenant_id: str, counterparty_id: str, *, limit: int = 20) -> list[dict]:
        self._record(tenant_id, counterparty_id, include_archived=True)
        stored = self.session.scalars(
            select(AuditEventRecord)
            .where(
                AuditEventRecord.tenant_id == tenant_id,
                AuditEventRecord.aggregate_type == "counterparty",
                AuditEventRecord.aggregate_id == f"{tenant_id}:{counterparty_id}",
            )
        ).all()
        by_previous = {row.previous_hash: row for row in stored}
        ordered: list[AuditEventRecord] = []
        previous_hash = ""
        while previous_hash in by_previous:
            row = by_previous[previous_hash]
            ordered.append(row)
            previous_hash = row.event_hash
        rows = list(reversed(ordered))[:limit]
        events: list[dict] = []
        for row in rows:
            payload = row.payload or {}
            before = payload.get("before") or {}
            after = payload.get("after") or {}
            events.append({
                "id": row.id,
                "event_type": row.event_type,
                "actor": row.actor,
                "actor_name": payload.get("actor_name") or row.actor,
                "reason": payload.get("reason") or "未记录业务原因",
                "changed_fields": sorted(
                    key for key in set(before) | set(after)
                    if before.get(key) != after.get(key)
                ),
                "row_version": after.get("row_version"),
                "previous_hash": row.previous_hash,
                "event_hash": row.event_hash,
                "created_at": self._iso(row.created_at),
            })
        return events

    def create(self, payload: dict, principal: "Principal") -> dict:
        values = deepcopy(payload)
        reason = values.pop("reason")
        record = CounterpartyRecord(
            id=str(uuid4()), tenant_id=principal.tenant_id,
            counterparty_id=values["counterparty_id"], credit_code=values["credit_code"], name=values["name"],
            counterparty_type=values["counterparty_type"], industry=values["industry"],
            cooperation_status=values["cooperation_status"], is_key_counterparty=values["is_key_counterparty"],
            requested_limit=Decimal(str(values["requested_limit"])), current_limit=Decimal(str(values["current_limit"])),
            current_payment_term_days=values["current_payment_term_days"], current_rating=values.get("current_rating"),
            current_segment=values.get("current_segment"), external_json=deepcopy(values["external"]),
            internal_json=deepcopy(values["internal"]), financial_json=deepcopy(values["financial"]),
            extensions_json=deepcopy(values["extensions"]), profile_hash="", status="active", source_type="manual",
            created_by=principal.subject, updated_by=principal.subject,
        )
        record.profile_hash = self._profile_hash(record)
        self.session.add(record)
        try:
            self.session.flush()
            self._audit(record, "counterparty_created", principal, reason, before=None, after=self._snapshot(record))
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise CounterpartyError("COUNTERPARTY_ALREADY_EXISTS", "客商编号或统一信用代码已在当前租户登记", 409) from exc
        self.session.refresh(record)
        return self._view(record)

    def update(self, tenant_id: str, counterparty_id: str, payload: dict, principal: "Principal") -> dict:
        record = self._record(tenant_id, counterparty_id)
        self._check_version(record.row_version, payload["expected_row_version"])
        before = self._snapshot(record)
        reason = payload["reason"]
        mappings = {
            "credit_code": "credit_code", "name": "name", "counterparty_type": "counterparty_type",
            "industry": "industry", "cooperation_status": "cooperation_status",
            "is_key_counterparty": "is_key_counterparty", "current_payment_term_days": "current_payment_term_days",
            "current_rating": "current_rating", "current_segment": "current_segment", "external": "external_json",
            "internal": "internal_json", "financial": "financial_json", "extensions": "extensions_json",
        }
        for source, target in mappings.items():
            if source in payload and payload[source] is not None:
                setattr(record, target, deepcopy(payload[source]))
        for field in ("requested_limit", "current_limit"):
            if field in payload and payload[field] is not None:
                setattr(record, field, Decimal(str(payload[field])))
        if payload.get("clear_current_rating"):
            record.current_rating = None
        if payload.get("clear_current_segment"):
            record.current_segment = None
        record.updated_by = principal.subject
        record.profile_hash = self._profile_hash(record)
        if self._snapshot(record) == before:
            raise CounterpartyError("COUNTERPARTY_UNCHANGED", "客商主数据未发生变化", 422)
        self._commit(record, "counterparty_updated", principal, reason, before)
        return self._view(record)

    def archive(self, tenant_id: str, counterparty_id: str, payload: dict, principal: "Principal") -> dict:
        record = self._record(tenant_id, counterparty_id, include_archived=True)
        if record.status == "archived":
            raise CounterpartyError("COUNTERPARTY_ALREADY_ARCHIVED", "客商已归档，不能重复操作", 409)
        self._check_version(record.row_version, payload["expected_row_version"])
        before = self._snapshot(record)
        record.status = "archived"
        record.archived_at = datetime.now(timezone.utc)
        record.archived_by = principal.subject
        record.archive_reason = payload["reason"]
        record.updated_by = principal.subject
        self._commit(record, "counterparty_archived", principal, payload["reason"], before)
        return self._view(record)

    def _record(self, tenant_id: str, counterparty_id: str, *, include_archived: bool = False) -> CounterpartyRecord:
        statement = select(CounterpartyRecord).where(
            CounterpartyRecord.tenant_id == tenant_id,
            CounterpartyRecord.counterparty_id == counterparty_id,
        )
        if not include_archived:
            statement = statement.where(CounterpartyRecord.status == "active")
        record = self.session.scalars(statement).first()
        if record is None:
            raise CounterpartyError("COUNTERPARTY_NOT_FOUND", "客商不存在", 404)
        return record

    @staticmethod
    def _check_version(current: int, expected: int) -> None:
        if current != expected:
            raise CounterpartyError("COUNTERPARTY_VERSION_CONFLICT", "客商主数据已更新，请刷新后重试", 409)

    def _commit(self, record: CounterpartyRecord, event_type: str, principal: "Principal", reason: str, before: dict) -> None:
        try:
            self.session.flush()
            self._audit(record, event_type, principal, reason, before=before, after=self._snapshot(record))
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise CounterpartyError("COUNTERPARTY_ALREADY_EXISTS", "客商编号或统一信用代码已在当前租户登记", 409) from exc
        except StaleDataError as exc:
            self.session.rollback()
            raise CounterpartyError("COUNTERPARTY_VERSION_CONFLICT", "客商主数据已更新，请刷新后重试", 409) from exc
        self.session.refresh(record)

    def _audit(self, record: CounterpartyRecord, event_type: str, principal: "Principal", reason: str, *, before: dict | None, after: dict) -> None:
        self.audit.append(
            "counterparty", f"{record.tenant_id}:{record.counterparty_id}", event_type, principal.subject,
            {"tenant_id": record.tenant_id, "counterparty_id": record.counterparty_id, "actor_name": principal.name,
             "reason": reason, "before": before, "after": after},
        )

    @classmethod
    def _view(cls, record: CounterpartyRecord) -> dict:
        result = deepcopy(record.extensions_json or {})
        result.update({
            "id": record.counterparty_id, "tenant_id": record.tenant_id, "name": record.name,
            "credit_code": record.credit_code, "counterparty_type": record.counterparty_type,
            "industry": record.industry, "cooperation_status": record.cooperation_status,
            "is_key_counterparty": record.is_key_counterparty, "requested_limit": float(record.requested_limit),
            "current_limit": float(record.current_limit), "current_payment_term_days": record.current_payment_term_days,
            "current_rating": record.current_rating, "current_segment": record.current_segment,
            "external": deepcopy(record.external_json or {}), "internal": deepcopy(record.internal_json or {}),
            "financial": deepcopy(record.financial_json or {}), "status": record.status, "source_type": record.source_type,
            "profile_hash": record.profile_hash, "row_version": record.row_version,
            "archived_at": cls._iso(record.archived_at), "archived_by": record.archived_by,
            "archive_reason": record.archive_reason, "created_at": cls._iso(record.created_at),
            "updated_at": cls._iso(record.updated_at),
        })
        return result

    @classmethod
    def _snapshot(cls, record: CounterpartyRecord) -> dict:
        view = cls._view(record)
        return {key: value for key, value in view.items() if key not in {"created_at", "updated_at"}}

    @classmethod
    def _profile_hash(cls, record: CounterpartyRecord) -> str:
        return content_hash({
            "id": record.counterparty_id, "name": record.name, "credit_code": record.credit_code,
            "counterparty_type": record.counterparty_type, "industry": record.industry,
            "cooperation_status": record.cooperation_status, "is_key_counterparty": record.is_key_counterparty,
            "requested_limit": float(record.requested_limit), "current_limit": float(record.current_limit),
            "current_payment_term_days": record.current_payment_term_days, "current_rating": record.current_rating,
            "current_segment": record.current_segment, "external": record.external_json or {},
            "internal": record.internal_json or {}, "financial": record.financial_json or {},
            "extensions": record.extensions_json or {},
        })

    @staticmethod
    def _iso(value: datetime | None) -> str | None:
        return value.isoformat() if value else None
