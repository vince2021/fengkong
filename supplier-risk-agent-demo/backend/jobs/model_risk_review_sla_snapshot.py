"""Persist idempotent daily snapshots for the model-risk review workbench."""
from __future__ import annotations

import json

from sqlalchemy import select

from backend.database import SessionLocal
from backend.db_models import TenantRecord
from backend.model_risk_policy_repository import ModelRiskPolicyRepository


def run_model_risk_review_sla_snapshot(session, tenant_id: str | None = None) -> dict:
    statement = select(TenantRecord.id).where(TenantRecord.status == "active")
    if tenant_id:
        statement = statement.where(TenantRecord.id == tenant_id)
    tenant_ids = sorted(session.scalars(statement).all())
    runs = []
    repository = ModelRiskPolicyRepository(session)
    for current_tenant_id in tenant_ids:
        try:
            snapshot = repository.create_review_sla_snapshot(current_tenant_id)
            runs.append({"tenant_id": current_tenant_id, "status": "completed", "snapshot_id": snapshot["id"]})
        except Exception as exc:
            session.rollback()
            runs.append({"tenant_id": current_tenant_id, "status": "failed", "error_type": type(exc).__name__, "error_code": getattr(exc, "code", None)})
    return {"tenant_count": len(tenant_ids), "failed_count": sum(item["status"] == "failed" for item in runs), "runs": runs}


def main() -> int:
    with SessionLocal() as session:
        result = run_model_risk_review_sla_snapshot(session)
    print(json.dumps(result, ensure_ascii=False))
    return 2 if result["failed_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
