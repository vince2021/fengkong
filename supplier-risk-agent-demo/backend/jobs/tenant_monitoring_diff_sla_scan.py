"""Scan monitoring-difference case SLA stages and maintain tenant notifications."""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.db_models import TenantMonitoringDiffCaseRecord
from backend.tenant_outcome_repository import TenantOutcomeRepository


def run_tenant_monitoring_diff_sla_scan(session: Session, tenant_id: str | None = None) -> dict:
    statement = select(TenantMonitoringDiffCaseRecord.tenant_id).where(
        TenantMonitoringDiffCaseRecord.status.in_(("open", "assigned", "recomputing", "pending_disposition")),
    ).distinct()
    if tenant_id:
        statement = statement.where(TenantMonitoringDiffCaseRecord.tenant_id == tenant_id)
    tenant_ids = sorted(session.scalars(statement).all())
    repository = TenantOutcomeRepository(session)
    runs = []
    for current_tenant_id in tenant_ids:
        try:
            result = repository.scan_monitoring_diff_case_sla(current_tenant_id)
            runs.append({"tenant_id": current_tenant_id, "status": "completed", **result})
        except Exception as exc:
            session.rollback()
            runs.append({
                "tenant_id": current_tenant_id, "status": "failed",
                "error_type": type(exc).__name__, "error_code": getattr(exc, "code", None),
            })
    return {
        "tenant_count": len(tenant_ids),
        "failed_count": sum(item["status"] == "failed" for item in runs),
        "runs": runs,
    }


def main() -> int:
    with SessionLocal() as session:
        result = run_tenant_monitoring_diff_sla_scan(session)
    print(json.dumps(result, ensure_ascii=False))
    return 2 if result["failed_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
