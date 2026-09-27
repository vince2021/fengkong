"""Scan tenant monitoring gates and maintain deduplicated exception notices."""
from __future__ import annotations

import json

from backend.database import SessionLocal
from backend.tenant_outcome_repository import TenantOutcomeRepository


def run_tenant_monitoring_gate_scan(session, tenant_id: str | None = None) -> dict:
    return TenantOutcomeRepository(session).scan_monitoring_gates(tenant_id=tenant_id)


def main() -> int:
    with SessionLocal() as session:
        try:
            result = run_tenant_monitoring_gate_scan(session)
        except Exception as exc:
            result = {
                "scanned_count": 0, "accepted_count": 0, "at_risk_count": 0,
                "blocked_count": 0, "stale_count": 0, "notifications_created": 0,
                "notifications_resolved": 0, "error_type": type(exc).__name__,
                "error_code": getattr(exc, "code", None),
                "error_message": getattr(exc, "message", str(exc)),
            }
            print(json.dumps(result, ensure_ascii=False))
            return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
