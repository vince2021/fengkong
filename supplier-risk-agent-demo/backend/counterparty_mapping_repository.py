"""Tenant-scoped, versioned field mapping templates for counterparty imports."""
from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from backend.db_models import CounterpartyImportMappingTemplateRecord
from backend.repository import AuditRepository, content_hash

if TYPE_CHECKING:
    from backend.security import Principal


class CounterpartyMappingError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class CounterpartyImportMappingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit = AuditRepository(session)

    def list(self, tenant_id: str, status: str | None = "active") -> list[dict]:
        statement = select(CounterpartyImportMappingTemplateRecord).where(
            CounterpartyImportMappingTemplateRecord.tenant_id == tenant_id
        )
        if status:
            statement = statement.where(CounterpartyImportMappingTemplateRecord.status == status)
        rows = self.session.scalars(
            statement.order_by(
                CounterpartyImportMappingTemplateRecord.updated_at.desc(),
                CounterpartyImportMappingTemplateRecord.template_key,
            )
        ).all()
        return [self._view(row) for row in rows]

    def create(self, payload: dict, principal: "Principal") -> dict:
        record = CounterpartyImportMappingTemplateRecord(
            id=str(uuid4()),
            tenant_id=principal.tenant_id,
            template_key=payload["template_key"],
            name=payload["name"],
            file_format=payload["file_format"],
            mapping_json=deepcopy(payload["mapping"]),
            description=payload["description"],
            status="active",
            created_by=principal.subject,
            updated_by=principal.subject,
        )
        self.session.add(record)
        self._commit(record, "counterparty_import_mapping_created", principal, payload["reason"], before=None)
        return self._view(record)

    def update(self, tenant_id: str, template_id: str, payload: dict, principal: "Principal") -> dict:
        record = self._record(tenant_id, template_id)
        self._check_version(record.row_version, payload["expected_row_version"])
        if record.status != "active":
            raise CounterpartyMappingError("COUNTERPARTY_MAPPING_ARCHIVED", "已归档字段映射模板不能修改", 409)
        before = self._snapshot(record)
        for source, target in (("name", "name"), ("file_format", "file_format"), ("description", "description")):
            if payload.get(source) is not None:
                setattr(record, target, payload[source])
        if payload.get("mapping") is not None:
            record.mapping_json = deepcopy(payload["mapping"])
        record.updated_by = principal.subject
        if self._snapshot(record) == before:
            raise CounterpartyMappingError("COUNTERPARTY_MAPPING_UNCHANGED", "字段映射模板未发生变化", 422)
        self._commit(record, "counterparty_import_mapping_updated", principal, payload["reason"], before=before)
        return self._view(record)

    def archive(self, tenant_id: str, template_id: str, payload: dict, principal: "Principal") -> dict:
        record = self._record(tenant_id, template_id)
        self._check_version(record.row_version, payload["expected_row_version"])
        if record.status == "archived":
            raise CounterpartyMappingError("COUNTERPARTY_MAPPING_ALREADY_ARCHIVED", "字段映射模板已归档", 409)
        before = self._snapshot(record)
        record.status = "archived"
        record.updated_by = principal.subject
        self._commit(record, "counterparty_import_mapping_archived", principal, payload["reason"], before=before)
        return self._view(record)

    def _record(self, tenant_id: str, template_id: str) -> CounterpartyImportMappingTemplateRecord:
        record = self.session.scalars(
            select(CounterpartyImportMappingTemplateRecord).where(
                CounterpartyImportMappingTemplateRecord.tenant_id == tenant_id,
                CounterpartyImportMappingTemplateRecord.id == template_id,
            )
        ).first()
        if record is None:
            raise CounterpartyMappingError("COUNTERPARTY_MAPPING_NOT_FOUND", "字段映射模板不存在", 404)
        return record

    @staticmethod
    def _check_version(current: int, expected: int) -> None:
        if current != expected:
            raise CounterpartyMappingError("COUNTERPARTY_MAPPING_VERSION_CONFLICT", "字段映射模板已更新，请刷新后重试", 409)

    def _commit(
        self,
        record: CounterpartyImportMappingTemplateRecord,
        event_type: str,
        principal: "Principal",
        reason: str,
        *,
        before: dict | None,
    ) -> None:
        try:
            self.session.flush()
            after = self._snapshot(record)
            self.audit.append(
                "counterparty_import_mapping",
                f"{record.tenant_id}:{record.template_key}",
                event_type,
                principal.subject,
                {
                    "tenant_id": record.tenant_id,
                    "template_key": record.template_key,
                    "actor_name": principal.name,
                    "reason": reason,
                    "before": before,
                    "after": after,
                },
            )
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise CounterpartyMappingError("COUNTERPARTY_MAPPING_ALREADY_EXISTS", "字段映射模板编号已在当前租户登记", 409) from exc
        except StaleDataError as exc:
            self.session.rollback()
            raise CounterpartyMappingError("COUNTERPARTY_MAPPING_VERSION_CONFLICT", "字段映射模板已更新，请刷新后重试", 409) from exc
        self.session.refresh(record)

    @classmethod
    def _snapshot(cls, record: CounterpartyImportMappingTemplateRecord) -> dict:
        return {
            "template_key": record.template_key,
            "name": record.name,
            "file_format": record.file_format,
            "mapping": deepcopy(record.mapping_json or {}),
            "mapping_hash": content_hash(record.mapping_json or {}),
            "description": record.description,
            "status": record.status,
            "updated_by": record.updated_by,
            "row_version": record.row_version,
        }

    @classmethod
    def _view(cls, record: CounterpartyImportMappingTemplateRecord) -> dict:
        iso = lambda value: value.isoformat() if value else None
        return {
            "id": record.id,
            "tenant_id": record.tenant_id,
            **cls._snapshot(record),
            "created_by": record.created_by,
            "created_at": iso(record.created_at),
            "updated_at": iso(record.updated_at),
        }
