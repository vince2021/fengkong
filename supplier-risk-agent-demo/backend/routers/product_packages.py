"""Platform product package and tenant entitlement administration APIs."""
from __future__ import annotations

import csv
from datetime import date, datetime, timezone
from io import StringIO
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from backend.dependencies import get_product_package_repository, get_tenant_usage_repository
from backend.product_package_repository import ProductPackageError, ProductPackageRepository
from backend.product_package_schemas import (
    EntitlementImpactPreview,
    EntitlementLifecycleIncidentAction,
    EntitlementLifecycleRetry,
    EntitlementLifecycleRunView,
    EntitlementLifecycleScanRequest,
    EntitlementRequest,
    EntitlementStatusAction,
    EntitlementView,
    GovernanceReview,
    ProductPackageCreate,
    ProductPackageView,
    VersionAction,
    TenantUsageDailyView,
    TenantUsageStatementView,
    UsageRefreshRequest,
    UsageStatementRequest,
)
from backend.security import Principal, require_permissions
from backend.tenant_usage_repository import TenantUsageRepository


router = APIRouter(prefix="/tenant-admin", tags=["product-packages"])


@router.get("/product-packages", response_model=list[ProductPackageView])
def list_product_packages(
    status: Literal["draft", "pending_review", "published", "rejected", "retired"] | None = None,
    repository: ProductPackageRepository = Depends(get_product_package_repository),
    _: Principal = Depends(require_permissions("tenant_admin:view")),
) -> list[dict]:
    return repository.list_packages(status)


@router.post("/product-packages", status_code=201, response_model=ProductPackageView)
def create_product_package(
    request: ProductPackageCreate,
    repository: ProductPackageRepository = Depends(get_product_package_repository),
    principal: Principal = Depends(require_permissions("tenant_admin:manage")),
) -> dict:
    return _run(repository.create_package, request.model_dump(), principal)


@router.post("/product-packages/{package_id}/submit", response_model=ProductPackageView)
def submit_product_package(
    package_id: str, request: VersionAction,
    repository: ProductPackageRepository = Depends(get_product_package_repository),
    principal: Principal = Depends(require_permissions("tenant_admin:manage")),
) -> dict:
    return _run(repository.submit_package, package_id, request.model_dump(), principal)


@router.post("/product-packages/{package_id}/review", response_model=ProductPackageView)
def review_product_package(
    package_id: str, request: GovernanceReview,
    repository: ProductPackageRepository = Depends(get_product_package_repository),
    principal: Principal = Depends(require_permissions("tenant_admin:manage")),
) -> dict:
    return _run(repository.review_package, package_id, request.model_dump(), principal)


@router.get("/entitlements", response_model=list[EntitlementView])
def list_entitlements(
    tenant_id: str | None = None,
    status: Literal["draft", "pending_review", "scheduled", "active", "suspended", "expired", "terminated"] | None = None,
    repository: ProductPackageRepository = Depends(get_product_package_repository),
    _: Principal = Depends(require_permissions("tenant_admin:view")),
) -> list[dict]:
    return repository.list_entitlements(tenant_id, status)


@router.get("/entitlement-lifecycle/status")
def entitlement_lifecycle_status(
    repository: ProductPackageRepository = Depends(get_product_package_repository),
    _: Principal = Depends(require_permissions("tenant_admin:view")),
) -> dict:
    return repository.entitlement_lifecycle_status()


@router.post("/entitlement-lifecycle/scan")
def scan_entitlement_lifecycle(
    request: EntitlementLifecycleScanRequest,
    repository: ProductPackageRepository = Depends(get_product_package_repository),
    principal: Principal = Depends(require_permissions("tenant_admin:manage")),
) -> dict:
    return _run(
        repository.run_entitlement_lifecycle,
        principal,
        None,
        request.run_key,
        "manual",
    )


@router.get("/entitlement-runs", response_model=list[EntitlementLifecycleRunView])
def list_entitlement_lifecycle_runs(
    limit: int = Query(default=100, ge=1, le=500),
    repository: ProductPackageRepository = Depends(get_product_package_repository),
    _: Principal = Depends(require_permissions("tenant_admin:view")),
) -> list[dict]:
    return repository.list_entitlement_lifecycle_runs(limit)


@router.post("/entitlement-runs/{run_id}/acknowledge", response_model=EntitlementLifecycleRunView)
def acknowledge_entitlement_lifecycle_run(
    run_id: str,
    request: EntitlementLifecycleIncidentAction,
    repository: ProductPackageRepository = Depends(get_product_package_repository),
    principal: Principal = Depends(require_permissions("tenant_admin:manage")),
) -> dict:
    return _run(repository.acknowledge_entitlement_lifecycle_run, run_id, request.model_dump(), principal)


@router.post("/entitlement-runs/{run_id}/retry")
def retry_entitlement_lifecycle_run(
    run_id: str,
    request: EntitlementLifecycleRetry,
    repository: ProductPackageRepository = Depends(get_product_package_repository),
    principal: Principal = Depends(require_permissions("tenant_admin:manage")),
) -> dict:
    return _run(repository.retry_entitlement_lifecycle_run, run_id, request.model_dump(), principal)


@router.post("/entitlements/preview", response_model=EntitlementImpactPreview)
def preview_entitlement(
    request: EntitlementRequest,
    repository: ProductPackageRepository = Depends(get_product_package_repository),
    _: Principal = Depends(require_permissions("tenant_admin:manage")),
) -> dict:
    return _run(repository.preview_entitlement, request.model_dump())


@router.post("/entitlements", status_code=201, response_model=EntitlementView)
def create_entitlement(
    request: EntitlementRequest,
    repository: ProductPackageRepository = Depends(get_product_package_repository),
    principal: Principal = Depends(require_permissions("tenant_admin:manage")),
) -> dict:
    return _run(repository.create_entitlement, request.model_dump(), principal)


@router.post("/entitlements/{entitlement_id}/submit", response_model=EntitlementView)
def submit_entitlement(
    entitlement_id: str, request: VersionAction,
    repository: ProductPackageRepository = Depends(get_product_package_repository),
    principal: Principal = Depends(require_permissions("tenant_admin:manage")),
) -> dict:
    return _run(repository.submit_entitlement, entitlement_id, request.model_dump(), principal)


@router.post("/entitlements/{entitlement_id}/review", response_model=EntitlementView)
def review_entitlement(
    entitlement_id: str, request: GovernanceReview,
    repository: ProductPackageRepository = Depends(get_product_package_repository),
    principal: Principal = Depends(require_permissions("tenant_admin:manage")),
) -> dict:
    return _run(repository.review_entitlement, entitlement_id, request.model_dump(), principal)


@router.post("/entitlements/{entitlement_id}/status", response_model=EntitlementView)
def change_entitlement_status(
    entitlement_id: str, request: EntitlementStatusAction,
    repository: ProductPackageRepository = Depends(get_product_package_repository),
    principal: Principal = Depends(require_permissions("tenant_admin:manage")),
) -> dict:
    return _run(repository.change_entitlement_status, entitlement_id, request.model_dump(), principal)


@router.get("/usage/summary")
def tenant_usage_summary(
    tenant_id: str = Query(..., min_length=2, max_length=128),
    billing_month: date = Query(...),
    repository: TenantUsageRepository = Depends(get_tenant_usage_repository),
    _: Principal = Depends(require_permissions("tenant_admin:view")),
) -> dict:
    return _run(repository.summary, tenant_id, billing_month)


@router.post("/usage/refresh", response_model=TenantUsageDailyView)
def refresh_tenant_usage(
    request: UsageRefreshRequest,
    repository: TenantUsageRepository = Depends(get_tenant_usage_repository),
    principal: Principal = Depends(require_permissions("tenant_admin:manage")),
) -> dict:
    return _run(repository.refresh_day, request.tenant_id, request.usage_date or datetime.now(timezone.utc).date(), principal)


@router.get("/usage/statements", response_model=list[TenantUsageStatementView])
def list_tenant_usage_statements(
    tenant_id: str | None = Query(default=None, min_length=2, max_length=128),
    billing_month: date | None = Query(default=None),
    repository: TenantUsageRepository = Depends(get_tenant_usage_repository),
    _: Principal = Depends(require_permissions("tenant_admin:view")),
) -> list[dict]:
    return _run(repository.list_statements, tenant_id, billing_month)


@router.post("/usage/statements", status_code=201, response_model=TenantUsageStatementView)
def create_tenant_usage_statement(
    request: UsageStatementRequest,
    repository: TenantUsageRepository = Depends(get_tenant_usage_repository),
    principal: Principal = Depends(require_permissions("tenant_admin:manage")),
) -> dict:
    return _run(repository.create_statement, request.tenant_id, request.billing_month, principal)


@router.get("/usage/statements/{statement_id}/export.csv")
def export_tenant_usage_statement(
    statement_id: str,
    repository: TenantUsageRepository = Depends(get_tenant_usage_repository),
    _: Principal = Depends(require_permissions("tenant_admin:view")),
) -> Response:
    statement, rows = _run(repository.export_rows, statement_id)
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=["billing_month", "statement_version", "statement_hash", "usage_date", "sync_decision_requests", "async_job_items", "portfolio_candidates", "replay_samples", "document_storage_bytes", "evidence_hash"])
    writer.writeheader()
    for row in rows:
        writer.writerow({"billing_month": statement["billing_month"], "statement_version": statement["statement_version"], "statement_hash": statement["statement_hash"], **row})
    filename = f"tenant-usage-{statement['tenant_id']}-{statement['billing_month']}-v{statement['statement_version']}.csv"
    return Response(content="\ufeff" + output.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _run(operation, *args):
    try:
        return operation(*args)
    except ProductPackageError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message, "details": exc.details},
        ) from exc
