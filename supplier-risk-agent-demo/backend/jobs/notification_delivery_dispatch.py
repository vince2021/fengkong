"""Dispatch tenant notification outboxes with per-tenant failure isolation."""
from __future__ import annotations

import json

from sqlalchemy import select

from backend.database import SessionLocal
from backend.db_models import TenantNotificationChannelRecord, TenantRecord
from backend.notification_delivery_repository import NotificationDeliveryRepository


def run_notification_delivery_dispatch(session, tenant_id: str | None = None, limit: int = 200) -> dict:
    statement = select(TenantRecord.id).join(
        TenantNotificationChannelRecord,
        TenantNotificationChannelRecord.tenant_id == TenantRecord.id,
    ).where(
        TenantRecord.status == "active",
        TenantNotificationChannelRecord.status == "active",
    ).distinct()
    if tenant_id:
        statement = statement.where(TenantRecord.id == tenant_id)
    tenant_ids = sorted(session.scalars(statement).all())
    runs = []
    repository = NotificationDeliveryRepository(session)
    for current_tenant_id in tenant_ids:
        try:
            result = repository.scan_and_dispatch(
                current_tenant_id, "system:notification-delivery-dispatch", limit=limit,
            )
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
        result = run_notification_delivery_dispatch(session)
    print(json.dumps(result, ensure_ascii=False))
    return 2 if result["failed_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
