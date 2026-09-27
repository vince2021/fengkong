"""Periodic tenant rollout evaluation and safe observation-window closure."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.db_models import TenantRolloutPolicyRecord
from backend.dependencies import demo_repository
from backend.security import Principal
from backend.tenant_rollout_repository import TenantRolloutRepository


SCHEDULER_PRINCIPAL = Principal(
    subject="system:tenant-rollout-scheduler", name="租户灰度周期扫描器",
    roles=("admin",), permissions=frozenset({"*"}),
    tenant_id="tenant-platform-internal", client_id="system-scheduler",
)


def run_tenant_rollout_scan(session: Session, now: datetime | None = None, run_key: str | None = None) -> dict:
    scan_at = now or datetime.now(timezone.utc)
    tenant_ids = session.scalars(select(TenantRolloutPolicyRecord.tenant_id).where(
        TenantRolloutPolicyRecord.status.in_(("scheduled", "active")),
    ).distinct().order_by(TenantRolloutPolicyRecord.tenant_id)).all()
    repository = TenantRolloutRepository(session, demo_repository)
    runs = [repository.scan(tenant_id, SCHEDULER_PRINCIPAL, now=scan_at,
                            run_key=f"{run_key}:{tenant_id}" if run_key else None,
                            trigger_type="scheduler") for tenant_id in tenant_ids]
    return {"tenant_count": len(tenant_ids), "runs": runs, "failed_count": sum(
        run["run"]["status"] in {"partial", "failed"} for run in runs
    )}


def main() -> int:
    with SessionLocal() as session:
        result = run_tenant_rollout_scan(session)
    print(json.dumps(result, ensure_ascii=False))
    return 2 if result["failed_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
