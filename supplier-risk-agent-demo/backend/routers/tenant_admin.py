"""Explicit platform-only tenant administration control plane."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.dependencies import get_tenant_admin_repository
from backend.security import Principal, require_permissions
from backend.tenant_admin_repository import TenantAdminError, TenantAdminRepository
from backend.tenant_schemas import (
    ApiClientCreate,
    ApiClientUpdate,
    ApiClientView,
    TenantCreate,
    TenantMembershipCreate,
    TenantMembershipUpdate,
    TenantMembershipView,
    TenantPage,
    TenantStatusUpdate,
    TenantView,
)


router = APIRouter(prefix="/tenant-admin/tenants", tags=["tenant-administration"])


@router.get("", response_model=TenantPage)
def list_tenants(
    status: Literal["active", "suspended", "disabled"] | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    repository: TenantAdminRepository = Depends(get_tenant_admin_repository),
    _: Principal = Depends(require_permissions("tenant_admin:view")),
) -> dict:
    return repository.list_tenants(limit=limit, offset=offset, status=status)


@router.post("", status_code=201, response_model=TenantView)
def create_tenant(
    request: TenantCreate,
    repository: TenantAdminRepository = Depends(get_tenant_admin_repository),
    principal: Principal = Depends(require_permissions("tenant_admin:manage")),
) -> dict:
    try:
        return repository.create_tenant(request.model_dump(), principal)
    except TenantAdminError as exc:
        _raise(exc)


@router.get("/{tenant_id}", response_model=TenantView)
def get_tenant(
    tenant_id: str,
    repository: TenantAdminRepository = Depends(get_tenant_admin_repository),
    _: Principal = Depends(require_permissions("tenant_admin:view")),
) -> dict:
    try:
        return repository.get_tenant(tenant_id)
    except TenantAdminError as exc:
        _raise(exc)


@router.patch("/{tenant_id}/status", response_model=TenantView)
def update_tenant_status(
    tenant_id: str,
    request: TenantStatusUpdate,
    repository: TenantAdminRepository = Depends(get_tenant_admin_repository),
    principal: Principal = Depends(require_permissions("tenant_admin:manage")),
) -> dict:
    try:
        return repository.update_tenant_status(tenant_id, request.model_dump(), principal)
    except TenantAdminError as exc:
        _raise(exc)


@router.get("/{tenant_id}/members", response_model=list[TenantMembershipView])
def list_tenant_members(
    tenant_id: str,
    repository: TenantAdminRepository = Depends(get_tenant_admin_repository),
    _: Principal = Depends(require_permissions("tenant_admin:view")),
) -> list[dict]:
    try:
        return repository.list_memberships(tenant_id)
    except TenantAdminError as exc:
        _raise(exc)


@router.post("/{tenant_id}/members", status_code=201, response_model=TenantMembershipView)
def create_tenant_member(
    tenant_id: str,
    request: TenantMembershipCreate,
    repository: TenantAdminRepository = Depends(get_tenant_admin_repository),
    principal: Principal = Depends(require_permissions("tenant_admin:manage")),
) -> dict:
    try:
        return repository.create_membership(tenant_id, request.model_dump(), principal)
    except TenantAdminError as exc:
        _raise(exc)


@router.patch("/{tenant_id}/members/{subject}", response_model=TenantMembershipView)
def update_tenant_member(
    tenant_id: str,
    subject: str,
    request: TenantMembershipUpdate,
    repository: TenantAdminRepository = Depends(get_tenant_admin_repository),
    principal: Principal = Depends(require_permissions("tenant_admin:manage")),
) -> dict:
    try:
        return repository.update_membership(tenant_id, subject, request.model_dump(), principal)
    except TenantAdminError as exc:
        _raise(exc)


@router.get("/{tenant_id}/clients", response_model=list[ApiClientView])
def list_api_clients(
    tenant_id: str,
    repository: TenantAdminRepository = Depends(get_tenant_admin_repository),
    _: Principal = Depends(require_permissions("tenant_admin:view")),
) -> list[dict]:
    try:
        return repository.list_clients(tenant_id)
    except TenantAdminError as exc:
        _raise(exc)


@router.post("/{tenant_id}/clients", status_code=201, response_model=ApiClientView)
def create_api_client(
    tenant_id: str,
    request: ApiClientCreate,
    repository: TenantAdminRepository = Depends(get_tenant_admin_repository),
    principal: Principal = Depends(require_permissions("tenant_admin:manage")),
) -> dict:
    try:
        return repository.create_client(tenant_id, request.model_dump(), principal)
    except TenantAdminError as exc:
        _raise(exc)


@router.patch("/{tenant_id}/clients/{client_id}", response_model=ApiClientView)
def update_api_client(
    tenant_id: str,
    client_id: str,
    request: ApiClientUpdate,
    repository: TenantAdminRepository = Depends(get_tenant_admin_repository),
    principal: Principal = Depends(require_permissions("tenant_admin:manage")),
) -> dict:
    try:
        return repository.update_client(tenant_id, client_id, request.model_dump(), principal)
    except TenantAdminError as exc:
        _raise(exc)


def _raise(error: TenantAdminError) -> None:
    raise HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": error.message},
    ) from error
