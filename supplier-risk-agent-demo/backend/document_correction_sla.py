from __future__ import annotations

from datetime import datetime, timedelta, timezone


ACTIVE_CORRECTION_STATUSES = {"open", "resubmitted"}
CORRECTION_ESCALATION_AFTER_SECONDS = 4 * 3600
MIN_MANUAL_REMINDER_INTERVAL_SECONDS = 30 * 60
MAX_CORRECTION_EXTENSION_COUNT = 3
MAX_TOTAL_CORRECTION_EXTENSION_HOURS = 7 * 24
CORRECTION_SLA_HOURS = {
    "open": 48,
    "resubmitted": 24,
}
CORRECTION_ASSIGNED_ROLES = {
    "open": "relationship_manager",
    "resubmitted": "risk_manager",
}


def correction_sla_window(status: str, started_at: datetime) -> tuple[str, datetime, datetime]:
    if status not in ACTIVE_CORRECTION_STATUSES:
        raise ValueError(f"补件状态 {status} 不支持启动 SLA")
    started_at = as_utc(started_at)
    return (
        CORRECTION_ASSIGNED_ROLES[status],
        started_at,
        started_at + timedelta(hours=CORRECTION_SLA_HOURS[status]),
    )


def correction_sla_snapshot(
    status: str,
    due_at: datetime | None,
    now: datetime | None = None,
) -> dict:
    if status not in ACTIVE_CORRECTION_STATUSES or not due_at:
        return {"sla_status": "stopped", "remaining_seconds": 0}
    scan_time = as_utc(now or datetime.now(timezone.utc))
    remaining = int((as_utc(due_at) - scan_time).total_seconds())
    if remaining <= -CORRECTION_ESCALATION_AFTER_SECONDS:
        level = "escalated"
    elif remaining < 0:
        level = "overdue"
    else:
        warning_seconds = CORRECTION_SLA_HOURS[status] * 3600 * 0.25
        level = "due_soon" if remaining <= warning_seconds else "normal"
    return {"sla_status": level, "remaining_seconds": remaining}


def as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
