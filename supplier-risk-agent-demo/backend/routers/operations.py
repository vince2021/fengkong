from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.database import get_db_session
from backend.dependencies import get_document_repository
from backend.repository import ConcurrentUpdateError, DocumentRepository
from backend.schemas import DocumentCorrectionActionRequest, PersonalTaskAssignmentRequest, SupervisorTaskReleaseRequest, SupervisorTaskReminderRequest
from backend.security import Principal, require_permissions
from backend.sla_monitor import build_operations_summary, build_personal_task_queue, build_team_task_board, run_sla_scan
from backend.task_assignment import TaskAssignmentConflict, TaskAssignmentForbidden, TaskAssignmentNotFound, change_task_assignment, release_task_as_supervisor, remind_task_as_supervisor


router = APIRouter(prefix="/operations", tags=["operations"])


@router.get("/sla/summary")
def sla_summary(
    session: Session = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("operations:view")),
) -> dict:
    return build_operations_summary(
        session,
        recipient_roles=None if "admin" in principal.roles else principal.roles,
        recipient_subject=None if "admin" in principal.roles else principal.subject,
        counterparty_id=principal.counterparty_id if "client" in principal.roles else None,
    )


@router.get("/my-tasks")
def personal_task_queue(
    limit: int = Query(default=200, ge=1, le=500),
    session: Session = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("approvals:view")),
) -> dict:
    return build_personal_task_queue(
        session,
        principal.roles,
        principal.counterparty_id if "client" in principal.roles else None,
        actor_subject=principal.subject,
        limit=limit,
    )


@router.post("/my-tasks/{task_type}/{task_id}/assignment")
def update_personal_task_assignment(
    task_type: Literal["approval", "correction"],
    task_id: str,
    request: PersonalTaskAssignmentRequest,
    session: Session = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("approvals:act")),
) -> dict:
    try:
        return change_task_assignment(
            session,
            task_type,
            task_id,
            request.action,
            request.expected_row_version,
            principal,
        )
    except TaskAssignmentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TaskAssignmentForbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TaskAssignmentConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/team-tasks")
def team_task_board(
    limit: int = Query(default=500, ge=1, le=500),
    session: Session = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("operations:view")),
) -> dict:
    return build_team_task_board(
        session,
        limit=limit,
        can_manage=principal.can("tasks:manage"),
    )


@router.post("/team-tasks/{task_type}/{task_id}/release")
def supervisor_release_task(
    task_type: Literal["approval", "correction"],
    task_id: str,
    request: SupervisorTaskReleaseRequest,
    session: Session = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("tasks:manage")),
) -> dict:
    try:
        return release_task_as_supervisor(
            session,
            task_type,
            task_id,
            request.expected_row_version,
            request.reason,
            principal,
        )
    except TaskAssignmentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TaskAssignmentForbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TaskAssignmentConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/team-tasks/{task_type}/{task_id}/remind")
def supervisor_remind_task(
    task_type: Literal["approval", "correction"],
    task_id: str,
    request: SupervisorTaskReminderRequest,
    session: Session = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("tasks:manage")),
) -> dict:
    try:
        return remind_task_as_supervisor(
            session,
            task_type,
            task_id,
            request.expected_row_version,
            request.reason,
            principal,
        )
    except TaskAssignmentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TaskAssignmentForbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TaskAssignmentConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/sla/scan")
def scan_sla(
    session: Session = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("sla:scan")),
) -> dict:
    return run_sla_scan(session, actor=principal.name)


@router.get("/document-corrections")
def document_correction_workbench(
    active_only: bool = True,
    repository: DocumentRepository = Depends(get_document_repository),
    principal: Principal = Depends(require_permissions("operations:view")),
) -> list[dict]:
    return repository.list_correction_workbench(active_only)


@router.post("/document-corrections/{correction_id}/actions")
def act_on_document_correction(
    correction_id: str,
    request: DocumentCorrectionActionRequest,
    repository: DocumentRepository = Depends(get_document_repository),
    principal: Principal = Depends(require_permissions("corrections:act")),
) -> dict:
    try:
        repository.act_on_correction(
            correction_id,
            request.expected_row_version,
            request.action,
            request.reason,
            principal.name,
            request.assigned_role,
            request.extension_hours,
        )
        return next(
            item for item in repository.list_correction_workbench(False)
            if item["id"] == correction_id
        )
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail="补件任务不存在") from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
