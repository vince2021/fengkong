from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.dependencies import get_notification_delivery_repository, get_notification_repository
from backend.notification_delivery_repository import NotificationDeliveryError, NotificationDeliveryRepository
from backend.repository import NotificationRepository
from backend.schemas import TenantNotificationChannelCreate, TenantNotificationChannelUpdate, TenantNotificationDeliveryAction, TenantNotificationDispatchRequest
from backend.security import Principal, require_permissions


router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/channels")
def list_notification_channels(
    repository: NotificationDeliveryRepository = Depends(get_notification_delivery_repository),
    principal: Principal = Depends(require_permissions("notification_channels:view")),
) -> list[dict]:
    return repository.list_channels(principal.tenant_id)


@router.post("/channels", status_code=201)
def create_notification_channel(
    body: TenantNotificationChannelCreate,
    repository: NotificationDeliveryRepository = Depends(get_notification_delivery_repository),
    principal: Principal = Depends(require_permissions("notification_channels:manage")),
) -> dict:
    try:
        return repository.create_channel(principal.tenant_id, body.model_dump(), principal.subject, principal.name)
    except NotificationDeliveryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.put("/channels/{channel_id}")
def update_notification_channel(
    channel_id: str,
    body: TenantNotificationChannelUpdate,
    repository: NotificationDeliveryRepository = Depends(get_notification_delivery_repository),
    principal: Principal = Depends(require_permissions("notification_channels:manage")),
) -> dict:
    try:
        payload = body.model_dump(exclude={"expected_row_version"})
        return repository.update_channel(
            principal.tenant_id, channel_id, body.expected_row_version, payload, principal.subject,
        )
    except NotificationDeliveryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/channels/{channel_id}/test")
def test_notification_channel(
    channel_id: str,
    body: TenantNotificationDeliveryAction,
    repository: NotificationDeliveryRepository = Depends(get_notification_delivery_repository),
    principal: Principal = Depends(require_permissions("notification_channels:manage")),
) -> dict:
    try:
        return repository.test_channel(
            principal.tenant_id, channel_id, body.expected_row_version, principal.subject,
        )
    except NotificationDeliveryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/deliveries")
def list_notification_deliveries(
    status: str | None = Query(default=None, pattern=r"^(pending|retry_scheduled|delivered|dead_letter|cancelled)$"),
    limit: int = Query(default=100, ge=1, le=500),
    repository: NotificationDeliveryRepository = Depends(get_notification_delivery_repository),
    principal: Principal = Depends(require_permissions("notification_channels:view")),
) -> dict:
    return repository.list_deliveries(principal.tenant_id, status=status, limit=limit)


@router.get("/deliveries/operations")
def notification_delivery_operations(
    window_hours: int = Query(default=24, ge=1, le=168),
    repository: NotificationDeliveryRepository = Depends(get_notification_delivery_repository),
    principal: Principal = Depends(require_permissions("notification_channels:view")),
) -> dict:
    return repository.delivery_operations(principal.tenant_id, window_hours=window_hours)


@router.post("/deliveries/dispatch")
def dispatch_notification_deliveries(
    body: TenantNotificationDispatchRequest,
    repository: NotificationDeliveryRepository = Depends(get_notification_delivery_repository),
    principal: Principal = Depends(require_permissions("notification_channels:manage")),
) -> dict:
    try:
        return repository.scan_and_dispatch(principal.tenant_id, principal.subject, limit=body.limit)
    except NotificationDeliveryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/deliveries/{delivery_id}/retry")
def retry_notification_delivery(
    delivery_id: str,
    body: TenantNotificationDeliveryAction,
    repository: NotificationDeliveryRepository = Depends(get_notification_delivery_repository),
    principal: Principal = Depends(require_permissions("notification_channels:manage")),
) -> dict:
    try:
        return repository.retry_delivery(
            principal.tenant_id, delivery_id, body.expected_row_version, principal.subject,
        )
    except NotificationDeliveryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/deliveries/{delivery_id}/redeliver")
def redeliver_notification_delivery(
    delivery_id: str,
    body: TenantNotificationDeliveryAction,
    repository: NotificationDeliveryRepository = Depends(get_notification_delivery_repository),
    principal: Principal = Depends(require_permissions("notification_channels:manage")),
) -> dict:
    try:
        return repository.retry_delivery(
            principal.tenant_id, delivery_id, body.expected_row_version, principal.subject, redeliver=True,
        )
    except NotificationDeliveryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("")
def list_notifications(
    unread_only: bool = False,
    limit: int = Query(default=100, ge=1, le=200),
    repository: NotificationRepository = Depends(get_notification_repository),
    principal: Principal = Depends(require_permissions("notifications:view")),
) -> list[dict]:
    recipient_roles = None if "admin" in principal.roles else principal.roles
    counterparty_id = principal.counterparty_id if "client" in principal.roles else None
    return repository.list(
        principal.tenant_id,
        recipient_roles,
        None if "admin" in principal.roles else principal.subject,
        "unread" if unread_only else None,
        counterparty_id,
        limit,
    )


@router.post("/{notification_id}/read")
def mark_notification_read(
    notification_id: str,
    repository: NotificationRepository = Depends(get_notification_repository),
    principal: Principal = Depends(require_permissions("notifications:act")),
) -> dict:
    notification = repository.get(principal.tenant_id, notification_id)
    if not notification or not _can_access_notification(principal, notification):
        raise HTTPException(status_code=404, detail="通知不存在")
    updated = repository.mark_read(principal.tenant_id, notification_id, principal.name)
    if not updated:
        raise HTTPException(status_code=404, detail="通知不存在")
    return updated


def _can_access_notification(principal: Principal, notification: dict) -> bool:
    if "admin" in principal.roles:
        return True
    if notification.get("recipient_subject"):
        if notification["recipient_subject"] != principal.subject:
            return False
    elif notification["recipient_role"] not in principal.roles:
        return False
    return "client" not in principal.roles or principal.counterparty_id == notification["counterparty_id"]
