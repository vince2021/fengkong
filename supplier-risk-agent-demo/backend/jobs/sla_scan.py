from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from threading import Event, Thread

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from uuid import uuid4

import backend.database as database
from backend.database import SessionLocal
from backend.db_models import AuditEventRecord, SlaScanLeaseRecord
from backend.repository import AuditRepository, NotificationRepository
from backend.sla_monitor import SLA_SCAN_EXECUTION_TIMEOUT_MINUTES, SLA_SCAN_HEARTBEAT_INTERVAL_SECONDS, SLA_SCAN_LEASE_HARD_EXPIRY_MINUTES, SLA_SCAN_LEASE_KEY, run_sla_scan, sla_scan_scheduler_run_key
from backend.tenant_registry import PLATFORM_INTERNAL_TENANT_ID


SCHEDULER_NAME = "全域 SLA 自动调度器"
RETRY_IN_PROGRESS_TIMEOUT_MINUTES = 15


class SlaScanRetryNotFound(LookupError):
    pass


class SlaScanRetryConflict(RuntimeError):
    pass


class SlaScanExecutionConflict(RuntimeError):
    def __init__(self, lease: dict) -> None:
        self.lease = lease
        actor = lease.get("actor") or "其他处理人"
        trigger = {"manual": "人工扫描", "scheduler": "自动调度", "retry": "人工恢复"}.get(lease.get("trigger_type"), "全域扫描")
        started_at = lease.get("acquired_at") or "未知时间"
        super().__init__(
            f"{trigger}正在由{actor}执行（开始于 {started_at}），"
            f"请等待当前扫描完成、由运营受控释放或 {SLA_SCAN_LEASE_HARD_EXPIRY_MINUTES} 分钟硬过期后再试"
        )


class SlaScanLeaseReleaseNotFound(LookupError):
    pass


class SlaScanLeaseReleaseConflict(RuntimeError):
    pass


class SlaScanLeaseLost(RuntimeError):
    pass


class _ScanLeaseHeartbeat:
    def __init__(self, execution_id: str, interval_seconds: int = SLA_SCAN_HEARTBEAT_INTERVAL_SECONDS) -> None:
        self.execution_id = execution_id
        self.interval_seconds = interval_seconds
        self._stop = Event()
        self._lost = Event()
        self._thread = Thread(target=self._run, name=f"sla-heartbeat-{execution_id[:8]}", daemon=True)

    def __enter__(self) -> _ScanLeaseHeartbeat:
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def assert_owned(self, session: Session, final: bool = False) -> None:
        if self._lost.is_set():
            raise SlaScanLeaseLost("当前扫描租约已被释放或接管，旧执行已停止写入")
        _assert_scan_lease_owned(session, self.execution_id, final=final)

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                with database.SessionLocal() as heartbeat_session:
                    renewed = _renew_scan_lease(heartbeat_session, self.execution_id)
                if not renewed:
                    self._lost.set()
                    return
            except SQLAlchemyError:
                # A transient heartbeat write failure does not prove ownership was lost.
                # Guard checkpoints still read the authoritative lease before more work.
                continue


def run_scheduled_sla_scan(
    session: Session,
    now: datetime | None = None,
    run_key: str | None = None,
    actor: str = SCHEDULER_NAME,
    trigger_type: str = "scheduler",
    execution: dict | None = None,
) -> dict:
    run_at = now or datetime.now(timezone.utc)
    effective_run_key = sla_scan_scheduler_run_key(run_at) if run_key is None else run_key
    if not 1 <= len(effective_run_key) <= 128:
        raise ValueError("SLA 扫描任务键长度必须为 1—128 个字符")
    try:
        execution = execution or _start_scan_execution(session, actor, trigger_type, run_at, effective_run_key)
    except SlaScanExecutionConflict as exc:
        if trigger_type != "scheduler":
            raise
        skipped, created = _record_scheduled_scan_skip(session, effective_run_key, run_at, actor, exc.lease)
        return {
            "run_id": effective_run_key,
            "run_key": effective_run_key,
            "run_at": (run_at if run_at.tzinfo else run_at.replace(tzinfo=timezone.utc)).isoformat(),
            "trigger_type": "scheduler",
            "status": "skipped",
            "deduplicated": not created,
            "skip_reason": "scan_in_progress",
            "active_execution": exc.lease,
            "skip_event_id": skipped["id"],
        }
    try:
        with _ScanLeaseHeartbeat(execution["execution_id"]) as heartbeat:
            result = run_sla_scan(
                session,
                now=run_at,
                actor=actor,
                run_key=effective_run_key,
                trigger_type=trigger_type,
                lease_guard=lambda final: heartbeat.assert_owned(session, final),
            )
    except SlaScanLeaseLost as exc:
        session.rollback()
        _record_scan_lease_lost(session, execution, exc)
        tracked = _finish_scan_execution(session, execution, "aborted", None, error=exc)
        return {
            "run_id": effective_run_key,
            "run_key": effective_run_key,
            "run_at": _as_utc(run_at).isoformat(),
            "trigger_type": trigger_type,
            "status": "aborted",
            "deduplicated": False,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "execution_id": execution["execution_id"],
            "execution_tracked": tracked,
        }
    except Exception as exc:
        session.rollback()
        failure = _record_scan_failure(session, effective_run_key, run_at, exc, actor)
        session.commit()
        tracked = _finish_scan_execution(session, execution, "failed", failure, error=exc)
        return {**failure, "execution_id": execution["execution_id"], "execution_tracked": tracked}
    tracked = _finish_scan_execution(session, execution, "completed", result)
    return {**result, "execution_id": execution["execution_id"], "execution_tracked": tracked}


def run_manual_sla_scan(
    session: Session,
    tenant_id: str,
    actor: str,
    now: datetime | None = None,
) -> dict:
    run_at = now or datetime.now(timezone.utc)
    execution = _start_scan_execution(session, actor, "manual", run_at, None)
    try:
        with _ScanLeaseHeartbeat(execution["execution_id"]) as heartbeat:
            result = run_sla_scan(
                session,
                tenant_id=tenant_id,
                now=run_at,
                actor=actor,
                lease_guard=lambda final: heartbeat.assert_owned(session, final),
            )
    except SlaScanLeaseLost as exc:
        session.rollback()
        _record_scan_lease_lost(session, execution, exc)
        _finish_scan_execution(session, execution, "aborted", None, error=exc)
        raise
    except Exception as exc:
        session.rollback()
        _finish_scan_execution(session, execution, "failed", None, error=exc)
        raise
    tracked = _finish_scan_execution(session, execution, "completed", result)
    return {**result, "execution_id": execution["execution_id"], "execution_tracked": tracked}


def retry_failed_sla_scan(
    session: Session,
    run_key: str,
    actor: str,
    reason: str,
    now: datetime | None = None,
) -> dict:
    normalized_reason = reason.strip()
    if not 5 <= len(normalized_reason) <= 1000:
        raise ValueError("人工重试原因长度必须为 5—1000 个字符")
    if not 1 <= len(run_key) <= 128:
        raise ValueError("SLA 扫描任务键长度必须为 1—128 个字符")
    failure = session.scalars(
        select(AuditEventRecord).where(
            AuditEventRecord.tenant_id == PLATFORM_INTERNAL_TENANT_ID,
            AuditEventRecord.scope_type == "platform",
            AuditEventRecord.aggregate_type == "sla_scan_failure",
            AuditEventRecord.aggregate_id == run_key,
            AuditEventRecord.event_type == "sla_scan_failed",
        )
    ).first()
    if failure is None:
        raise SlaScanRetryNotFound("失败扫描记录不存在，无法发起人工重试")
    completed = session.scalars(
        select(AuditEventRecord).where(
            AuditEventRecord.tenant_id == PLATFORM_INTERNAL_TENANT_ID,
            AuditEventRecord.scope_type == "platform",
            AuditEventRecord.aggregate_type == "sla_scan",
            AuditEventRecord.aggregate_id == run_key,
            AuditEventRecord.event_type == "sla_scan_completed",
        )
    ).first()
    if completed is not None:
        raise SlaScanRetryConflict("该失败扫描已恢复，无需重复重试")

    retry_at = now or datetime.now(timezone.utc)
    normalized_at = retry_at if retry_at.tzinfo else retry_at.replace(tzinfo=timezone.utc)
    audit = AuditRepository(session)
    retry_events = session.scalars(
        select(AuditEventRecord).where(
            AuditEventRecord.tenant_id == PLATFORM_INTERNAL_TENANT_ID,
            AuditEventRecord.scope_type == "platform",
            AuditEventRecord.aggregate_type == "sla_scan_failure",
            AuditEventRecord.aggregate_id == run_key,
            AuditEventRecord.event_type.in_({
                "sla_scan_retry_requested",
                "sla_scan_retry_completed",
                "sla_scan_retry_failed",
            }),
        )
    ).all()
    retry_requests = [event for event in retry_events if event.event_type == "sla_scan_retry_requested"]
    completed_retry_numbers = {
        _retry_number(event)
        for event in retry_events
        if event.event_type in {"sla_scan_retry_completed", "sla_scan_retry_failed"}
    }
    open_requests = [event for event in retry_requests if _retry_number(event) not in completed_retry_numbers]
    latest_open_request = max(open_requests, key=_retry_number) if open_requests else None
    if latest_open_request and not _retry_request_is_expired(latest_open_request, normalized_at):
        raise SlaScanRetryConflict("该失败扫描正在人工重试中，请稍后刷新运行结果")
    retry_number = max((_retry_number(event) for event in retry_requests), default=0) + 1
    execution = _start_scan_execution(session, actor, "retry", normalized_at, run_key)
    retry_payload = {
        "run_key": run_key,
        "retry_number": retry_number,
        "reason": normalized_reason,
        "requested_at": normalized_at.isoformat(),
    }
    try:
        audit.append("sla_scan_failure", run_key, "sla_scan_retry_requested", actor, retry_payload)
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        _finish_scan_execution(session, execution, "failed", None, error=exc)
        if isinstance(exc, IntegrityError):
            raise SlaScanRetryConflict("该失败扫描已被其他人员发起重试，请刷新后查看结果") from exc
        raise

    result = run_scheduled_sla_scan(
        session,
        now=normalized_at,
        run_key=run_key,
        actor=actor,
        trigger_type="retry",
        execution=execution,
    )
    retry_status = "completed" if result.get("status") == "completed" else "failed"
    AuditRepository(session).append(
        "sla_scan_failure",
        run_key,
        f"sla_scan_retry_{retry_status}",
        actor,
        {
            **retry_payload,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "result_status": retry_status,
            "deduplicated": bool(result.get("deduplicated")),
            "error_type": result.get("error_type"),
        },
    )
    session.commit()
    return {**result, "retry": {**retry_payload, "status": retry_status, "actor": actor}}


def _retry_number(event: AuditEventRecord) -> int:
    value = (event.payload or {}).get("retry_number")
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _retry_request_is_expired(event: AuditEventRecord, now: datetime) -> bool:
    requested_at = (event.payload or {}).get("requested_at")
    try:
        parsed = datetime.fromisoformat(requested_at.replace("Z", "+00:00")) if isinstance(requested_at, str) else event.created_at
    except ValueError:
        parsed = event.created_at
    normalized = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return normalized <= now - timedelta(minutes=RETRY_IN_PROGRESS_TIMEOUT_MINUTES)


def _start_scan_execution(
    session: Session,
    actor: str,
    trigger_type: str,
    started_at: datetime,
    run_key: str | None,
) -> dict:
    if trigger_type not in {"manual", "scheduler", "retry"}:
        raise ValueError("SLA 扫描执行来源必须为 manual、scheduler 或 retry")
    normalized_at = started_at if started_at.tzinfo else started_at.replace(tzinfo=timezone.utc)
    execution = {
        "execution_id": str(uuid4()),
        "started_at": normalized_at.isoformat(),
        "trigger_type": trigger_type,
        "run_key": run_key,
        "actor": actor,
        "status": "running",
    }
    expired_lease = _acquire_scan_lease(session, execution, normalized_at)
    if expired_lease and expired_lease.get("execution_id"):
        _record_expired_scan_execution(session, expired_lease, normalized_at)
    AuditRepository(session).append_root_once(
        "sla_scan_execution",
        execution["execution_id"],
        "sla_scan_started",
        actor,
        execution,
    )
    session.commit()
    return execution


def _finish_scan_execution(
    session: Session,
    execution: dict,
    status: str,
    result: dict | None,
    error: Exception | None = None,
) -> bool:
    if status not in {"completed", "failed", "aborted"}:
        raise ValueError("SLA 扫描执行结果必须为 completed、failed 或 aborted")
    prior_terminal = session.scalars(
        select(AuditEventRecord).where(
            AuditEventRecord.tenant_id == PLATFORM_INTERNAL_TENANT_ID,
            AuditEventRecord.scope_type == "platform",
            AuditEventRecord.aggregate_type == "sla_scan_execution",
            AuditEventRecord.aggregate_id == execution["execution_id"],
            AuditEventRecord.event_type.in_({
                "sla_scan_execution_timed_out",
                "sla_scan_execution_force_released",
            }),
        )
    ).first()
    recorded_status = f"late_{status}" if prior_terminal else status
    payload = {
        "execution_id": execution["execution_id"],
        "started_at": execution["started_at"],
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "trigger_type": execution["trigger_type"],
        "run_key": execution["run_key"],
        "status": recorded_status,
        "result_run_id": result.get("run_id") if result else None,
        "deduplicated": bool(result and result.get("deduplicated")),
        "error_type": type(error).__name__ if error else result.get("error_type") if result else None,
    }
    try:
        AuditRepository(session).append(
            "sla_scan_execution",
            execution["execution_id"],
            f"sla_scan_execution_{recorded_status}",
            execution["actor"],
            payload,
        )
        _release_scan_lease(session, execution["execution_id"])
        session.commit()
        return True
    except SQLAlchemyError:
        session.rollback()
        try:
            _release_scan_lease(session, execution["execution_id"])
            session.commit()
        except SQLAlchemyError:
            session.rollback()
        return False


def _acquire_scan_lease(session: Session, execution: dict, now: datetime) -> dict | None:
    expires_at = now + timedelta(minutes=SLA_SCAN_LEASE_HARD_EXPIRY_MINUTES)
    lease = session.get(SlaScanLeaseRecord, SLA_SCAN_LEASE_KEY)
    if lease is None:
        session.add(SlaScanLeaseRecord(
            lease_key=SLA_SCAN_LEASE_KEY,
            execution_id=execution["execution_id"],
            run_key=execution["run_key"],
            actor=execution["actor"],
            trigger_type=execution["trigger_type"],
            acquired_at=now,
            expires_at=expires_at,
            last_heartbeat_at=now,
            heartbeat_count=0,
        ))
        try:
            session.flush()
            return None
        except IntegrityError as exc:
            session.rollback()
            current = session.get(SlaScanLeaseRecord, SLA_SCAN_LEASE_KEY)
            raise SlaScanExecutionConflict(_scan_lease_to_dict(current, now)) from exc

    previous = _scan_lease_to_dict(lease, now)
    terminal_holder = None
    if lease.execution_id:
        terminal_holder = session.scalars(
            select(AuditEventRecord).where(
                AuditEventRecord.tenant_id == PLATFORM_INTERNAL_TENANT_ID,
                AuditEventRecord.scope_type == "platform",
                AuditEventRecord.aggregate_type == "sla_scan_execution",
                AuditEventRecord.aggregate_id == lease.execution_id,
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
        ).first()
    reclaimable_execution_id = lease.execution_id if terminal_holder else None
    updated = session.execute(
        update(SlaScanLeaseRecord)
        .where(
            SlaScanLeaseRecord.lease_key == SLA_SCAN_LEASE_KEY,
            or_(
                SlaScanLeaseRecord.execution_id.is_(None),
                SlaScanLeaseRecord.expires_at.is_(None),
                SlaScanLeaseRecord.expires_at <= now,
                SlaScanLeaseRecord.execution_id == reclaimable_execution_id if reclaimable_execution_id else False,
            ),
        )
        .values(
            execution_id=execution["execution_id"],
            run_key=execution["run_key"],
            actor=execution["actor"],
            trigger_type=execution["trigger_type"],
            acquired_at=now,
            expires_at=expires_at,
            last_heartbeat_at=now,
            heartbeat_count=0,
        )
        .execution_options(synchronize_session=False)
    )
    if updated.rowcount != 1:
        session.rollback()
        current = session.get(SlaScanLeaseRecord, SLA_SCAN_LEASE_KEY)
        raise SlaScanExecutionConflict(_scan_lease_to_dict(current, now))
    return previous if previous.get("execution_id") else None


def _release_scan_lease(session: Session, execution_id: str) -> None:
    session.execute(
        update(SlaScanLeaseRecord)
        .where(
            SlaScanLeaseRecord.lease_key == SLA_SCAN_LEASE_KEY,
            SlaScanLeaseRecord.execution_id == execution_id,
        )
        .values(
            execution_id=None,
            run_key=None,
            actor=None,
            trigger_type=None,
            acquired_at=None,
            expires_at=None,
            last_heartbeat_at=None,
            heartbeat_count=0,
        )
        .execution_options(synchronize_session=False)
    )


def _record_expired_scan_execution(session: Session, lease: dict, expired_at: datetime) -> None:
    execution_id = lease["execution_id"]
    terminal = session.scalars(
        select(AuditEventRecord).where(
            AuditEventRecord.tenant_id == PLATFORM_INTERNAL_TENANT_ID,
            AuditEventRecord.scope_type == "platform",
            AuditEventRecord.aggregate_type == "sla_scan_execution",
            AuditEventRecord.aggregate_id == execution_id,
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
    ).first()
    if terminal:
        return
    AuditRepository(session).append(
        "sla_scan_execution",
        execution_id,
        "sla_scan_execution_timed_out",
        "全域 SLA 运行锁",
        {
            "execution_id": execution_id,
            "started_at": lease.get("acquired_at"),
            "finished_at": expired_at.isoformat(),
            "trigger_type": lease.get("trigger_type"),
            "run_key": lease.get("run_key"),
            "status": "timed_out",
            "result_run_id": None,
            "deduplicated": False,
            "error_type": "ExecutionLeaseExpired",
        },
    )


def _scan_lease_to_dict(lease: SlaScanLeaseRecord | None, now: datetime) -> dict:
    if lease is None:
        return {
            "lease_key": SLA_SCAN_LEASE_KEY,
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
    expires_at = _as_utc(lease.expires_at) if lease.expires_at else None
    return {
        "lease_key": lease.lease_key,
        "execution_id": lease.execution_id,
        "run_key": lease.run_key,
        "actor": lease.actor,
        "trigger_type": lease.trigger_type,
        "acquired_at": _as_utc(lease.acquired_at).isoformat() if lease.acquired_at else None,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "remaining_seconds": max(0, int((expires_at - now).total_seconds())) if expires_at else 0,
        "warning_after_seconds": SLA_SCAN_EXECUTION_TIMEOUT_MINUTES * 60,
        "last_heartbeat_at": _as_utc(lease.last_heartbeat_at).isoformat() if lease.last_heartbeat_at else None,
        "heartbeat_count": lease.heartbeat_count or 0,
    }


def _renew_scan_lease(session: Session, execution_id: str, now: datetime | None = None) -> bool:
    heartbeat_at = _as_utc(now or datetime.now(timezone.utc))
    renewed = session.execute(
        update(SlaScanLeaseRecord)
        .where(
            SlaScanLeaseRecord.lease_key == SLA_SCAN_LEASE_KEY,
            SlaScanLeaseRecord.execution_id == execution_id,
        )
        .values(
            expires_at=heartbeat_at + timedelta(minutes=SLA_SCAN_LEASE_HARD_EXPIRY_MINUTES),
            last_heartbeat_at=heartbeat_at,
            heartbeat_count=SlaScanLeaseRecord.heartbeat_count + 1,
        )
        .execution_options(synchronize_session=False)
    )
    session.commit()
    return renewed.rowcount == 1


def _assert_scan_lease_owned(session: Session, execution_id: str, final: bool = False) -> None:
    statement = select(SlaScanLeaseRecord.execution_id).where(
        SlaScanLeaseRecord.lease_key == SLA_SCAN_LEASE_KEY,
    )
    if final:
        statement = statement.with_for_update()
    current_execution_id = session.scalar(statement)
    if current_execution_id != execution_id:
        raise SlaScanLeaseLost("当前扫描租约已被释放或接管，旧执行已停止写入")


def _record_scan_lease_lost(session: Session, execution: dict, error: Exception) -> None:
    try:
        AuditRepository(session).append(
            "sla_scan_execution",
            execution["execution_id"],
            "sla_scan_execution_lease_lost",
            execution["actor"],
            {
                "execution_id": execution["execution_id"],
                "started_at": execution["started_at"],
                "detected_at": datetime.now(timezone.utc).isoformat(),
                "trigger_type": execution["trigger_type"],
                "run_key": execution["run_key"],
                "status": "lease_lost",
                "error_type": type(error).__name__,
                "message": str(error),
            },
        )
        session.commit()
    except SQLAlchemyError:
        session.rollback()


def force_release_scan_lease(
    session: Session,
    expected_execution_id: str,
    actor: str,
    reason: str,
    now: datetime | None = None,
) -> dict:
    normalized_reason = reason.strip()
    if not 5 <= len(normalized_reason) <= 1000:
        raise ValueError("受控释放原因长度必须为 5—1000 个字符")
    release_at = _as_utc(now or datetime.now(timezone.utc))
    lease = session.get(SlaScanLeaseRecord, SLA_SCAN_LEASE_KEY)
    if lease is None or lease.execution_id is None:
        raise SlaScanLeaseReleaseNotFound("当前没有可释放的全域扫描租约")
    if lease.execution_id != expected_execution_id:
        raise SlaScanLeaseReleaseConflict("扫描租约已变化，请刷新后核对当前执行再操作")

    acquired_at = _as_utc(lease.acquired_at) if lease.acquired_at else None
    elapsed_seconds = max(0, int((release_at - acquired_at).total_seconds())) if acquired_at else 0
    terminal = session.scalars(
        select(AuditEventRecord).where(
            AuditEventRecord.tenant_id == PLATFORM_INTERNAL_TENANT_ID,
            AuditEventRecord.scope_type == "platform",
            AuditEventRecord.aggregate_type == "sla_scan_execution",
            AuditEventRecord.aggregate_id == expected_execution_id,
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
    ).first()
    if terminal is None and elapsed_seconds < SLA_SCAN_EXECUTION_TIMEOUT_MINUTES * 60:
        raise SlaScanLeaseReleaseConflict(
            f"扫描尚未达到 {SLA_SCAN_EXECUTION_TIMEOUT_MINUTES} 分钟预警阈值，不能提前释放运行保护"
        )

    snapshot = _scan_lease_to_dict(lease, release_at)
    released = session.execute(
        update(SlaScanLeaseRecord)
        .where(
            SlaScanLeaseRecord.lease_key == SLA_SCAN_LEASE_KEY,
            SlaScanLeaseRecord.execution_id == expected_execution_id,
        )
        .values(
            execution_id=None,
            run_key=None,
            actor=None,
            trigger_type=None,
            acquired_at=None,
            expires_at=None,
            last_heartbeat_at=None,
            heartbeat_count=0,
        )
        .execution_options(synchronize_session=False)
    )
    if released.rowcount != 1:
        session.rollback()
        raise SlaScanLeaseReleaseConflict("扫描租约已被其他人员处理，请刷新后查看最新状态")
    terminal_cleanup = terminal is not None
    payload = {
        "execution_id": expected_execution_id,
        "started_at": snapshot.get("acquired_at"),
        "finished_at": release_at.isoformat(),
        "trigger_type": snapshot.get("trigger_type"),
        "run_key": snapshot.get("run_key"),
        "status": "terminal_lease_released" if terminal_cleanup else "force_released",
        "result_run_id": None,
        "deduplicated": False,
        "error_type": "TerminalExecutionLeaseCleanup" if terminal_cleanup else "ExecutionLeaseForceReleased",
        "reason": normalized_reason,
        "released_by": actor,
        "lease_snapshot": snapshot,
        "terminal_event_type": terminal.event_type if terminal else None,
    }
    try:
        AuditRepository(session).append(
            "sla_scan_execution",
            expected_execution_id,
            "sla_scan_execution_terminal_lease_released" if terminal_cleanup else "sla_scan_execution_force_released",
            actor,
            payload,
        )
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise
    return payload


def _record_scheduled_scan_skip(
    session: Session,
    run_key: str,
    run_at: datetime,
    actor: str,
    active_execution: dict,
) -> tuple[dict, bool]:
    normalized_at = run_at if run_at.tzinfo else run_at.replace(tzinfo=timezone.utc)
    event, created = AuditRepository(session).append_root_once(
        "sla_scan_skip",
        run_key,
        "sla_scan_skipped",
        actor,
        {
            "run_key": run_key,
            "run_at": normalized_at.isoformat(),
            "reason": "scan_in_progress",
            "active_execution": active_execution,
        },
    )
    session.commit()
    return event, created


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _record_scan_failure(session: Session, run_key: str, run_at: datetime, error: Exception, actor: str = SCHEDULER_NAME) -> dict:
    normalized_at = run_at if run_at.tzinfo else run_at.replace(tzinfo=timezone.utc)
    error_type = type(error).__name__
    error_message = "全域扫描执行异常，请检查调度器、数据库连接和服务日志。"
    failure = {
        "run_id": run_key,
        "run_key": run_key,
        "run_at": normalized_at.isoformat(),
        "trigger_type": "scheduler",
        "status": "failed",
        "deduplicated": False,
        "error_type": error_type,
        "error_message": error_message,
    }
    event, created = AuditRepository(session).append_root_once(
        "sla_scan_failure",
        run_key,
        "sla_scan_failed",
        actor,
        failure,
    )
    stored = dict(event["payload"])
    stored["deduplicated"] = not created
    notifications = NotificationRepository(session)
    for role in ("operations", "admin"):
        notifications.create_if_absent(
            PLATFORM_INTERNAL_TENANT_ID,
            {
                "case_id": None,
                "counterparty_id": None,
                "recipient_role": role,
                "recipient_subject": None,
                "category": "sla_scan",
                "level": "scan_failed",
                "severity": "critical",
                "title": "全域 SLA 自动扫描失败",
                "message": f"任务 {run_key} 执行失败（{error_type}）。请检查自动调度和服务运行状态。",
                "action_json": {},
                "dedup_key": f"sla-scan-failed:{run_key}:{role}",
                "status": "unread",
            }
        )
    return stored


def main() -> int:
    with SessionLocal() as session:
        result = run_scheduled_sla_scan(session)
    print(json.dumps(result, ensure_ascii=False))
    return 2 if result.get("status") == "failed" else 3 if result.get("status") == "aborted" else 0


if __name__ == "__main__":
    raise SystemExit(main())
