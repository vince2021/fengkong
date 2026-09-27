from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from backend.counterparty_import_repository import CounterpartyImportError, CounterpartyImportRepository
from backend.counterparty_mapping_repository import CounterpartyImportMappingRepository, CounterpartyMappingError
from backend.counterparty_repository import CounterpartyError, CounterpartyRepository
from backend.counterparty_schemas import CounterpartyArchive, CounterpartyCreate, CounterpartyHistoryEvent, CounterpartyImportCommit, CounterpartyImportCorrectionDraft, CounterpartyImportMappingTemplateArchive, CounterpartyImportMappingTemplateCreate, CounterpartyImportMappingTemplateUpdate, CounterpartyImportMappingTemplateView, CounterpartyImportPage, CounterpartyImportPrecheck, CounterpartyImportView, CounterpartyPage, CounterpartyUpdate, CounterpartyView
from backend.dependencies import get_counterparty_import_repository, get_counterparty_mapping_repository, get_counterparty_repository, get_demo_repository
from backend.repository import DemoRepository
from backend.security import Principal, require_permissions


router = APIRouter(prefix="/counterparties", tags=["counterparties"])


@router.get("", response_model=list[CounterpartyView])
def list_counterparties(
    repository: CounterpartyRepository = Depends(get_counterparty_repository),
    principal: Principal = Depends(require_permissions("counterparties:view")),
) -> list[dict]:
    return repository.list_legacy(principal.tenant_id, principal.counterparty_id if "client" in principal.roles else None)


@router.get("/page", response_model=CounterpartyPage)
def page_counterparties(
    q: str | None = Query(default=None, min_length=1, max_length=255),
    counterparty_type: Literal["supplier", "customer"] | None = None,
    status: Literal["active", "archived"] | None = "active",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    repository: CounterpartyRepository = Depends(get_counterparty_repository),
    principal: Principal = Depends(require_permissions("counterparties:view")),
) -> dict:
    return repository.page(
        principal.tenant_id, q=q, counterparty_type=counterparty_type, status=status, limit=limit, offset=offset,
        counterparty_id=principal.counterparty_id if "client" in principal.roles else None,
    )


@router.post("", status_code=201, response_model=CounterpartyView)
def create_counterparty(
    request: CounterpartyCreate,
    repository: CounterpartyRepository = Depends(get_counterparty_repository),
    principal: Principal = Depends(require_permissions("counterparties:manage")),
) -> dict:
    try:
        return repository.create(request.model_dump(), principal)
    except CounterpartyError as exc:
        _raise(exc)


@router.get("/imports", response_model=CounterpartyImportPage)
def list_counterparty_imports(
    status: Literal["prechecked", "blocked", "committed"] | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    repository: CounterpartyImportRepository = Depends(get_counterparty_import_repository),
    principal: Principal = Depends(require_permissions("counterparties:imports:view")),
) -> dict:
    return repository.list(principal.tenant_id, status=status, limit=limit, offset=offset)


@router.get("/import-mapping-templates", response_model=list[CounterpartyImportMappingTemplateView])
def list_counterparty_import_mapping_templates(
    status: Literal["active", "archived"] | None = "active",
    repository: CounterpartyImportMappingRepository = Depends(get_counterparty_mapping_repository),
    principal: Principal = Depends(require_permissions("counterparties:imports:view")),
) -> list[dict]:
    return repository.list(principal.tenant_id, status=status)


@router.post("/import-mapping-templates", status_code=201, response_model=CounterpartyImportMappingTemplateView)
def create_counterparty_import_mapping_template(
    request: CounterpartyImportMappingTemplateCreate,
    repository: CounterpartyImportMappingRepository = Depends(get_counterparty_mapping_repository),
    principal: Principal = Depends(require_permissions("counterparties:manage")),
) -> dict:
    try:
        return repository.create(request.model_dump(), principal)
    except CounterpartyMappingError as exc:
        _raise_mapping(exc)


@router.patch("/import-mapping-templates/{template_id}", response_model=CounterpartyImportMappingTemplateView)
def update_counterparty_import_mapping_template(
    template_id: str,
    request: CounterpartyImportMappingTemplateUpdate,
    repository: CounterpartyImportMappingRepository = Depends(get_counterparty_mapping_repository),
    principal: Principal = Depends(require_permissions("counterparties:manage")),
) -> dict:
    try:
        return repository.update(principal.tenant_id, template_id, request.model_dump(exclude_unset=True), principal)
    except CounterpartyMappingError as exc:
        _raise_mapping(exc)


@router.post("/import-mapping-templates/{template_id}/archive", response_model=CounterpartyImportMappingTemplateView)
def archive_counterparty_import_mapping_template(
    template_id: str,
    request: CounterpartyImportMappingTemplateArchive,
    repository: CounterpartyImportMappingRepository = Depends(get_counterparty_mapping_repository),
    principal: Principal = Depends(require_permissions("counterparties:manage")),
) -> dict:
    try:
        return repository.archive(principal.tenant_id, template_id, request.model_dump(), principal)
    except CounterpartyMappingError as exc:
        _raise_mapping(exc)


@router.post("/imports/precheck", status_code=201, response_model=CounterpartyImportView)
def precheck_counterparty_import(
    request: CounterpartyImportPrecheck,
    repository: CounterpartyImportRepository = Depends(get_counterparty_import_repository),
    principal: Principal = Depends(require_permissions("counterparties:manage")),
) -> dict:
    try:
        return repository.precheck(request.model_dump(), principal)
    except CounterpartyImportError as exc:
        _raise_import(exc)


@router.get("/imports/{batch_id}", response_model=CounterpartyImportView)
def get_counterparty_import(
    batch_id: str,
    repository: CounterpartyImportRepository = Depends(get_counterparty_import_repository),
    principal: Principal = Depends(require_permissions("counterparties:imports:view")),
) -> dict:
    try:
        return repository.get(principal.tenant_id, batch_id)
    except CounterpartyImportError as exc:
        _raise_import(exc)


@router.get("/imports/{batch_id}/correction-draft", response_model=CounterpartyImportCorrectionDraft)
def get_counterparty_import_correction_draft(
    batch_id: str,
    repository: CounterpartyImportRepository = Depends(get_counterparty_import_repository),
    principal: Principal = Depends(require_permissions("counterparties:manage")),
) -> dict:
    try:
        return repository.correction_draft(principal.tenant_id, batch_id)
    except CounterpartyImportError as exc:
        _raise_import(exc)


@router.get("/imports/{batch_id}/receipt.csv")
def download_counterparty_import_receipt(
    batch_id: str,
    repository: CounterpartyImportRepository = Depends(get_counterparty_import_repository),
    principal: Principal = Depends(require_permissions("counterparties:imports:view")),
) -> Response:
    try:
        filename, content = repository.receipt_csv(principal.tenant_id, batch_id)
    except CounterpartyImportError as exc:
        _raise_import(exc)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/imports/{batch_id}/commit", response_model=CounterpartyImportView)
def commit_counterparty_import(
    batch_id: str,
    request: CounterpartyImportCommit,
    repository: CounterpartyImportRepository = Depends(get_counterparty_import_repository),
    principal: Principal = Depends(require_permissions("counterparties:manage")),
) -> dict:
    try:
        return repository.commit(batch_id, request.model_dump(), principal)
    except CounterpartyImportError as exc:
        _raise_import(exc)


@router.get("/{counterparty_id}", response_model=CounterpartyView)
def get_counterparty(
    counterparty_id: str,
    include_archived: bool = False,
    repository: CounterpartyRepository = Depends(get_counterparty_repository),
    principal: Principal = Depends(require_permissions("counterparties:view")),
) -> dict:
    _enforce_client_scope(principal, counterparty_id)
    try:
        return repository.get(
            principal.tenant_id,
            counterparty_id,
            include_archived=include_archived and "client" not in principal.roles,
        )
    except CounterpartyError as exc:
        _raise(exc)


@router.get("/{counterparty_id}/history", response_model=list[CounterpartyHistoryEvent])
def get_counterparty_history(
    counterparty_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    repository: CounterpartyRepository = Depends(get_counterparty_repository),
    principal: Principal = Depends(require_permissions("counterparties:view")),
) -> list[dict]:
    _enforce_client_scope(principal, counterparty_id)
    try:
        return repository.history(principal.tenant_id, counterparty_id, limit=limit)
    except CounterpartyError as exc:
        _raise(exc)


@router.patch("/{counterparty_id}", response_model=CounterpartyView)
def update_counterparty(
    counterparty_id: str,
    request: CounterpartyUpdate,
    repository: CounterpartyRepository = Depends(get_counterparty_repository),
    principal: Principal = Depends(require_permissions("counterparties:manage")),
) -> dict:
    try:
        return repository.update(principal.tenant_id, counterparty_id, request.model_dump(exclude_unset=True), principal)
    except CounterpartyError as exc:
        _raise(exc)


@router.post("/{counterparty_id}/archive", response_model=CounterpartyView)
def archive_counterparty(
    counterparty_id: str,
    request: CounterpartyArchive,
    repository: CounterpartyRepository = Depends(get_counterparty_repository),
    principal: Principal = Depends(require_permissions("counterparties:manage")),
) -> dict:
    try:
        return repository.archive(principal.tenant_id, counterparty_id, request.model_dump(), principal)
    except CounterpartyError as exc:
        _raise(exc)


@router.get("/{counterparty_id}/raw-profile")
def get_counterparty_raw_profile(
    counterparty_id: str,
    repository: CounterpartyRepository = Depends(get_counterparty_repository),
    demo_repository: DemoRepository = Depends(get_demo_repository),
    principal: Principal = Depends(require_permissions("counterparties:view")),
) -> dict:
    _enforce_client_scope(principal, counterparty_id)
    try:
        counterparty = repository.get(principal.tenant_id, counterparty_id)
    except CounterpartyError as exc:
        _raise(exc)
    profile = demo_repository.get_raw_profile(counterparty_id)
    if not profile:
        raise HTTPException(status_code=404, detail="当前客商暂无材料提炼原始数据")
    return {
        **profile,
        "counterparty_id": counterparty_id,
        "recommended_model": counterparty.get("data_quality", {}).get("recommended_model", "general"),
        "missing_critical_fields": counterparty.get("data_quality", {}).get("missing_critical_fields", []),
    }


def _enforce_client_scope(principal: Principal, counterparty_id: str) -> None:
    if "client" in principal.roles and principal.counterparty_id != counterparty_id:
        raise HTTPException(status_code=404, detail="客商不存在")


def _raise(error: CounterpartyError) -> None:
    raise HTTPException(status_code=error.status_code, detail={"code": error.code, "message": error.message}) from error


def _raise_import(error: CounterpartyImportError) -> None:
    raise HTTPException(status_code=error.status_code, detail={"code": error.code, "message": error.message}) from error


def _raise_mapping(error: CounterpartyMappingError) -> None:
    raise HTTPException(status_code=error.status_code, detail={"code": error.code, "message": error.message}) from error
