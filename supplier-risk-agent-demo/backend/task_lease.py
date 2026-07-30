from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol


TASK_ASSIGNMENT_LEASE_HOURS = 4


class TaskLeaseRecord(Protocol):
    assigned_to: str | None
    assigned_to_name: str | None
    assigned_at: datetime | None
    assignment_expires_at: datetime | None


def assignment_expiry(record: TaskLeaseRecord) -> datetime | None:
    if record.assignment_expires_at:
        return _as_utc(record.assignment_expires_at)
    if record.assigned_at:
        return _as_utc(record.assigned_at) + timedelta(hours=TASK_ASSIGNMENT_LEASE_HOURS)
    return None


def assignment_is_active(record: TaskLeaseRecord, now: datetime | None = None) -> bool:
    return assignment_values_are_active(
        record.assigned_to,
        record.assignment_expires_at,
        record.assigned_at,
        now,
    )


def assignment_values_are_active(
    assigned_to: str | None,
    assignment_expires_at: datetime | str | None,
    assigned_at: datetime | str | None = None,
    now: datetime | None = None,
) -> bool:
    if not assigned_to:
        return False
    expires_at = _parse_datetime(assignment_expires_at)
    if not expires_at:
        started_at = _parse_datetime(assigned_at)
        expires_at = started_at + timedelta(hours=TASK_ASSIGNMENT_LEASE_HOURS) if started_at else None
    return bool(expires_at and expires_at > _as_utc(now or datetime.now(timezone.utc)))


def assignment_is_expired(record: TaskLeaseRecord, now: datetime | None = None) -> bool:
    return bool(record.assigned_to and not assignment_is_active(record, now))


def start_assignment_lease(record: TaskLeaseRecord, now: datetime | None = None) -> datetime:
    assigned_at = _as_utc(now or datetime.now(timezone.utc))
    record.assigned_at = assigned_at
    record.assignment_expires_at = assigned_at + timedelta(hours=TASK_ASSIGNMENT_LEASE_HOURS)
    return record.assignment_expires_at


def renew_assignment_lease(record: TaskLeaseRecord, now: datetime | None = None) -> datetime:
    renewed_at = _as_utc(now or datetime.now(timezone.utc))
    record.assignment_expires_at = renewed_at + timedelta(hours=TASK_ASSIGNMENT_LEASE_HOURS)
    return record.assignment_expires_at


def clear_assignment(record: TaskLeaseRecord) -> None:
    record.assigned_to = None
    record.assigned_to_name = None
    record.assigned_at = None
    record.assignment_expires_at = None


def lease_remaining_seconds(record: TaskLeaseRecord, now: datetime | None = None) -> int | None:
    if not assignment_is_active(record, now):
        return None
    expires_at = assignment_expiry(record)
    return max(0, int((expires_at - _as_utc(now or datetime.now(timezone.utc))).total_seconds())) if expires_at else None


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _parse_datetime(value: datetime | str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    return _as_utc(parsed)
