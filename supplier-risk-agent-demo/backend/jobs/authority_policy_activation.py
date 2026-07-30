from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.authority_policy_repository import (
    AuthorityPolicyRepository,
    DEFAULT_ACTIVATION_SCAN_INTERVAL_MINUTES,
    authority_policy_scheduler_run_key,
)
from backend.database import SessionLocal


SCHEDULER_SUBJECT = "system:authority-policy-scheduler"
SCHEDULER_NAME = "授权策略自动调度器"


def run_authority_policy_activation(
    session: Session,
    now: datetime | None = None,
    run_key: str | None = None,
    interval_minutes: int = DEFAULT_ACTIVATION_SCAN_INTERVAL_MINUTES,
) -> dict:
    run_at = now or datetime.now(timezone.utc)
    return AuthorityPolicyRepository(session).activate_due(
        SCHEDULER_SUBJECT,
        SCHEDULER_NAME,
        now=run_at,
        run_key=run_key or authority_policy_scheduler_run_key(run_at, interval_minutes),
        trigger_type="scheduler",
    )


def main() -> int:
    with SessionLocal() as session:
        result = run_authority_policy_activation(session)
    print(json.dumps(result, ensure_ascii=False))
    return 2 if result["run"]["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
