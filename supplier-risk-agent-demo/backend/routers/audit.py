from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.dependencies import get_audit_repository
from backend.repository import AuditRepository
from backend.security import Principal, require_permissions


router = APIRouter(prefix="/audit-events", tags=["audit"])


@router.get("")
def list_audit_events(
    aggregate_id: str | None = None,
    repository: AuditRepository = Depends(get_audit_repository),
    principal: Principal = Depends(require_permissions("audit:view")),
) -> list[dict]:
    return repository.list(aggregate_id)
