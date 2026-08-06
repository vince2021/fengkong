from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from backend.credit_authority import authority_has_signer, authority_owner_roles
from backend.db_models import (
    ApprovalCaseRecord,
    AuditEventRecord,
    CreditFacilityRecord,
    DocumentCorrectionRecord,
    FacilityControlConditionRecord,
    FacilityControlExtensionRecord,
    NotificationRecord,
    SlaScanLeaseRecord,
)
from backend.document_correction_sla import ACTIVE_CORRECTION_STATUSES, correction_sla_snapshot
from backend.repository import AuditRepository, CreditFacilityRepository, NotificationRepository
from backend.security import APPROVAL_STAGE_ROLES
from backend.task_lease import assignment_expiry, assignment_is_active, assignment_is_expired, clear_assignment, lease_remaining_seconds
from rating.approval_workflow import STAGE_SLA_HOURS, stage_label


ACTIVE_STATUSES = {"处理中", "待补件"}
SLA_SCANNABLE_STATUSES = {"处理中"}
ESCALATION_AFTER_SECONDS = 4 * 3600
ASSIGNMENT_LEASE_WARNING_SECONDS = 30 * 60
SLA_SCAN_EXPECTED_CADENCE_MINUTES = 5
SLA_SCAN_STALE_AFTER_MINUTES = 15
SLA_SCAN_EXECUTION_TIMEOUT_MINUTES = 10
SLA_SCAN_LEASE_HARD_EXPIRY_MINUTES = 30
SLA_SCAN_HEARTBEAT_INTERVAL_SECONDS = 60
SLA_SCAN_GUARD_BATCH_SIZE = 25
SLA_SCAN_LEASE_KEY = "global-sla-scan"


def run_sla_scan(
    session: Session,
    now: datetime | None = None,
    actor: str = "sla-monitor",
    run_key: str | None = None,
    trigger_type: str = "manual",
    lease_guard: Callable[[bool], None] | None = None,
) -> dict:
    scan_time = _as_utc(now or datetime.now(timezone.utc))
    if trigger_type not in {"manual", "scheduler", "retry"}:
        raise ValueError("SLA 扫描触发类型必须为 manual、scheduler 或 retry")
    if trigger_type in {"scheduler", "retry"}:
        if trigger_type == "retry" and run_key is None:
            raise ValueError("人工重试必须指定原调度任务键")
        scan_run_id = sla_scan_scheduler_run_key(scan_time) if run_key is None else run_key
        if not 1 <= len(scan_run_id) <= 128:
            raise ValueError("SLA 扫描任务键长度必须为 1—128 个字符")
        existing = _find_sla_scan_run(session, scan_run_id)
        if existing:
            return _deduplicated_scan_result(existing)
    else:
        if run_key is not None:
            raise ValueError("人工 SLA 扫描不能指定调度任务键")
        scan_run_id = str(uuid4())
    _ensure_scan_write_transaction(session)
    cases = session.scalars(
        select(ApprovalCaseRecord).where(
            ApprovalCaseRecord.status.in_(SLA_SCANNABLE_STATUSES),
            ApprovalCaseRecord.stage_due_at.is_not(None),
        )
    ).all()
    corrections = session.scalars(
        select(DocumentCorrectionRecord).where(
            DocumentCorrectionRecord.status.in_(ACTIVE_CORRECTION_STATUSES),
            DocumentCorrectionRecord.sla_due_at.is_not(None),
        )
    ).all()
    if lease_guard:
        lease_guard(False)
    notifications = NotificationRepository(session)
    audit = AuditRepository(session)
    level_counts: Counter[str] = Counter()
    correction_level_counts: Counter[str] = Counter()
    created_count = _notify_due_assignment_leases(cases, corrections, scan_time, notifications, audit, actor)
    expired_assignments_released, expired_notifications_created = _release_expired_assignments(
        cases,
        corrections,
        scan_time,
        notifications,
        audit,
        actor,
    )
    created_count += expired_notifications_created
    if lease_guard:
        lease_guard(False)

    for index, case in enumerate(cases):
        if lease_guard and index and index % SLA_SCAN_GUARD_BATCH_SIZE == 0:
            lease_guard(False)
        level = _sla_level(case, scan_time)
        if not level:
            continue
        level_counts[level] += 1
        roles = _recipient_roles(case, level)
        created_for_case = []
        for role in sorted(roles):
            _, created = notifications.create_if_absent(_notification_payload(case, role, level))
            if created:
                created_count += 1
                created_for_case.append(role)
        if created_for_case:
            audit.append(
                "approval_case",
                case.case_id,
                f"sla_{level}_notification_generated",
                actor,
                {"stage": case.current_stage, "sla_level": level, "recipient_roles": created_for_case, "stage_due_at": _as_utc(case.stage_due_at).isoformat()},
            )

    if lease_guard:
        lease_guard(False)
    for index, correction in enumerate(corrections):
        if lease_guard and index and index % SLA_SCAN_GUARD_BATCH_SIZE == 0:
            lease_guard(False)
        snapshot = correction_sla_snapshot(correction.status, correction.sla_due_at, scan_time)
        level = snapshot["sla_status"]
        if level == "normal":
            continue
        correction_level_counts[level] += 1
        if not correction.case_id:
            continue
        created_for_correction = []
        for role in sorted(_correction_recipient_roles(correction, level)):
            _, created = notifications.create_if_absent(_correction_notification_payload(correction, role, level))
            if created:
                created_count += 1
                created_for_correction.append(role)
        if created_for_correction:
            audit.append(
                "document_correction",
                correction.id,
                f"correction_sla_{level}_notification_generated",
                actor,
                {
                    "case_id": correction.case_id,
                    "status": correction.status,
                    "sla_level": level,
                    "assigned_role": correction.assigned_role,
                    "recipient_roles": created_for_correction,
                    "sla_due_at": _as_utc(correction.sla_due_at).isoformat(),
                },
            )

    if lease_guard:
        lease_guard(False)
    post_credit_scan = CreditFacilityRepository(session).scan(actor, now=scan_time, commit=False)
    failure_notifications_resolved = (
        _resolve_scan_failure_notifications(session, audit, actor, scan_time, scan_run_id)
        if trigger_type in {"scheduler", "retry"}
        else 0
    )
    result = {
        "run_id": scan_run_id,
        "run_key": scan_run_id if trigger_type == "scheduler" else None,
        "run_at": scan_time.isoformat(),
        "trigger_type": trigger_type,
        "status": "completed",
        "deduplicated": False,
        "active_cases_scanned": len(cases),
        "due_soon_cases": level_counts["due_soon"],
        "overdue_cases": level_counts["overdue"],
        "escalated_cases": level_counts["escalated"],
        "active_corrections_scanned": len(corrections),
        "due_soon_corrections": correction_level_counts["due_soon"],
        "overdue_corrections": correction_level_counts["overdue"],
        "escalated_corrections": correction_level_counts["escalated"],
        "workflow_notifications_created": created_count,
        "notifications_created": created_count + post_credit_scan["control_notifications_created"],
        "expired_assignments_released": expired_assignments_released,
        "active_facilities_scanned": post_credit_scan["active_facilities_scanned"],
        "facilities_expired": post_credit_scan["facilities_expired"],
        "facility_alerts_opened": post_credit_scan["alerts_opened"],
        "control_conditions_scanned": post_credit_scan["control_conditions_scanned"],
        "control_alerts_opened": post_credit_scan["control_alerts_opened"],
        "control_conditions_escalated": post_credit_scan["control_conditions_escalated"],
        "control_notifications_created": post_credit_scan["control_notifications_created"],
        "failure_notifications_resolved": failure_notifications_resolved,
    }
    if lease_guard:
        lease_guard(True)
    audit_event, created = audit.append_root_once("sla_scan", result["run_id"], "sla_scan_completed", actor, result)
    if not created:
        session.rollback()
        return _deduplicated_scan_result_from_payload(audit_event["payload"])
    session.commit()
    return result


def _ensure_scan_write_transaction(session: Session) -> None:
    if session.get_bind().dialect.name == "sqlite":
        connection = session.connection()
        driver_connection = getattr(connection.connection, "driver_connection", None)
        if not getattr(driver_connection, "in_transaction", False):
            connection.exec_driver_sql("BEGIN IMMEDIATE")


def sla_scan_scheduler_run_key(
    value: datetime | None = None,
) -> str:
    current = _as_utc(value or datetime.now(timezone.utc))
    bucket_seconds = SLA_SCAN_EXPECTED_CADENCE_MINUTES * 60
    timestamp = int(current.timestamp())
    bucket = datetime.fromtimestamp(timestamp - timestamp % bucket_seconds, tz=timezone.utc)
    return f"sla-scheduler:{bucket.strftime('%Y%m%dT%H%MZ')}:{SLA_SCAN_EXPECTED_CADENCE_MINUTES}m"


def _find_sla_scan_run(session: Session, run_id: str) -> AuditEventRecord | None:
    return session.scalars(
        select(AuditEventRecord).where(
            AuditEventRecord.aggregate_type == "sla_scan",
            AuditEventRecord.aggregate_id == run_id,
            AuditEventRecord.event_type == "sla_scan_completed",
        )
    ).first()


def _deduplicated_scan_result(record: AuditEventRecord) -> dict:
    return _deduplicated_scan_result_from_payload(record.payload or {})


def _deduplicated_scan_result_from_payload(payload: dict) -> dict:
    result = dict(payload)
    result["deduplicated"] = True
    return result


def _resolve_scan_failure_notifications(
    session: Session,
    audit: AuditRepository,
    actor: str,
    resolved_at: datetime,
    recovery_run_id: str,
) -> int:
    records = session.scalars(
        select(NotificationRecord).where(
            NotificationRecord.category == "sla_scan",
            NotificationRecord.level == "scan_failed",
            NotificationRecord.status != "resolved",
        )
    ).all()
    for record in records:
        record.status = "resolved"
        record.read_at = record.read_at or resolved_at
        audit.append(
            "notification",
            record.id,
            "sla_scan_failure_notification_auto_resolved",
            actor,
            {
                "recovery_run_id": recovery_run_id,
                "resolved_at": resolved_at.isoformat(),
            },
        )
    return len(records)


def list_sla_scan_runs(session: Session, limit: int = 20, now: datetime | None = None) -> dict:
    generated_at = _as_utc(now or datetime.now(timezone.utc))
    execution_history = _list_sla_scan_executions(session, generated_at, limit)
    execution_lease = _sla_scan_lease_snapshot(session, generated_at)
    records = session.scalars(
        select(AuditEventRecord)
        .where(
            or_(
                and_(
                    AuditEventRecord.aggregate_type == "sla_scan",
                    AuditEventRecord.event_type == "sla_scan_completed",
                ),
                and_(
                    AuditEventRecord.aggregate_type == "sla_scan_failure",
                    AuditEventRecord.event_type == "sla_scan_failed",
                ),
            )
        )
        .order_by(
            AuditEventRecord.payload["run_at"].as_string().desc(),
            (AuditEventRecord.event_type == "sla_scan_completed").desc(),
            AuditEventRecord.created_at.desc(),
            AuditEventRecord.id.desc(),
        )
        .limit(limit + 1)
    ).all()
    latest_scheduler_record = session.scalars(
        select(AuditEventRecord)
        .where(
            or_(
                and_(
                    AuditEventRecord.aggregate_type == "sla_scan",
                    AuditEventRecord.event_type == "sla_scan_completed",
                ),
                and_(
                    AuditEventRecord.aggregate_type == "sla_scan_failure",
                    AuditEventRecord.event_type == "sla_scan_failed",
                ),
            ),
            AuditEventRecord.payload["trigger_type"].as_string() == "scheduler",
        )
        .order_by(
            AuditEventRecord.payload["run_at"].as_string().desc(),
            (AuditEventRecord.event_type == "sla_scan_completed").desc(),
            AuditEventRecord.created_at.desc(),
            AuditEventRecord.id.desc(),
        )
        .limit(1)
    ).first()
    normalized = [_sla_scan_event_to_dict(record) for record in records]
    _attach_sla_scan_retry_history(session, normalized)
    runs = normalized[:limit]
    for index, run in enumerate(runs):
        previous = next(
            (item for item in normalized[index + 1:] if item["status"] == "completed"),
            None,
        )
        if run["status"] == "failed":
            previous = None
        run["notification_delta"] = _scan_metric_delta(run, previous, "notifications_created")
        run["alert_delta"] = _scan_metric_delta(run, previous, "alerts_opened")
        run["escalation_delta"] = _scan_metric_delta(run, previous, "escalations_triggered")
        run["risk_action_delta"] = _scan_metric_delta(run, previous, "risk_actions_created")
        run["risk_increased"] = previous is not None and run["risk_action_delta"] > 0

    latest_at = _parse_scan_time(runs[0]["run_at"]) if runs else None
    minutes_since_last_run = (
        max(0, int((generated_at - latest_at).total_seconds() // 60))
        if latest_at
        else None
    )
    health = (
        "never"
        if latest_at is None
        else "blocked"
        if runs[0]["status"] == "failed"
        else "healthy"
        if minutes_since_last_run <= SLA_SCAN_STALE_AFTER_MINUTES
        else "stale"
    )
    short_interval_runs = sum(
        1
        for current, previous in zip(runs, runs[1:])
        if _scan_interval_minutes(current, previous) < SLA_SCAN_EXPECTED_CADENCE_MINUTES
    )
    missed_intervals = (
        max(0, minutes_since_last_run // SLA_SCAN_EXPECTED_CADENCE_MINUTES - 1)
        if minutes_since_last_run is not None
        else 0
    )
    scheduler_runs = [item for item in runs if item["trigger_type"] == "scheduler"]
    latest_scheduler_run = _sla_scan_event_to_dict(latest_scheduler_record) if latest_scheduler_record else None
    if latest_scheduler_run:
        _attach_sla_scan_retry_history(session, [latest_scheduler_run])
    latest_scheduler_at = _parse_scan_time(latest_scheduler_run["run_at"]) if latest_scheduler_run else None
    scheduler_minutes_since_last_run = (
        max(0, int((generated_at - latest_scheduler_at).total_seconds() // 60))
        if latest_scheduler_at
        else None
    )
    scheduler_health = (
        "never"
        if latest_scheduler_at is None
        else "blocked"
        if latest_scheduler_run["status"] == "failed" and not latest_scheduler_run["recovered"]
        else "healthy"
        if scheduler_minutes_since_last_run <= SLA_SCAN_STALE_AFTER_MINUTES
        else "stale"
    )
    scheduler_missed_intervals = (
        max(0, scheduler_minutes_since_last_run // SLA_SCAN_EXPECTED_CADENCE_MINUTES - 1)
        if scheduler_minutes_since_last_run is not None
        else 0
    )
    return {
        "generated_at": generated_at.isoformat(),
        "health": health,
        "expected_cadence_minutes": SLA_SCAN_EXPECTED_CADENCE_MINUTES,
        "stale_after_minutes": SLA_SCAN_STALE_AFTER_MINUTES,
        "execution_timeout_minutes": SLA_SCAN_EXECUTION_TIMEOUT_MINUTES,
        "execution_lease_expiry_minutes": SLA_SCAN_LEASE_HARD_EXPIRY_MINUTES,
        "execution_heartbeat_interval_seconds": SLA_SCAN_HEARTBEAT_INTERVAL_SECONDS,
        "execution_summary": execution_history["summary"],
        "execution_lease": execution_lease,
        "executions": execution_history["executions"],
        "scheduler_health": {
            "state": scheduler_health,
            "last_run_at": latest_scheduler_run["run_at"] if latest_scheduler_run else None,
            "last_status": ("completed" if latest_scheduler_run and latest_scheduler_run["recovered"] else latest_scheduler_run["status"]) if latest_scheduler_run else None,
            "recovered": latest_scheduler_run["recovered"] if latest_scheduler_run else False,
            "error_type": latest_scheduler_run["error_type"] if latest_scheduler_run else None,
            "error_message": latest_scheduler_run["error_message"] if latest_scheduler_run else None,
            "next_expected_run_at": (
                (latest_scheduler_at + timedelta(minutes=SLA_SCAN_EXPECTED_CADENCE_MINUTES)).isoformat()
                if latest_scheduler_at
                else None
            ),
            "minutes_since_last_run": scheduler_minutes_since_last_run,
            "missed_intervals": scheduler_missed_intervals,
        },
        "summary": {
            "returned_runs": len(runs),
            "scheduler_runs": len(scheduler_runs),
            "manual_runs": sum(item["trigger_type"] == "manual" for item in runs),
            "retry_runs": sum(item["trigger_type"] == "retry" for item in runs),
            "legacy_runs": sum(item["trigger_type"] == "legacy" for item in runs),
            "failed_runs": sum(item["status"] == "failed" for item in runs),
            "last_run_at": runs[0]["run_at"] if runs else None,
            "minutes_since_last_run": minutes_since_last_run,
            "missed_intervals": missed_intervals,
            "short_interval_runs": short_interval_runs,
            "runs_with_new_risk": sum(item["risk_actions_created"] > 0 for item in runs),
            "total_notifications": sum(item["notifications_created"] for item in runs),
            "total_alerts": sum(item["alerts_opened"] for item in runs),
            "total_escalations": sum(item["escalations_triggered"] for item in runs),
        },
        "runs": runs,
    }


def _list_sla_scan_executions(session: Session, generated_at: datetime, limit: int) -> dict:
    starts = session.scalars(
        select(AuditEventRecord)
        .where(
            AuditEventRecord.aggregate_type == "sla_scan_execution",
            AuditEventRecord.event_type == "sla_scan_started",
        )
        .order_by(
            AuditEventRecord.payload["started_at"].as_string().desc(),
            AuditEventRecord.created_at.desc(),
            AuditEventRecord.id.desc(),
        )
        .limit(limit)
    ).all()
    execution_ids = [record.aggregate_id for record in starts]
    terminal_events = session.scalars(
        select(AuditEventRecord)
        .where(
            AuditEventRecord.aggregate_type == "sla_scan_execution",
            AuditEventRecord.aggregate_id.in_(execution_ids),
            AuditEventRecord.event_type.in_({
                "sla_scan_execution_completed",
                "sla_scan_execution_failed",
                "sla_scan_execution_timed_out",
                "sla_scan_execution_force_released",
                "sla_scan_execution_aborted",
                "sla_scan_execution_late_aborted",
                "sla_scan_execution_late_completed",
                "sla_scan_execution_late_failed",
            }),
        )
        .order_by(
            AuditEventRecord.payload["finished_at"].as_string(),
            AuditEventRecord.created_at,
            AuditEventRecord.id,
        )
    ).all() if execution_ids else []
    terminal_by_execution = {record.aggregate_id: record for record in terminal_events}
    executions: list[dict] = []
    for start in starts:
        start_payload = start.payload or {}
        terminal = terminal_by_execution.get(start.aggregate_id)
        terminal_payload = terminal.payload or {} if terminal else {}
        started_at = _parse_scan_time(start_payload.get("started_at")) or _as_utc(start.created_at)
        finished_at = _parse_scan_time(terminal_payload.get("finished_at")) if terminal else None
        elapsed_seconds = max(0, int(((finished_at or generated_at) - started_at).total_seconds()))
        status = (
            "completed"
            if terminal and terminal.event_type == "sla_scan_execution_completed"
            else "late_completed"
            if terminal and terminal.event_type == "sla_scan_execution_late_completed"
            else "failed"
            if terminal and terminal.event_type == "sla_scan_execution_failed"
            else "late_failed"
            if terminal and terminal.event_type == "sla_scan_execution_late_failed"
            else "force_released"
            if terminal and terminal.event_type == "sla_scan_execution_force_released"
            else "aborted"
            if terminal and terminal.event_type == "sla_scan_execution_aborted"
            else "late_aborted"
            if terminal and terminal.event_type == "sla_scan_execution_late_aborted"
            else "timed_out"
            if terminal
            else "timed_out"
            if elapsed_seconds >= SLA_SCAN_EXECUTION_TIMEOUT_MINUTES * 60
            else "running"
        )
        trigger_type = start_payload.get("trigger_type")
        if trigger_type not in {"manual", "scheduler", "retry"}:
            trigger_type = "legacy"
        executions.append({
            "execution_id": start.aggregate_id,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat() if finished_at else None,
            "elapsed_seconds": elapsed_seconds,
            "actor": start.actor,
            "trigger_type": trigger_type,
            "run_key": start_payload.get("run_key") if isinstance(start_payload.get("run_key"), str) else None,
            "status": status,
            "result_run_id": terminal_payload.get("result_run_id") if isinstance(terminal_payload.get("result_run_id"), str) else None,
            "deduplicated": bool(terminal_payload.get("deduplicated")),
            "error_type": terminal_payload.get("error_type") if isinstance(terminal_payload.get("error_type"), str) else None,
        })
    return {
        "summary": {
            "returned_executions": len(executions),
            "running": sum(item["status"] == "running" for item in executions),
            "timed_out": sum(item["status"] == "timed_out" for item in executions),
            "force_released": sum(item["status"] == "force_released" for item in executions),
            "aborted": sum(item["status"] in {"aborted", "late_aborted"} for item in executions),
            "failed": sum(item["status"] in {"failed", "late_failed"} for item in executions),
            "last_started_at": executions[0]["started_at"] if executions else None,
        },
        "executions": executions,
    }


def _sla_scan_lease_snapshot(session: Session, generated_at: datetime) -> dict:
    lease = session.get(SlaScanLeaseRecord, SLA_SCAN_LEASE_KEY)
    if lease is None or lease.execution_id is None:
        return {
            "status": "idle",
            "execution_id": None,
            "run_key": None,
            "actor": None,
            "trigger_type": None,
            "acquired_at": None,
            "expires_at": None,
            "remaining_seconds": 0,
            "warning_after_seconds": SLA_SCAN_EXECUTION_TIMEOUT_MINUTES * 60,
            "last_heartbeat_at": None,
            "heartbeat_count": 0,
        }
    acquired_at = _as_utc(lease.acquired_at) if lease.acquired_at else None
    expires_at = _as_utc(lease.expires_at) if lease.expires_at else None
    remaining_seconds = max(0, int((expires_at - generated_at).total_seconds())) if expires_at else 0
    elapsed_seconds = max(0, int((generated_at - acquired_at).total_seconds())) if acquired_at else 0
    status = (
        "expired"
        if expires_at is not None and expires_at <= generated_at
        else "overdue"
        if elapsed_seconds >= SLA_SCAN_EXECUTION_TIMEOUT_MINUTES * 60
        else "active"
    )
    return {
        "status": status,
        "execution_id": lease.execution_id,
        "run_key": lease.run_key,
        "actor": lease.actor,
        "trigger_type": lease.trigger_type if lease.trigger_type in {"manual", "scheduler", "retry"} else "legacy",
        "acquired_at": acquired_at.isoformat() if acquired_at else None,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "remaining_seconds": remaining_seconds,
        "warning_after_seconds": SLA_SCAN_EXECUTION_TIMEOUT_MINUTES * 60,
        "last_heartbeat_at": _as_utc(lease.last_heartbeat_at).isoformat() if lease.last_heartbeat_at else None,
        "heartbeat_count": lease.heartbeat_count or 0,
    }


def _sla_scan_event_to_dict(record: AuditEventRecord) -> dict:
    payload = record.payload or {}
    payload_run_id = payload.get("run_id")
    run_id = payload_run_id if isinstance(payload_run_id, str) and payload_run_id else record.aggregate_id
    parsed_run_at = _parse_scan_time(payload.get("run_at"))
    run_at = parsed_run_at.isoformat() if parsed_run_at else _as_utc(record.created_at).isoformat()
    trigger_type = payload.get("trigger_type")
    if trigger_type not in {"manual", "scheduler", "retry"}:
        trigger_type = "legacy"
    payload_run_key = payload.get("run_key")
    run_key = payload_run_key if isinstance(payload_run_key, str) and payload_run_key else None
    status = "failed" if record.event_type == "sla_scan_failed" else "completed"
    error_type = payload.get("error_type") if isinstance(payload.get("error_type"), str) else None
    error_message = payload.get("error_message") if isinstance(payload.get("error_message"), str) else None
    notifications_created = _scan_count(payload, "notifications_created")
    alerts_opened = _scan_count(payload, "facility_alerts_opened") + _scan_count(payload, "control_alerts_opened")
    escalations_triggered = (
        _scan_count(payload, "escalated_cases")
        + _scan_count(payload, "escalated_corrections")
        + _scan_count(payload, "control_conditions_escalated")
    )
    return {
        "event_id": record.id,
        "run_id": run_id,
        "run_at": run_at,
        "actor": record.actor,
        "trigger_type": trigger_type,
        "run_key": run_key,
        "status": status,
        "error_type": error_type,
        "error_message": error_message,
        "active_cases_scanned": _scan_count(payload, "active_cases_scanned"),
        "active_corrections_scanned": _scan_count(payload, "active_corrections_scanned"),
        "active_facilities_scanned": _scan_count(payload, "active_facilities_scanned"),
        "control_conditions_scanned": _scan_count(payload, "control_conditions_scanned"),
        "notifications_created": notifications_created,
        "workflow_notifications_created": _scan_count(payload, "workflow_notifications_created", notifications_created),
        "control_notifications_created": _scan_count(payload, "control_notifications_created"),
        "facility_alerts_opened": _scan_count(payload, "facility_alerts_opened"),
        "control_alerts_opened": _scan_count(payload, "control_alerts_opened"),
        "alerts_opened": alerts_opened,
        "escalated_cases": _scan_count(payload, "escalated_cases"),
        "escalated_corrections": _scan_count(payload, "escalated_corrections"),
        "control_conditions_escalated": _scan_count(payload, "control_conditions_escalated"),
        "escalations_triggered": escalations_triggered,
        "facilities_expired": _scan_count(payload, "facilities_expired"),
        "expired_assignments_released": _scan_count(payload, "expired_assignments_released"),
        "failure_notifications_resolved": _scan_count(payload, "failure_notifications_resolved"),
        "risk_actions_created": notifications_created + alerts_opened + escalations_triggered,
        "recovered": False,
        "can_retry": False,
        "retry_count": 0,
        "last_retry_at": None,
        "last_retry_actor": None,
        "last_retry_status": None,
        "last_retry_reason": None,
    }


def _attach_sla_scan_retry_history(session: Session, runs: list[dict]) -> None:
    failed_run_ids = {item["run_id"] for item in runs if item["status"] == "failed"}
    if not failed_run_ids:
        return
    completed_ids = set(
        session.scalars(
            select(AuditEventRecord.aggregate_id).where(
                AuditEventRecord.aggregate_type == "sla_scan",
                AuditEventRecord.aggregate_id.in_(failed_run_ids),
                AuditEventRecord.event_type == "sla_scan_completed",
            )
        ).all()
    )
    retry_events = session.scalars(
        select(AuditEventRecord)
        .where(
            AuditEventRecord.aggregate_type == "sla_scan_failure",
            AuditEventRecord.aggregate_id.in_(failed_run_ids),
            AuditEventRecord.event_type.in_({
                "sla_scan_retry_requested",
                "sla_scan_retry_completed",
                "sla_scan_retry_failed",
            }),
        )
        .order_by(AuditEventRecord.created_at, AuditEventRecord.id)
    ).all()
    retries_by_run: dict[str, list[AuditEventRecord]] = {}
    for event in retry_events:
        retries_by_run.setdefault(event.aggregate_id, []).append(event)
    for run in runs:
        if run["status"] != "failed":
            continue
        events = retries_by_run.get(run["run_id"], [])
        requests = [event for event in events if event.event_type == "sla_scan_retry_requested"]
        outcomes = [event for event in events if event.event_type in {"sla_scan_retry_completed", "sla_scan_retry_failed"}]
        latest_request = max(requests, key=_sla_retry_number) if requests else None
        latest_retry_number = _sla_retry_number(latest_request) if latest_request else 0
        latest_retry_outcomes = [event for event in outcomes if _sla_retry_number(event) == latest_retry_number]
        latest_outcome = latest_retry_outcomes[-1] if latest_retry_outcomes else None
        recovered = run["run_id"] in completed_ids
        run.update({
            "recovered": recovered,
            "can_retry": not recovered,
            "retry_count": len(requests),
            "last_retry_at": (
                (latest_outcome.payload or {}).get("finished_at")
                if latest_outcome
                else (latest_request.payload or {}).get("requested_at") if latest_request else None
            ),
            "last_retry_actor": (latest_request.actor if latest_request else None),
            "last_retry_status": (
                "completed" if latest_outcome and latest_outcome.event_type == "sla_scan_retry_completed"
                else "failed" if latest_outcome
                else "requested" if latest_request
                else None
            ),
            "last_retry_reason": (latest_request.payload or {}).get("reason") if latest_request else None,
        })


def _sla_retry_number(event: AuditEventRecord) -> int:
    value = (event.payload or {}).get("retry_number")
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _scan_count(payload: dict, key: str, default: int = 0) -> int:
    value = payload.get(key, default)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else default


def _scan_metric_delta(current: dict, previous: dict | None, key: str) -> int:
    return current[key] - previous[key] if previous else 0


def _scan_interval_minutes(current: dict, previous: dict) -> float:
    current_at = _parse_scan_time(current["run_at"])
    previous_at = _parse_scan_time(previous["run_at"])
    if not current_at or not previous_at:
        return SLA_SCAN_EXPECTED_CADENCE_MINUTES
    return max(0, (current_at - previous_at).total_seconds() / 60)


def _parse_scan_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return _as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _release_expired_assignments(
    cases: list[ApprovalCaseRecord],
    corrections: list[DocumentCorrectionRecord],
    scan_time: datetime,
    notifications: NotificationRepository,
    audit: AuditRepository,
    actor: str,
) -> tuple[int, int]:
    released = 0
    notifications_created = 0
    records: list[tuple[str, str, str, ApprovalCaseRecord | DocumentCorrectionRecord]] = [
        ("approval", "approval_case", case.case_id, case) for case in cases
    ]
    records.extend(("correction", "document_correction", correction.id, correction) for correction in corrections)
    for task_type, aggregate_type, aggregate_id, record in records:
        if not assignment_is_expired(record, scan_time):
            continue
        previous_assignee = record.assigned_to
        previous_assignee_name = record.assigned_to_name
        previous_expires_at = assignment_expiry(record)
        notification_id = None
        notification_payload = _assignment_notification_payload(
            task_type,
            record,
            "lease_expired",
            previous_assignee,
            previous_assignee_name,
            previous_expires_at,
        )
        if notification_payload:
            notification, created = notifications.create_if_absent(notification_payload)
            notification_id = notification["id"]
            notifications_created += int(created)
        clear_assignment(record)
        audit.append(
            aggregate_type,
            aggregate_id,
            "personal_task_lease_expired",
            actor,
            {
                "previous_assignee": previous_assignee,
                "previous_assignee_name": previous_assignee_name,
                "previous_assignment_expires_at": previous_expires_at.isoformat() if previous_expires_at else None,
                "released_at": scan_time.isoformat(),
                "notification_id": notification_id,
            },
        )
        released += 1
    return released, notifications_created


def _notify_due_assignment_leases(
    cases: list[ApprovalCaseRecord],
    corrections: list[DocumentCorrectionRecord],
    scan_time: datetime,
    notifications: NotificationRepository,
    audit: AuditRepository,
    actor: str,
) -> int:
    created_count = 0
    records: list[tuple[str, str, str, ApprovalCaseRecord | DocumentCorrectionRecord]] = [
        ("approval", "approval_case", case.case_id, case) for case in cases
    ]
    records.extend(("correction", "document_correction", correction.id, correction) for correction in corrections)
    for task_type, aggregate_type, aggregate_id, record in records:
        remaining = lease_remaining_seconds(record, scan_time)
        if remaining is None or remaining > ASSIGNMENT_LEASE_WARNING_SECONDS:
            continue
        expires_at = assignment_expiry(record)
        payload = _assignment_notification_payload(
            task_type,
            record,
            "lease_due_soon",
            record.assigned_to,
            record.assigned_to_name,
            expires_at,
        )
        if not payload:
            continue
        notification, created = notifications.create_if_absent(payload)
        if not created:
            continue
        created_count += 1
        audit.append(
            aggregate_type,
            aggregate_id,
            "personal_task_lease_due_notification_generated",
            actor,
            {
                "recipient_subject": record.assigned_to,
                "assignment_expires_at": expires_at.isoformat() if expires_at else None,
                "notification_id": notification["id"],
            },
        )
    return created_count


def _assignment_notification_payload(
    task_type: str,
    record: ApprovalCaseRecord | DocumentCorrectionRecord,
    level: str,
    recipient_subject: str | None,
    recipient_name: str | None,
    expires_at: datetime | None,
) -> dict | None:
    case_id = record.case_id
    if not case_id or not recipient_subject or not expires_at:
        return None
    is_approval = task_type == "approval"
    action_json = {
        "page": "approvals" if is_approval else "documents",
        "counterparty_id": record.counterparty_id,
        "case_id": case_id,
        **({"correction_id": record.id} if not is_approval else {}),
    }
    title = "任务认领租约即将到期" if level == "lease_due_soon" else "任务认领已自动回收"
    message = (
        f"{recipient_name or '任务处理人'}，当前任务认领将在 {expires_at.isoformat()} 到期，请及时处理或续期。"
        if level == "lease_due_soon"
        else f"{recipient_name or '任务处理人'}，当前任务认领已到期并返回角色公共队列。"
    )
    return {
        "case_id": case_id,
        "counterparty_id": record.counterparty_id,
        "recipient_role": "personal",
        "recipient_subject": recipient_subject,
        "category": "task_assignment",
        "level": level,
        "severity": "warning",
        "title": title,
        "message": message,
        "action_json": action_json,
        "dedup_key": f"task-lease:{task_type}:{case_id if is_approval else record.id}:{recipient_subject}:{expires_at.isoformat()}:{level}",
        "status": "unread",
    }


def build_operations_summary(
    session: Session,
    now: datetime | None = None,
    recipient_roles: tuple[str, ...] | None = None,
    recipient_subject: str | None = None,
    counterparty_id: str | None = None,
) -> dict:
    scan_time = _as_utc(now or datetime.now(timezone.utc))
    cases = session.scalars(select(ApprovalCaseRecord)).all()
    active_cases = [case for case in cases if case.status in ACTIVE_STATUSES]
    corrections = session.scalars(
        select(DocumentCorrectionRecord).where(DocumentCorrectionRecord.status.in_(ACTIVE_CORRECTION_STATUSES))
    ).all()
    facility_statement = select(CreditFacilityRecord)
    condition_statement = (
        select(FacilityControlConditionRecord)
        .join(CreditFacilityRecord, CreditFacilityRecord.id == FacilityControlConditionRecord.facility_id)
        .where(FacilityControlConditionRecord.status == "pending")
    )
    extension_statement = (
        select(FacilityControlExtensionRecord)
        .select_from(FacilityControlExtensionRecord)
        .join(FacilityControlConditionRecord, FacilityControlConditionRecord.id == FacilityControlExtensionRecord.condition_id)
        .join(CreditFacilityRecord, CreditFacilityRecord.id == FacilityControlExtensionRecord.facility_id)
        .where(
            FacilityControlExtensionRecord.status == "pending",
            FacilityControlConditionRecord.status == "pending",
        )
    )
    if counterparty_id:
        facility_statement = facility_statement.where(CreditFacilityRecord.counterparty_id == counterparty_id)
        condition_statement = condition_statement.where(CreditFacilityRecord.counterparty_id == counterparty_id)
        extension_statement = extension_statement.where(CreditFacilityRecord.counterparty_id == counterparty_id)
    facilities = session.scalars(facility_statement).all()
    control_conditions = session.scalars(condition_statement).all()
    pending_extensions = session.scalars(extension_statement).all()
    sla_counts: Counter[str] = Counter()
    stage_counts: Counter[str] = Counter()
    for case in active_cases:
        stage_counts[case.current_stage] += 1
        if case.status == "待补件":
            sla_counts["paused"] += 1
        else:
            level = _sla_level(case, scan_time)
            sla_counts[level or "normal"] += 1
    correction_sla_counts: Counter[str] = Counter()
    for correction in corrections:
        snapshot = correction_sla_snapshot(correction.status, correction.sla_due_at, scan_time)
        correction_sla_counts[snapshot["sla_status"]] += 1
    control_sla_counts: Counter[str] = Counter()
    for condition in control_conditions:
        level, _ = _facility_control_sla(condition, scan_time)
        control_sla_counts[level] += 1
    unread_statement = select(NotificationRecord).where(NotificationRecord.status == "unread")
    if recipient_roles is not None:
        broadcast_scope = and_(
            NotificationRecord.recipient_subject.is_(None),
            NotificationRecord.recipient_role.in_(recipient_roles),
        )
        unread_statement = unread_statement.where(
            or_(NotificationRecord.recipient_subject == recipient_subject, broadcast_scope)
            if recipient_subject
            else broadcast_scope
        )
    if counterparty_id:
        unread_statement = unread_statement.where(NotificationRecord.counterparty_id == counterparty_id)
    unread = session.scalars(unread_statement).all()
    severity_counts = Counter(item.severity for item in unread)
    last_scan = session.scalars(
        select(AuditEventRecord)
        .where(
            AuditEventRecord.aggregate_type == "sla_scan",
            AuditEventRecord.event_type == "sla_scan_completed",
        )
        .order_by(AuditEventRecord.payload["run_at"].as_string().desc())
        .limit(1)
    ).first()
    last_scan_payload = _sla_scan_event_to_dict(last_scan) if last_scan else None
    return {
        "generated_at": scan_time.isoformat(),
        "total_cases": len(cases),
        "active_cases": len(active_cases),
        "sla": {
            "normal": sla_counts["normal"],
            "due_soon": sla_counts["due_soon"],
            "overdue": sla_counts["overdue"],
            "escalated": sla_counts["escalated"],
            "paused": sla_counts["paused"],
        },
        "correction_sla": {
            "active": len(corrections),
            "normal": correction_sla_counts["normal"],
            "due_soon": correction_sla_counts["due_soon"],
            "overdue": correction_sla_counts["overdue"],
            "escalated": correction_sla_counts["escalated"],
        },
        "post_credit_sla": {
            "active_facilities": sum(item.status == "active" for item in facilities),
            "pending_controls": len(control_conditions),
            "normal": control_sla_counts["normal"],
            "due_soon": control_sla_counts["due_soon"],
            "overdue": control_sla_counts["overdue"],
            "escalated": control_sla_counts["escalated"],
            "pending_extensions": len(pending_extensions),
        },
        "unread_notifications": {
            "total": len(unread),
            "info": severity_counts["info"],
            "warning": severity_counts["warning"],
            "critical": severity_counts["critical"],
        },
        "last_scan": last_scan_payload,
        "stage_distribution": [
            {"stage": stage, "label": stage_label(stage), "count": count}
            for stage, count in sorted(stage_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
    }


def build_personal_task_queue(
    session: Session,
    roles: tuple[str, ...],
    counterparty_id: str | None = None,
    now: datetime | None = None,
    actor_subject: str | None = None,
    limit: int | None = 200,
) -> dict:
    queue_time = _as_utc(now or datetime.now(timezone.utc))
    is_admin = "admin" in roles
    role_set = set(roles)
    case_statement = select(ApprovalCaseRecord).where(ApprovalCaseRecord.status.in_(ACTIVE_STATUSES))
    correction_statement = select(DocumentCorrectionRecord).where(
        DocumentCorrectionRecord.status.in_(ACTIVE_CORRECTION_STATUSES)
    )
    if counterparty_id:
        case_statement = case_statement.where(ApprovalCaseRecord.counterparty_id == counterparty_id)
        correction_statement = correction_statement.where(DocumentCorrectionRecord.counterparty_id == counterparty_id)
    cases = session.scalars(case_statement).all()
    corrections = session.scalars(correction_statement).all()
    case_names = {case.case_id: case.counterparty_name for case in cases}
    tasks: list[dict] = []

    for case in cases:
        owner_roles = (
            authority_owner_roles(case, APPROVAL_STAGE_ROLES.get(case.current_stage, set()))
            if case.current_stage == "final_strategy"
            else set(APPROVAL_STAGE_ROLES.get(case.current_stage, set()))
        )
        if case.status != "处理中" or (not is_admin and not owner_roles.intersection(role_set)):
            continue
        if (
            case.current_stage == "final_strategy"
            and not is_admin
            and authority_has_signer(case, actor_subject)
        ):
            continue
        active_assignment = assignment_is_active(case, queue_time)
        expired_assignment = assignment_is_expired(case, queue_time)
        if active_assignment and case.assigned_to != actor_subject and not is_admin:
            continue
        due_at = _as_utc(case.stage_due_at) if case.stage_due_at else None
        remaining_seconds = int((due_at - queue_time).total_seconds()) if due_at else None
        tasks.append(
            {
                "id": f"approval:{case.case_id}:{case.current_stage}",
                "task_type": "approval",
                "title": f"处理{stage_label(case.current_stage)}环节",
                "description": f"{case.counterparty_name} 的授信申请等待当前角色处理。",
                "counterparty_id": case.counterparty_id,
                "counterparty_name": case.counterparty_name,
                "case_id": case.case_id,
                "stage": case.current_stage,
                "stage_label": stage_label(case.current_stage),
                "correction_id": None,
                "document_type": None,
                "status": case.status,
                "sla_status": _sla_level(case, queue_time) or "normal",
                "due_at": due_at.isoformat() if due_at else None,
                "remaining_seconds": remaining_seconds,
                "owner_roles": sorted(owner_roles),
                "viewer_mode": "owner",
                "assigned_to": case.assigned_to if active_assignment else None,
                "assigned_to_name": case.assigned_to_name if active_assignment else None,
                "assigned_at": correction_as_iso(case.assigned_at) if active_assignment else None,
                "assignment_expires_at": assignment_expiry(case).isoformat() if active_assignment and assignment_expiry(case) else None,
                "lease_remaining_seconds": lease_remaining_seconds(case, queue_time),
                "assignment_expired": expired_assignment,
                "assignment_state": "assigned_other" if active_assignment and case.assigned_to != actor_subject else "mine" if active_assignment else "unassigned",
                "can_release": bool(active_assignment and (case.assigned_to == actor_subject or is_admin)),
                "claimable": True,
                "reminder_role": None,
                "row_version": case.row_version,
                "action": {
                    "page": "approvals",
                    "counterparty_id": case.counterparty_id,
                    "case_id": case.case_id,
                },
            }
        )

    for correction in corrections:
        is_collaborating_client = correction.status == "open" and "client" in role_set
        is_owner = correction.assigned_role in role_set
        if not is_admin and not is_owner and not is_collaborating_client:
            continue
        active_assignment = assignment_is_active(correction, queue_time)
        expired_assignment = assignment_is_expired(correction, queue_time)
        if active_assignment and correction.assigned_to != actor_subject and not is_admin:
            continue
        snapshot = correction_sla_snapshot(correction.status, correction.sla_due_at, queue_time)
        task_action = "提交替换资料" if correction.status == "open" else "复核替换资料"
        tasks.append(
            {
                "id": f"correction:{correction.id}",
                "task_type": "correction",
                "title": f"{task_action}：{correction.document_type}",
                "description": correction.reason,
                "counterparty_id": correction.counterparty_id,
                "counterparty_name": case_names.get(correction.case_id, correction.counterparty_id),
                "case_id": correction.case_id,
                "stage": "supplement",
                "stage_label": "补充资料",
                "correction_id": correction.id,
                "document_type": correction.document_type,
                "status": correction.status,
                "sla_status": snapshot["sla_status"],
                "due_at": correction_as_iso(correction.sla_due_at),
                "remaining_seconds": snapshot["remaining_seconds"],
                "owner_roles": [correction.assigned_role],
                "viewer_mode": "owner" if is_admin or is_owner else "collaborator",
                "assigned_to": correction.assigned_to if active_assignment else None,
                "assigned_to_name": correction.assigned_to_name if active_assignment else None,
                "assigned_at": correction_as_iso(correction.assigned_at) if active_assignment else None,
                "assignment_expires_at": assignment_expiry(correction).isoformat() if active_assignment and assignment_expiry(correction) else None,
                "lease_remaining_seconds": lease_remaining_seconds(correction, queue_time),
                "assignment_expired": expired_assignment,
                "assignment_state": "assigned_other" if active_assignment and correction.assigned_to != actor_subject else "mine" if active_assignment else "unassigned",
                "can_release": bool(active_assignment and (correction.assigned_to == actor_subject or is_admin)),
                "claimable": True,
                "reminder_role": None,
                "row_version": correction.row_version,
                "action": {
                    "page": "documents",
                    "counterparty_id": correction.counterparty_id,
                    "correction_id": correction.id,
                    **({"case_id": correction.case_id} if correction.case_id else {}),
                },
            }
        )

    _append_facility_control_tasks(
        session,
        tasks,
        queue_time,
        role_set,
        is_admin,
        actor_subject,
        counterparty_id,
    )

    priority = {"escalated": 0, "overdue": 1, "due_soon": 2, "normal": 3}
    tasks.sort(
        key=lambda task: (
            priority.get(task["sla_status"], 4),
            task["due_at"] or "9999-12-31T23:59:59+00:00",
            task["task_type"],
            task["id"],
        )
    )
    counts = Counter(task["task_type"] for task in tasks)
    risk_counts = Counter(task["sla_status"] for task in tasks)
    returned_tasks = tasks if limit is None else tasks[:limit]
    return {
        "generated_at": queue_time.isoformat(),
        "summary": {
            "total": len(tasks),
            "returned": len(returned_tasks),
            "truncated": len(returned_tasks) < len(tasks),
            "approval": counts["approval"],
            "correction": counts["correction"],
            "facility_control": counts["facility_control"],
            "control_extension": counts["control_extension"],
            "post_credit": counts["facility_control"] + counts["control_extension"],
            "due_soon": risk_counts["due_soon"],
            "overdue": risk_counts["overdue"],
            "escalated": risk_counts["escalated"],
        },
        "tasks": returned_tasks,
    }


def build_team_task_board(
    session: Session,
    now: datetime | None = None,
    limit: int = 500,
    can_manage: bool = False,
) -> dict:
    board_time = _as_utc(now or datetime.now(timezone.utc))
    queue = build_personal_task_queue(
        session,
        ("admin",),
        now=board_time,
        actor_subject="__team_task_board__",
        limit=None,
    )
    tasks = queue["tasks"]
    role_load: dict[str, Counter[str]] = {}
    assignee_load: dict[tuple[str | None, str], Counter[str]] = {}
    for task in tasks:
        is_direct = not task["claimable"]
        is_claimed = task["assignment_state"] == "assigned_other"
        is_risk = task["sla_status"] != "normal"
        for role in task["owner_roles"]:
            counters = role_load.setdefault(role, Counter())
            counters["total"] += 1
            counters["direct" if is_direct else "claimed" if is_claimed else "unassigned"] += 1
            if is_risk:
                counters["risk"] += 1
        assignee_key = (
            task["assigned_to"] if is_claimed else "__direct__" if is_direct else None,
            task["assigned_to_name"] if is_claimed else "系统直派" if is_direct else "未认领",
        )
        assignee_counters = assignee_load.setdefault(assignee_key, Counter())
        assignee_counters["total"] += 1
        assignee_counters["risk"] += int(is_risk)
        task["can_release"] = False
        task["can_force_release"] = bool(can_manage and is_claimed)
        task["can_remind"] = bool(can_manage and (is_claimed or is_direct))

    returned_tasks = tasks[:limit]
    return {
        "generated_at": board_time.isoformat(),
        "summary": {
            "total": len(tasks),
            "returned": len(returned_tasks),
            "truncated": len(returned_tasks) < len(tasks),
            "claimed": sum(task["assignment_state"] == "assigned_other" for task in tasks),
            "unassigned": sum(task["claimable"] and task["assignment_state"] == "unassigned" for task in tasks),
            "direct": sum(not task["claimable"] for task in tasks),
            "expired": sum(task["assignment_expired"] for task in tasks),
            "at_risk": sum(task["sla_status"] != "normal" for task in tasks),
        },
        "role_load": [
            {
                "role": role,
                "total": counters["total"],
                "claimed": counters["claimed"],
                "unassigned": counters["unassigned"],
                "direct": counters["direct"],
                "risk": counters["risk"],
            }
            for role, counters in sorted(role_load.items(), key=lambda item: (-item[1]["total"], item[0]))
        ],
        "assignee_load": [
            {
                "subject": subject,
                "name": name,
                "total": counters["total"],
                "risk": counters["risk"],
            }
            for (subject, name), counters in sorted(
                assignee_load.items(),
                key=lambda item: (-item[1]["total"], item[0][1]),
            )
        ],
        "tasks": returned_tasks,
    }


def _append_facility_control_tasks(
    session: Session,
    tasks: list[dict],
    queue_time: datetime,
    role_set: set[str],
    is_admin: bool,
    actor_subject: str | None,
    counterparty_id: str | None,
) -> None:
    condition_statement = (
        select(FacilityControlConditionRecord, CreditFacilityRecord)
        .select_from(FacilityControlConditionRecord)
        .join(CreditFacilityRecord, CreditFacilityRecord.id == FacilityControlConditionRecord.facility_id)
        .where(FacilityControlConditionRecord.status == "pending")
    )
    extension_statement = (
        select(FacilityControlExtensionRecord, FacilityControlConditionRecord, CreditFacilityRecord)
        .select_from(FacilityControlExtensionRecord)
        .join(FacilityControlConditionRecord, FacilityControlConditionRecord.id == FacilityControlExtensionRecord.condition_id)
        .join(CreditFacilityRecord, CreditFacilityRecord.id == FacilityControlExtensionRecord.facility_id)
        .where(
            FacilityControlExtensionRecord.status == "pending",
            FacilityControlConditionRecord.status == "pending",
        )
    )
    if counterparty_id:
        condition_statement = condition_statement.where(CreditFacilityRecord.counterparty_id == counterparty_id)
        extension_statement = extension_statement.where(CreditFacilityRecord.counterparty_id == counterparty_id)

    for condition, facility in session.execute(condition_statement).all():
        owner_roles = {condition.owner_role}
        if condition.escalation_role:
            owner_roles.add(condition.escalation_role)
        if not is_admin and not owner_roles.intersection(role_set):
            continue
        sla_status, remaining_seconds = _facility_control_sla(condition, queue_time)
        is_escalation_viewer = condition.owner_role not in role_set and not is_admin
        tasks.append(
            {
                "id": f"facility_control:{condition.id}",
                "task_type": "facility_control",
                "title": f"{'升级督办' if is_escalation_viewer else '落实'}贷后控制条件 #{condition.sequence}",
                "description": condition.measure,
                "counterparty_id": facility.counterparty_id,
                "counterparty_name": facility.counterparty_name,
                "case_id": facility.case_id,
                "stage": "post_credit_control",
                "stage_label": "贷后控制",
                "correction_id": None,
                "document_type": None,
                "facility_id": facility.id,
                "condition_id": condition.id,
                "extension_id": None,
                "status": condition.status,
                "sla_status": sla_status,
                "due_at": _as_utc(condition.due_at).isoformat(),
                "remaining_seconds": remaining_seconds,
                "owner_roles": sorted(owner_roles),
                "viewer_mode": "owner",
                "assigned_to": None,
                "assigned_to_name": None,
                "assigned_at": None,
                "assignment_expires_at": None,
                "lease_remaining_seconds": None,
                "assignment_expired": False,
                "assignment_state": "direct",
                "can_release": False,
                "claimable": False,
                "reminder_role": condition.escalation_role or condition.owner_role,
                "row_version": condition.row_version,
                "action": {
                    "page": "facilities",
                    "case_id": facility.case_id,
                    "facility_id": facility.id,
                    "condition_id": condition.id,
                },
            }
        )

    for extension, condition, facility in session.execute(extension_statement).all():
        if not is_admin and "approver" not in role_set:
            continue
        if extension.requested_by == actor_subject:
            continue
        sla_status, remaining_seconds = _facility_control_sla(condition, queue_time)
        tasks.append(
            {
                "id": f"control_extension:{extension.id}",
                "task_type": "control_extension",
                "title": f"审批控制条件延期 {extension.extension_days} 天",
                "description": f"申请人：{extension.requested_by_name}；申请理由：{extension.reason}",
                "counterparty_id": facility.counterparty_id,
                "counterparty_name": facility.counterparty_name,
                "case_id": facility.case_id,
                "stage": "control_extension_review",
                "stage_label": "延期审批",
                "correction_id": None,
                "document_type": None,
                "facility_id": facility.id,
                "condition_id": condition.id,
                "extension_id": extension.id,
                "status": extension.status,
                "sla_status": sla_status,
                "due_at": _as_utc(condition.due_at).isoformat(),
                "remaining_seconds": remaining_seconds,
                "owner_roles": ["approver"],
                "viewer_mode": "owner",
                "assigned_to": None,
                "assigned_to_name": None,
                "assigned_at": None,
                "assignment_expires_at": None,
                "lease_remaining_seconds": None,
                "assignment_expired": False,
                "assignment_state": "direct",
                "can_release": False,
                "claimable": False,
                "reminder_role": "approver",
                "row_version": extension.row_version,
                "action": {
                    "page": "facilities",
                    "case_id": facility.case_id,
                    "facility_id": facility.id,
                    "condition_id": condition.id,
                },
            }
        )


def _facility_control_sla(condition: FacilityControlConditionRecord, now: datetime) -> tuple[str, int]:
    remaining_seconds = int((_as_utc(condition.due_at) - now).total_seconds())
    if remaining_seconds < 0:
        return ("escalated" if condition.escalation_level >= 2 else "overdue"), remaining_seconds
    if remaining_seconds <= 3 * 86400:
        return "due_soon", remaining_seconds
    return "normal", remaining_seconds


def _sla_level(case: ApprovalCaseRecord, now: datetime) -> str | None:
    if not case.stage_due_at:
        return None
    due_at = _as_utc(case.stage_due_at)
    remaining = int((due_at - now).total_seconds())
    if remaining <= -ESCALATION_AFTER_SECONDS:
        return "escalated"
    if remaining < 0:
        return "overdue"
    warning_seconds = STAGE_SLA_HOURS.get(case.current_stage, 24) * 3600 * 0.25
    return "due_soon" if remaining <= warning_seconds else None


def _recipient_roles(case: ApprovalCaseRecord, level: str) -> set[str]:
    roles = (
        authority_owner_roles(case, APPROVAL_STAGE_ROLES.get(case.current_stage, set()))
        if case.current_stage == "final_strategy"
        else set(APPROVAL_STAGE_ROLES.get(case.current_stage, set()))
    )
    if level in {"overdue", "escalated"}:
        roles.update({"relationship_manager", "risk_manager"})
    if level == "escalated":
        roles.update({"approver", "operations"})
    return roles


def _notification_payload(case: ApprovalCaseRecord, role: str, level: str) -> dict:
    titles = {"due_soon": "审批环节即将超时", "overdue": "审批环节已超时", "escalated": "审批超时升级催办"}
    severities = {"due_soon": "warning", "overdue": "critical", "escalated": "critical"}
    started_at = _as_utc(case.stage_started_at or case.updated_at or case.created_at).isoformat()
    due_at = _as_utc(case.stage_due_at).isoformat()
    return {
        "case_id": case.case_id,
        "counterparty_id": case.counterparty_id,
        "recipient_role": role,
        "category": "sla",
        "level": level,
        "severity": severities[level],
        "title": titles[level],
        "message": f"{case.counterparty_name} 的{stage_label(case.current_stage)}环节需处理，截止时间 {due_at}。",
        "action_json": {
            "page": "approvals",
            "counterparty_id": case.counterparty_id,
            "case_id": case.case_id,
        },
        "dedup_key": f"sla:{case.case_id}:{case.current_stage}:{started_at}:{level}:{role}",
        "status": "unread",
    }


def _correction_recipient_roles(correction: DocumentCorrectionRecord, level: str) -> set[str]:
    roles = {correction.assigned_role}
    if correction.status == "open":
        roles.add("client")
    if level in {"overdue", "escalated"}:
        roles.add("operations")
    if level == "escalated":
        roles.update({"relationship_manager", "risk_manager"})
    return roles


def _correction_notification_payload(correction: DocumentCorrectionRecord, role: str, level: str) -> dict:
    titles = {"due_soon": "补件任务即将超时", "overdue": "补件任务已超时", "escalated": "补件任务升级催办"}
    severities = {"due_soon": "warning", "overdue": "critical", "escalated": "critical"}
    started_at = _as_utc(correction.sla_started_at).isoformat()
    due_at = _as_utc(correction.sla_due_at).isoformat()
    action = "提交替换资料" if correction.status == "open" else "复核替换资料"
    return {
        "case_id": correction.case_id,
        "counterparty_id": correction.counterparty_id,
        "recipient_role": role,
        "category": "document_correction",
        "level": level,
        "severity": severities[level],
        "title": titles[level],
        "message": f"{correction.document_type} 补件任务需{action}，截止时间 {due_at}。",
        "action_json": {
            "page": "documents",
            "counterparty_id": correction.counterparty_id,
            "case_id": correction.case_id,
            "correction_id": correction.id,
        },
        "dedup_key": f"correction-sla:{correction.id}:{started_at}:{level}:{role}",
        "status": "unread",
    }


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def correction_as_iso(value: datetime | None) -> str | None:
    return _as_utc(value).isoformat() if value else None
