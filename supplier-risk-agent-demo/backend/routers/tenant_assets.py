"""Tenant asset catalog and governed override endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.dependencies import get_tenant_asset_repository
from backend.security import Principal, require_permissions
from backend.tenant_asset_repository import TenantAssetError, TenantAssetRepository
from backend.tenant_asset_schemas import (
    AssetType,
    TenantAssetBindingCreate,
    TenantAssetBindingUpdate,
    TenantAssetBindingView,
    TenantAssetOverrideCreate,
    TenantAssetOverrideUpdate,
    TenantAssetOverrideView,
    TenantAssetOverrideReview,
    TenantAssetResolution,
    TenantAssetVersionAction,
)


router = APIRouter(prefix="/tenant-assets", tags=["tenant-assets"])


@router.get("")
def list_tenant_assets(
    asset_type: AssetType | None = Query(default=None),
    repository: TenantAssetRepository = Depends(get_tenant_asset_repository),
    principal: Principal = Depends(require_permissions("tenant_assets:view")),
) -> dict:
    try:
        return repository.list_catalog(principal, asset_type)
    except TenantAssetError as exc:
        _raise(exc)


@router.get("/{asset_type}/{asset_code}/resolve", response_model=TenantAssetResolution)
def resolve_tenant_asset(
    asset_type: AssetType,
    asset_code: str,
    repository: TenantAssetRepository = Depends(get_tenant_asset_repository),
    principal: Principal = Depends(require_permissions("tenant_assets:view")),
) -> dict:
    try:
        return repository.resolve(principal.tenant_id, asset_type, asset_code)
    except TenantAssetError as exc:
        _raise(exc)


@router.post("/bindings", status_code=status.HTTP_201_CREATED, response_model=TenantAssetBindingView)
def create_tenant_asset_binding(
    request: TenantAssetBindingCreate,
    repository: TenantAssetRepository = Depends(get_tenant_asset_repository),
    principal: Principal = Depends(require_permissions("tenant_assets:manage")),
) -> dict:
    try:
        return repository.create_binding(request.model_dump(), principal)
    except TenantAssetError as exc:
        _raise(exc)


@router.patch("/bindings/{binding_id}", response_model=TenantAssetBindingView)
def update_tenant_asset_binding(
    binding_id: str,
    request: TenantAssetBindingUpdate,
    repository: TenantAssetRepository = Depends(get_tenant_asset_repository),
    principal: Principal = Depends(require_permissions("tenant_assets:manage")),
) -> dict:
    try:
        return repository.update_binding(binding_id, request.model_dump(), principal)
    except TenantAssetError as exc:
        _raise(exc)


@router.post("/overrides", status_code=status.HTTP_201_CREATED, response_model=TenantAssetOverrideView)
def create_tenant_asset_override(
    request: TenantAssetOverrideCreate,
    repository: TenantAssetRepository = Depends(get_tenant_asset_repository),
    principal: Principal = Depends(require_permissions("tenant_assets:manage")),
) -> dict:
    try:
        return repository.create_override(request.model_dump(), principal)
    except TenantAssetError as exc:
        _raise(exc)


@router.put("/overrides/{override_id}", response_model=TenantAssetOverrideView)
def update_tenant_asset_override(
    override_id: str,
    request: TenantAssetOverrideUpdate,
    repository: TenantAssetRepository = Depends(get_tenant_asset_repository),
    principal: Principal = Depends(require_permissions("tenant_assets:manage")),
) -> dict:
    try:
        return repository.update_override(override_id, request.model_dump(), principal)
    except TenantAssetError as exc:
        _raise(exc)


@router.post("/overrides/{override_id}/submit", response_model=TenantAssetOverrideView)
def submit_tenant_asset_override(
    override_id: str,
    request: TenantAssetVersionAction,
    repository: TenantAssetRepository = Depends(get_tenant_asset_repository),
    principal: Principal = Depends(require_permissions("tenant_assets:manage")),
) -> dict:
    try:
        return repository.submit_override(override_id, request.model_dump(), principal)
    except TenantAssetError as exc:
        _raise(exc)


@router.post("/overrides/{override_id}/review", response_model=TenantAssetOverrideView)
def review_tenant_asset_override(
    override_id: str,
    request: TenantAssetOverrideReview,
    repository: TenantAssetRepository = Depends(get_tenant_asset_repository),
    principal: Principal = Depends(require_permissions("tenant_assets:review")),
) -> dict:
    try:
        return repository.review_override(override_id, request.model_dump(), principal)
    except TenantAssetError as exc:
        _raise(exc)


def _raise(error: TenantAssetError) -> None:
    raise HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": error.message, "details": error.details},
    ) from error
