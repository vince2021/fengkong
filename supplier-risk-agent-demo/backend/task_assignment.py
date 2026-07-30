from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from backend.credit_authority import authority_has_signer, authority_owner_roles
from backend.db_models import ApprovalCaseRecord, DocumentCorrectionRecord, NotificationRecord
from backend.repository import AuditRepository, NotificationRepository
from backend.security import APPROVAL_STAGE_ROLES, Principal
from backend.task_lease import (
    assignment_expiry,
    assignment_is_active,
    assignment_is_expired,
    clear_assignment,
    lease_remaining_seconds,
    renew_assignment_lease,
    start_assignment_lease,
)


class TaskAssignmentNotFound(LookupError):
    pass


class TaskAssignmentConflict(RuntimeError):
    pass


class TaskAssignmentForbidden(PermissionError):
    pass


SUPERVISOR_REMINDER_INTERVAL_MINUTES = 30


def change_task_assignment(
    session: Session,
    task_type: str,
    task_id: str,
    action: str,
    expected_row_version: int,
    principal: Principal,
) -> dict:
    record = _get_task_record(session, task_type, task_id)
    _ensure_task_is_active(task_type, record)
    _ensure_role_is_eligible(task_type, record, principal)
    if record.row_version != expected_row_version:
        raise TaskAssignmentConflict(f"任务版本已变化，当前版本为 {record.row_version}")

    if action == "claim":
        active_assignment = assignment_is_active(record)
        expired_assignee = record.assigned_to if assignment_is_expired(record) else None
        expired_assignee_name = record.assigned_to_name if expired_assignee else None
        if active_assignment and record.assigned_to != principal.subject:
            raise TaskAssignmentConflict(f"任务已由{record.assigned_to_name or '其他人员'}认领")
        if active_assignment and record.assigned_to == principal.subject:
            return _assignment_result(task_type, record)
        record.assigned_to = principal.subject
        record.assigned_to_name = principal.name
        start_assignment_lease(record)
        event_type = "personal_task_claimed"
    elif action == "renew":
        if not assignment_is_active(record):
            raise TaskAssignmentConflict("任务认领已过期，请重新认领")
        if record.assigned_to != principal.subject:
            raise TaskAssignmentForbidden("只能续期本人认领的任务")
        previous_expires_at = assignment_expiry(record)
        renew_assignment_lease(record)
        event_type = "personal_task_lease_renewed"
    elif action == "release":
        if record.assigned_to and record.assigned_to != principal.subject and "admin" not in principal.roles:
            raise TaskAssignmentForbidden("只能释放本人认领的任务")
        if not record.assigned_to:
            return _assignment_result(task_type, record)
        previous_assignee = record.assigned_to
        previous_assignee_name = record.assigned_to_name
        previous_expires_at = assignment_expiry(record)
        clear_assignment(record)
        event_type = "personal_task_released"
    else:
        raise ValueError("不支持的任务认领动作")

    audit = AuditRepository(session)
    try:
        session.flush()
        audit.append(
            "approval_case" if task_type == "approval" else "document_correction",
            task_id,
            event_type,
            principal.name,
            {
                "task_type": task_type,
                "stage": record.current_stage if task_type == "approval" else "supplement",
                "assigned_role": None if task_type == "approval" else record.assigned_role,
                "assigned_to": record.assigned_to,
                "assigned_to_name": record.assigned_to_name,
                "assignment_expires_at": assignment_expiry(record).isoformat() if assignment_expiry(record) else None,
                **(
                    {
                        "previous_assignee": previous_assignee,
                        "previous_assignee_name": previous_assignee_name,
                        "previous_assignment_expires_at": previous_expires_at.isoformat() if previous_expires_at else None,
                    }
                    if action == "release"
                    else {}
                ),
                **(
                    {
                        "previous_assignment_expires_at": previous_expires_at.isoformat() if previous_expires_at else None,
                    }
                    if action == "renew"
                    else {}
                ),
                **(
                    {
                        "expired_assignee": expired_assignee,
                        "expired_assignee_name": expired_assignee_name,
                    }
                    if action == "claim" and expired_assignee
                    else {}
                ),
            },
        )
        session.commit()
    except StaleDataError as exc:
        session.rollback()
        raise TaskAssignmentConflict("任务已被其他人员更新，请刷新后重试") from exc
    session.refresh(record)
    return _assignment_result(task_type, record)


def release_task_as_supervisor(
    session: Session,
    task_type: str,
    task_id: str,
    expected_row_version: int,
    reason: str,
    principal: Principal,
) -> dict:
    record = _get_task_record(session, task_type, task_id)
    _ensure_task_is_active(task_type, record)
    if record.row_version != expected_row_version:
        raise TaskAssignmentConflict(f"任务版本已变化，当前版本为 {record.row_version}")
    if not assignment_is_active(record):
        raise TaskAssignmentConflict("任务当前没有有效的个人占用")
    previous_assignee = record.assigned_to
    previous_assignee_name = record.assigned_to_name
    previous_expires_at = assignment_expiry(record)
    clear_assignment(record)
    audit = AuditRepository(session)
    try:
        session.flush()
        audit.append(
            "approval_case" if task_type == "approval" else "document_correction",
            task_id,
            "personal_task_supervisor_released",
            principal.name,
            {
                "task_type": task_type,
                "reason": reason,
                "previous_assignee": previous_assignee,
                "previous_assignee_name": previous_assignee_name,
                "previous_assignment_expires_at": previous_expires_at.isoformat() if previous_expires_at else None,
                "supervisor_subject": principal.subject,
                "supervisor_roles": list(principal.roles),
            },
        )
        session.commit()
    except StaleDataError as exc:
        session.rollback()
        raise TaskAssignmentConflict("任务已被其他人员更新，请刷新后重试") from exc
    session.refresh(record)
    return _assignment_result(task_type, record)


def remind_task_as_supervisor(
    session: Session,
    task_type: str,
    task_id: str,
    expected_row_version: int,
    reason: str,
    principal: Principal,
) -> dict:
    record = _get_task_record(session, task_type, task_id)
    _ensure_task_is_active(task_type, record)
    if record.row_version != expected_row_version:
        raise TaskAssignmentConflict(f"任务版本已变化，当前版本为 {record.row_version}")
    if not assignment_is_active(record):
        raise TaskAssignmentConflict("任务当前没有可定向催办的认领人")
    case_id = record.case_id
    if not case_id:
        raise ValueError("未关联审批申请的任务不能发送站内催办")
    now = datetime.now(timezone.utc)
    dedup_prefix = f"task-supervisor-reminder:{task_type}:{task_id}:{record.assigned_to}:"
    recent = session.scalars(
        select(NotificationRecord).where(
            NotificationRecord.category == "task_assignment",
            NotificationRecord.level == "supervisor_reminder",
            NotificationRecord.recipient_subject == record.assigned_to,
            NotificationRecord.dedup_key.like(f"{dedup_prefix}%"),
            NotificationRecord.created_at >= now - timedelta(minutes=SUPERVISOR_REMINDER_INTERVAL_MINUTES),
        ).order_by(NotificationRecord.created_at.desc())
    ).first()
    if recent:
        raise TaskAssignmentConflict("同一任务两次定向催办至少间隔 30 分钟")
    action = {
        "page": "approvals" if task_type == "approval" else "documents",
        "counterparty_id": record.counterparty_id,
        "case_id": case_id,
        **({"correction_id": record.id} if task_type == "correction" else {}),
    }
    notification_payload = {
        "case_id": case_id,
        "counterparty_id": record.counterparty_id,
        "recipient_role": "personal",
        "recipient_subject": record.assigned_to,
        "category": "task_assignment",
        "level": "supervisor_reminder",
        "severity": "warning",
        "title": "团队任务定向催办",
        "message": f"{record.assigned_to_name or '任务处理人'}，当前任务需要尽快处理。催办原因：{reason}",
        "action_json": action,
        "dedup_key": f"{dedup_prefix}{now.isoformat()}",
        "status": "unread",
    }
    notifications = NotificationRepository(session)
    audit = AuditRepository(session)
    notification, _ = notifications.create_if_absent(notification_payload)
    audit.append(
        "approval_case" if task_type == "approval" else "document_correction",
        task_id,
        "personal_task_supervisor_reminded",
        principal.name,
        {
            "task_type": task_type,
            "reason": reason,
            "recipient_subject": record.assigned_to,
            "recipient_name": record.assigned_to_name,
            "notification_id": notification["id"],
            "supervisor_subject": principal.subject,
        },
    )
    session.commit()
    return notification


def _get_task_record(
    session: Session,
    task_type: str,
    task_id: str,
) -> ApprovalCaseRecord | DocumentCorrectionRecord:
    if task_type == "approval":
        record = session.get(ApprovalCaseRecord, task_id)
    elif task_type == "correction":
        record = session.get(DocumentCorrectionRecord, task_id)
    else:
        raise ValueError("不支持的任务类型")
    if not record:
        raise TaskAssignmentNotFound("任务不存在")
    return record


def _ensure_task_is_active(
    task_type: str,
    record: ApprovalCaseRecord | DocumentCorrectionRecord,
) -> None:
    active = record.status == "处理中" if task_type == "approval" else record.status in {"open", "resubmitted"}
    if not active:
        raise TaskAssignmentConflict("任务当前不处于可认领状态")


def _ensure_role_is_eligible(
    task_type: str,
    record: ApprovalCaseRecord | DocumentCorrectionRecord,
    principal: Principal,
) -> None:
    if "admin" in principal.roles:
        return
    roles = set(principal.roles)
    if task_type == "approval":
        eligible = (
            authority_owner_roles(record, APPROVAL_STAGE_ROLES.get(record.current_stage, set()))
            if record.current_stage == "final_strategy"
            else set(APPROVAL_STAGE_ROLES.get(record.current_stage, set()))
        )
    else:
        eligible = {record.assigned_role}
        if record.status == "open":
            eligible.add("client")
    if not eligible.intersection(roles):
        raise TaskAssignmentForbidden("当前角色不能认领此任务")
    if (
        task_type == "approval"
        and record.current_stage == "final_strategy"
        and authority_has_signer(record, principal.subject)
    ):
        raise TaskAssignmentForbidden("你已签署前序会签席位，不能再认领后续席位")
    if "client" in roles and principal.counterparty_id != record.counterparty_id:
        raise TaskAssignmentForbidden("企业客户只能认领本企业任务")


def _assignment_result(
    task_type: str,
    record: ApprovalCaseRecord | DocumentCorrectionRecord,
) -> dict:
    return {
        "task_type": task_type,
        "task_id": record.case_id if task_type == "approval" else record.id,
        "assigned_to": record.assigned_to,
        "assigned_to_name": record.assigned_to_name,
        "assigned_at": record.assigned_at.isoformat() if record.assigned_at else None,
        "assignment_expires_at": assignment_expiry(record).isoformat() if assignment_expiry(record) else None,
        "lease_remaining_seconds": lease_remaining_seconds(record),
        "row_version": record.row_version,
    }
