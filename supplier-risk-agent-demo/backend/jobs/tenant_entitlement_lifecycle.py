from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.product_package_repository import (
    DEFAULT_ENTITLEMENT_SCAN_INTERVAL_MINUTES,
    ProductPackageRepository,
    entitlement_lifecycle_run_key,
)
from backend.security import Principal


SCHEDULER_PRINCIPAL = Principal(
    subject="system:tenant-entitlement-scheduler",
    name="租户授权自动调度器",
    roles=("admin",),
    permissions=frozenset({"*"}),
    tenant_id="tenant-platform-internal",
    client_id="system-scheduler",
)


def run_tenant_entitlement_lifecycle(
    session: Session,
    now: datetime | None = None,
    run_key: str | None = None,
    interval_minutes: int = DEFAULT_ENTITLEMENT_SCAN_INTERVAL_MINUTES,
) -> dict:
    run_at = now or datetime.now(timezone.utc)
    return ProductPackageRepository(session).run_entitlement_lifecycle(
        principal=SCHEDULER_PRINCIPAL,
        now=run_at,
        run_key=run_key or entitlement_lifecycle_run_key(run_at, interval_minutes),
        trigger_type="scheduler",
    )


def main() -> int:
    with SessionLocal() as session:
        result = run_tenant_entitlement_lifecycle(session)
    print(json.dumps(result, ensure_ascii=False))
    return 2 if result["run"]["failed_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
