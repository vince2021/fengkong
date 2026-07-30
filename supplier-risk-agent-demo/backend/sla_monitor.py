from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from backend.credit_authority import authority_has_signer, authority_owner_roles
from backend.db_models import ApprovalCaseRecord, AuditEventRecord, DocumentCorrectionRecord, NotificationRecord
from backend.document_correction_sla import ACTIVE_CORRECTION_STATUSES, correction_sla_snapshot
from backend.repository import AuditRepository, NotificationRepository
from backend.security import APPROVAL_STAGE_ROLES
from backend.task_lease import assignment_expiry, assignment_is_active, assignment_is_expired, clear_assignment, lease_remaining_seconds
from rating.approval_workflow import STAGE_SLA_HOURS, stage_label


ACTIVE_STATUSES = {"处理中", "待补件"}
SLA_SCANNABLE_STATUSES = {"处理中"}
ESCALATION_AFTER_SECONDS = 4 * 3600
ASSIGNMENT_LEASE_WARNING_SECONDS = 30 * 60


def run_sla_scan(session: Session, now: datetime | None = None, actor: str = "sla-monitor") -> dict:
    scan_time = _as_utc(now or datetime.now(timezone.utc))
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

    for case in cases:
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

    for correction in corrections:
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

    result = {
        "run_id": str(uuid4()),
        "run_at": scan_time.isoformat(),
        "active_cases_scanned": len(cases),
        "due_soon_cases": level_counts["due_soon"],
        "overdue_cases": level_counts["overdue"],
        "escalated_cases": level_counts["escalated"],
        "active_corrections_scanned": len(corrections),
        "due_soon_corrections": correction_level_counts["due_soon"],
        "overdue_corrections": correction_level_counts["overdue"],
        "escalated_corrections": correction_level_counts["escalated"],
        "notifications_created": created_count,
        "expired_assignments_released": expired_assignments_released,
    }
    audit.append("sla_scan", result["run_id"], "sla_scan_completed", actor, result)
    session.commit()
    return result


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
        .where(AuditEventRecord.event_type == "sla_scan_completed")
        .order_by(AuditEventRecord.payload["run_at"].as_string().desc())
        .limit(1)
    ).first()
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
        "unread_notifications": {
            "total": len(unread),
            "info": severity_counts["info"],
            "warning": severity_counts["warning"],
            "critical": severity_counts["critical"],
        },
        "last_scan": (
            {
                "run_id": last_scan.aggregate_id,
                "run_at": last_scan.payload.get("run_at"),
                "actor": last_scan.actor,
                "active_cases_scanned": last_scan.payload.get("active_cases_scanned", 0),
                "active_corrections_scanned": last_scan.payload.get("active_corrections_scanned", 0),
                "notifications_created": last_scan.payload.get("notifications_created", 0),
                "expired_assignments_released": last_scan.payload.get("expired_assignments_released", 0),
            }
            if last_scan
            else None
        ),
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
                "row_version": correction.row_version,
                "action": {
                    "page": "documents",
                    "counterparty_id": correction.counterparty_id,
                    "correction_id": correction.id,
                    **({"case_id": correction.case_id} if correction.case_id else {}),
                },
            }
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
        is_claimed = task["assignment_state"] == "assigned_other"
        is_risk = task["sla_status"] != "normal"
        for role in task["owner_roles"]:
            counters = role_load.setdefault(role, Counter())
            counters["total"] += 1
            counters["claimed" if is_claimed else "unassigned"] += 1
            if is_risk:
                counters["risk"] += 1
        assignee_key = (
            task["assigned_to"] if is_claimed else None,
            task["assigned_to_name"] if is_claimed else "未认领",
        )
        assignee_counters = assignee_load.setdefault(assignee_key, Counter())
        assignee_counters["total"] += 1
        assignee_counters["risk"] += int(is_risk)
        task["can_release"] = False
        task["can_force_release"] = bool(can_manage and is_claimed)

    returned_tasks = tasks[:limit]
    return {
        "generated_at": board_time.isoformat(),
        "summary": {
            "total": len(tasks),
            "returned": len(returned_tasks),
            "truncated": len(returned_tasks) < len(tasks),
            "claimed": sum(task["assignment_state"] == "assigned_other" for task in tasks),
            "unassigned": sum(task["assignment_state"] == "unassigned" for task in tasks),
            "expired": sum(task["assignment_expired"] for task in tasks),
            "at_risk": sum(task["sla_status"] != "normal" for task in tasks),
        },
        "role_load": [
            {
                "role": role,
                "total": counters["total"],
                "claimed": counters["claimed"],
                "unassigned": counters["unassigned"],
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
