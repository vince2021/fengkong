from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db_models import ApprovalCaseRecord, AuditEventRecord, NotificationRecord
from backend.repository import AuditRepository, NotificationRepository
from backend.security import APPROVAL_STAGE_ROLES
from rating.approval_workflow import STAGE_SLA_HOURS, stage_label


ACTIVE_STATUSES = {"处理中", "待补件"}
ESCALATION_AFTER_SECONDS = 4 * 3600


def run_sla_scan(session: Session, now: datetime | None = None, actor: str = "sla-monitor") -> dict:
    scan_time = _as_utc(now or datetime.now(timezone.utc))
    cases = session.scalars(
        select(ApprovalCaseRecord).where(
            ApprovalCaseRecord.status.in_(ACTIVE_STATUSES),
            ApprovalCaseRecord.stage_due_at.is_not(None),
        )
    ).all()
    notifications = NotificationRepository(session)
    audit = AuditRepository(session)
    level_counts: Counter[str] = Counter()
    created_count = 0

    for case in cases:
        level = _sla_level(case, scan_time)
        if not level:
            continue
        level_counts[level] += 1
        roles = _recipient_roles(case.current_stage, level)
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

    result = {
        "run_id": str(uuid4()),
        "run_at": scan_time.isoformat(),
        "active_cases_scanned": len(cases),
        "due_soon_cases": level_counts["due_soon"],
        "overdue_cases": level_counts["overdue"],
        "escalated_cases": level_counts["escalated"],
        "notifications_created": created_count,
    }
    audit.append("sla_scan", result["run_id"], "sla_scan_completed", actor, result)
    session.commit()
    return result


def build_operations_summary(session: Session, now: datetime | None = None) -> dict:
    scan_time = _as_utc(now or datetime.now(timezone.utc))
    cases = session.scalars(select(ApprovalCaseRecord)).all()
    active_cases = [case for case in cases if case.status in ACTIVE_STATUSES]
    sla_counts: Counter[str] = Counter()
    stage_counts: Counter[str] = Counter()
    for case in active_cases:
        stage_counts[case.current_stage] += 1
        level = _sla_level(case, scan_time)
        sla_counts[level or "normal"] += 1
    unread = session.scalars(select(NotificationRecord).where(NotificationRecord.status == "unread")).all()
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
                "notifications_created": last_scan.payload.get("notifications_created", 0),
            }
            if last_scan
            else None
        ),
        "stage_distribution": [
            {"stage": stage, "label": stage_label(stage), "count": count}
            for stage, count in sorted(stage_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
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


def _recipient_roles(stage: str, level: str) -> set[str]:
    roles = set(APPROVAL_STAGE_ROLES.get(stage, set()))
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
        "dedup_key": f"sla:{case.case_id}:{case.current_stage}:{started_at}:{level}:{role}",
        "status": "unread",
    }


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
