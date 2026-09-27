"""Daily tenant model-risk review reminders; invoke with an external scheduler."""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.db_models import ModelRiskAcceptanceRecord, ModelRiskReacceptanceRecord
from backend.model_risk_policy_repository import ModelRiskPolicyRepository


def run_model_risk_review_scan(session: Session) -> dict:
    acceptance_tenants = session.scalars(select(ModelRiskAcceptanceRecord.tenant_id).where(
        ModelRiskAcceptanceRecord.status == "accepted",
    ).distinct()).all()
    reacceptance_tenants = session.scalars(select(ModelRiskReacceptanceRecord.tenant_id).where(
        ModelRiskReacceptanceRecord.status == "accepted",
    ).distinct()).all()
    tenant_ids = sorted(set(acceptance_tenants) | set(reacceptance_tenants))
    repository = ModelRiskPolicyRepository(session)
    runs = []
    for tenant_id in tenant_ids:
        try:
            acceptance = repository.scan_reviews(tenant_id, "system:model-risk-review-scheduler")
            reacceptance = repository.scan_reacceptance_reviews(tenant_id, "system:model-risk-review-scheduler")
            runs.append({"tenant_id": tenant_id, "status": "completed", "acceptance": acceptance,
                         "reacceptance": reacceptance})
        except Exception as exc:
            session.rollback()
            runs.append({"tenant_id": tenant_id, "status": "failed", "error_type": type(exc).__name__})
    return {"tenant_count": len(tenant_ids), "failed_count": sum(run["status"] == "failed" for run in runs), "runs": runs}


def main() -> int:
    with SessionLocal() as session:
        result = run_model_risk_review_scan(session)
    print(json.dumps(result, ensure_ascii=False))
    return 2 if result["failed_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
