from __future__ import annotations

import json
from datetime import datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.counterparty_repository import CounterpartyError, CounterpartyRepository
from backend.dependencies import get_counterparty_repository, get_demo_repository, get_enterprise_data_repository, get_enterprise_indicator_observation_repository, get_model_governance_repository
from backend.enterprise_data_governance import flatten_payload
from backend.indicator_observations import apply_effective_observations
from backend.rating_input_mapping import prepare_rating_input
from backend.repository import ConcurrentUpdateError, DemoRepository, EnterpriseDataRepository, EnterpriseIndicatorObservationRepository, ModelGovernanceRepository
from backend.schemas import EnterpriseDataImportCreate, EnterpriseDataResolutionCreate, EnterpriseDataResolutionReview
from backend.security import Principal, enforce_counterparty_scope, require_permissions


router = APIRouter(prefix="/data-governance", tags=["enterprise-data-governance"])


@router.get("/imports")
def list_enterprise_data_imports(
    counterparty_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    repository: EnterpriseDataRepository = Depends(get_enterprise_data_repository),
    counterparty_repository: CounterpartyRepository = Depends(get_counterparty_repository),
    principal: Principal = Depends(require_permissions("data_governance:view")),
) -> list[dict]:
    if counterparty_id:
        enforce_counterparty_scope(principal, counterparty_id)
        _get_counterparty(counterparty_repository, principal, counterparty_id)
    return repository.list_imports(principal.tenant_id, counterparty_id, limit)


@router.post("/imports", status_code=201)
def create_enterprise_data_import(
    request: EnterpriseDataImportCreate,
    repository: EnterpriseDataRepository = Depends(get_enterprise_data_repository),
    counterparty_repository: CounterpartyRepository = Depends(get_counterparty_repository),
    principal: Principal = Depends(require_permissions("data_governance:import")),
) -> dict:
    enforce_counterparty_scope(principal, request.counterparty_id)
    counterparty = _get_counterparty(counterparty_repository, principal, request.counterparty_id)
    encoded = json.dumps(request.payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(encoded) > 512 * 1024:
        raise HTTPException(status_code=422, detail="单批企业数据载荷不能超过 512KB")
    observed_at = datetime.combine(request.as_of_date, time.min, tzinfo=timezone.utc)
    if observed_at > datetime.now(timezone.utc) + timedelta(days=1):
        raise HTTPException(status_code=422, detail="数据截止日期不能晚于当前日期")
    try:
        flat = flatten_payload(request.payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    anchor = flat.get("entity.unified_social_credit_code")
    if not anchor:
        raise HTTPException(status_code=422, detail="每批企业数据必须包含 entity.unified_social_credit_code 作为主体锚点")
    if str(anchor).strip().upper() != str(counterparty.get("credit_code", "")).strip().upper():
        raise HTTPException(status_code=422, detail="导入数据统一社会信用代码与目标客商不一致")
    unknown_evidence = sorted(set(request.field_evidence) - set(flat))
    if unknown_evidence:
        raise HTTPException(status_code=422, detail=f"字段证据指向了不存在的字段：{', '.join(unknown_evidence[:5])}")
    payload = request.model_dump(mode="python")
    payload["as_of_date"] = observed_at
    payload["field_evidence"] = {path: evidence.model_dump(exclude_none=True) for path, evidence in request.field_evidence.items()}
    try:
        result, idempotent = repository.create_import(principal.tenant_id, payload, principal.subject)
    except (ValueError, ConcurrentUpdateError) as exc:
        raise HTTPException(status_code=409 if "任务编号已存在" in str(exc) or isinstance(exc, ConcurrentUpdateError) else 422, detail=str(exc)) from exc
    return {**result, "idempotent": idempotent}


@router.get("/counterparties/{counterparty_id}/profile")
def get_governed_enterprise_profile(
    counterparty_id: str,
    repository: EnterpriseDataRepository = Depends(get_enterprise_data_repository),
    counterparty_repository: CounterpartyRepository = Depends(get_counterparty_repository),
    principal: Principal = Depends(require_permissions("data_governance:view")),
) -> dict:
    enforce_counterparty_scope(principal, counterparty_id)
    _get_counterparty(counterparty_repository, principal, counterparty_id)
    return repository.build_profile(principal.tenant_id, counterparty_id)


@router.get("/counterparties/{counterparty_id}/conflicts")
def list_enterprise_data_conflicts(
    counterparty_id: str,
    repository: EnterpriseDataRepository = Depends(get_enterprise_data_repository),
    counterparty_repository: CounterpartyRepository = Depends(get_counterparty_repository),
    principal: Principal = Depends(require_permissions("data_governance:view")),
) -> list[dict]:
    enforce_counterparty_scope(principal, counterparty_id)
    _get_counterparty(counterparty_repository, principal, counterparty_id)
    return repository.list_conflicts(principal.tenant_id, counterparty_id)


@router.get("/resolutions")
def list_enterprise_data_resolutions(
    counterparty_id: str = Query(min_length=2, max_length=128),
    field_path: str | None = Query(default=None, min_length=1, max_length=512),
    repository: EnterpriseDataRepository = Depends(get_enterprise_data_repository),
    counterparty_repository: CounterpartyRepository = Depends(get_counterparty_repository),
    principal: Principal = Depends(require_permissions("data_governance:view")),
) -> list[dict]:
    enforce_counterparty_scope(principal, counterparty_id)
    _get_counterparty(counterparty_repository, principal, counterparty_id)
    return repository.list_resolutions(principal.tenant_id, counterparty_id, field_path)


@router.post("/resolutions", status_code=201)
def create_enterprise_data_resolution(
    request: EnterpriseDataResolutionCreate,
    repository: EnterpriseDataRepository = Depends(get_enterprise_data_repository),
    counterparty_repository: CounterpartyRepository = Depends(get_counterparty_repository),
    principal: Principal = Depends(require_permissions("data_governance:resolve")),
) -> dict:
    enforce_counterparty_scope(principal, request.counterparty_id)
    _get_counterparty(counterparty_repository, principal, request.counterparty_id)
    try:
        result, idempotent = repository.create_resolution(principal.tenant_id, request.model_dump(), principal.subject, principal.name)
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        status_code = 409 if "已有" in str(exc) or "已经" in str(exc) else 422
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return {**result, "idempotent": idempotent}


@router.post("/resolutions/{resolution_id}/review")
def review_enterprise_data_resolution(
    resolution_id: str,
    request: EnterpriseDataResolutionReview,
    repository: EnterpriseDataRepository = Depends(get_enterprise_data_repository),
    principal: Principal = Depends(require_permissions("data_governance:review")),
) -> dict:
    resolution = repository.get_resolution(principal.tenant_id, resolution_id)
    if not resolution:
        raise HTTPException(status_code=404, detail="字段冲突裁决不存在")
    enforce_counterparty_scope(principal, resolution["counterparty_id"])
    try:
        return repository.review_resolution(
            principal.tenant_id, resolution_id, request.expected_row_version, request.decision, request.comment,
            principal.subject, principal.name,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/counterparties/{counterparty_id}/rating-readiness")
def get_rating_readiness(
    counterparty_id: str,
    template_key: str = Query(default="corporate_credit_v2", min_length=2, max_length=64),
    repository: EnterpriseDataRepository = Depends(get_enterprise_data_repository),
    counterparty_repository: CounterpartyRepository = Depends(get_counterparty_repository),
    demo_repository: DemoRepository = Depends(get_demo_repository),
    model_governance: ModelGovernanceRepository = Depends(get_model_governance_repository),
    indicator_observations: EnterpriseIndicatorObservationRepository = Depends(get_enterprise_indicator_observation_repository),
    principal: Principal = Depends(require_permissions("data_governance:view", "models:view")),
) -> dict:
    enforce_counterparty_scope(principal, counterparty_id)
    counterparty = _get_counterparty(counterparty_repository, principal, counterparty_id)
    config = model_governance.get_config(demo_repository, template_key)
    if not config:
        raise HTTPException(status_code=404, detail="模型模板不存在")
    rating_input, readiness = prepare_rating_input(counterparty, repository.build_profile(principal.tenant_id, counterparty_id), template_key, config)
    _, readiness = apply_effective_observations(
        rating_input,
        readiness,
        indicator_observations.effective(principal.tenant_id, counterparty_id),
    )
    return readiness


@router.get("/counterparties/{counterparty_id}/lineage")
def get_enterprise_field_lineage(
    counterparty_id: str,
    field_path: str = Query(min_length=1, max_length=512),
    repository: EnterpriseDataRepository = Depends(get_enterprise_data_repository),
    counterparty_repository: CounterpartyRepository = Depends(get_counterparty_repository),
    principal: Principal = Depends(require_permissions("data_governance:view")),
) -> dict:
    enforce_counterparty_scope(principal, counterparty_id)
    _get_counterparty(counterparty_repository, principal, counterparty_id)
    return repository.lineage(principal.tenant_id, counterparty_id, field_path)


def _get_counterparty(
    repository: CounterpartyRepository,
    principal: Principal,
    counterparty_id: str,
) -> dict:
    try:
        return repository.get(principal.tenant_id, counterparty_id, include_archived=True)
    except CounterpartyError as exc:
        raise HTTPException(status_code=404, detail="客商不存在") from exc
