from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db_session
from backend.security import Principal, require_permissions
from backend.sla_monitor import build_operations_summary, run_sla_scan


router = APIRouter(prefix="/operations", tags=["operations"])


@router.get("/sla/summary")
def sla_summary(
    session: Session = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("operations:view")),
) -> dict:
    return build_operations_summary(session)


@router.post("/sla/scan")
def scan_sla(
    session: Session = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("sla:scan")),
) -> dict:
    return run_sla_scan(session, actor=principal.name)
