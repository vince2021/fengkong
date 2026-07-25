from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.dependencies import get_notification_repository
from backend.repository import NotificationRepository
from backend.security import Principal, require_permissions


router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def list_notifications(
    unread_only: bool = False,
    limit: int = Query(default=100, ge=1, le=200),
    repository: NotificationRepository = Depends(get_notification_repository),
    principal: Principal = Depends(require_permissions("notifications:view")),
) -> list[dict]:
    recipient_roles = None if "admin" in principal.roles else principal.roles
    counterparty_id = principal.counterparty_id if "client" in principal.roles else None
    return repository.list(recipient_roles, "unread" if unread_only else None, counterparty_id, limit)


@router.post("/{notification_id}/read")
def mark_notification_read(
    notification_id: str,
    repository: NotificationRepository = Depends(get_notification_repository),
    principal: Principal = Depends(require_permissions("notifications:act")),
) -> dict:
    notification = repository.get(notification_id)
    if not notification or not _can_access_notification(principal, notification):
        raise HTTPException(status_code=404, detail="通知不存在")
    updated = repository.mark_read(notification_id, principal.name)
    if not updated:
        raise HTTPException(status_code=404, detail="通知不存在")
    return updated


def _can_access_notification(principal: Principal, notification: dict) -> bool:
    if "admin" in principal.roles:
        return True
    if notification["recipient_role"] not in principal.roles:
        return False
    return "client" not in principal.roles or principal.counterparty_id == notification["counterparty_id"]
