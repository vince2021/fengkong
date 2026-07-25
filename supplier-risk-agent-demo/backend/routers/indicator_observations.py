from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.dependencies import get_demo_repository, get_document_repository, get_enterprise_indicator_observation_repository
from backend.indicator_observations import observed_datetime, validate_indicator_observation
from backend.repository import ConcurrentUpdateError, DemoRepository, DocumentRepository, EnterpriseIndicatorObservationRepository
from backend.schemas import EnterpriseIndicatorObservationCreate, EnterpriseIndicatorObservationReview
from backend.security import Principal, enforce_counterparty_scope, require_permissions


router = APIRouter(prefix="/indicator-observations", tags=["enterprise-indicator-observations"])


@router.get("")
def list_indicator_observations(
    counterparty_id: str,
    indicator_id: str | None = None,
    repository: EnterpriseIndicatorObservationRepository = Depends(get_enterprise_indicator_observation_repository),
    principal: Principal = Depends(require_permissions("indicator_data:view")),
) -> list[dict]:
    enforce_counterparty_scope(principal, counterparty_id)
    return repository.list(counterparty_id, indicator_id)


@router.post("", status_code=201)
def create_indicator_observation(
    request: EnterpriseIndicatorObservationCreate,
    repository: EnterpriseIndicatorObservationRepository = Depends(get_enterprise_indicator_observation_repository),
    demo_repository: DemoRepository = Depends(get_demo_repository),
    document_repository: DocumentRepository = Depends(get_document_repository),
    principal: Principal = Depends(require_permissions("indicator_data:manage")),
) -> dict:
    if not demo_repository.get_counterparty(request.counterparty_id):
        raise HTTPException(status_code=404, detail="客商不存在")
    enforce_counterparty_scope(principal, request.counterparty_id)
    try:
        indicator, values = validate_indicator_observation(request.indicator_id, request.values)
        observed_at = observed_datetime(request.as_of_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if request.evidence_document_id:
        document = document_repository.get(request.evidence_document_id)
        if not document or document["counterparty_id"] != request.counterparty_id:
            raise HTTPException(status_code=422, detail="证据资料不存在或不属于当前企业")
        if document.get("review_status") != "verified":
            raise HTTPException(status_code=422, detail="只有已逐项核验的资料可以绑定为指标证据")
    try:
        return repository.create({
            **request.model_dump(exclude={"values", "as_of_date"}),
            "indicator_name": indicator["name"],
            "values": values,
            "observed_at": observed_at,
        }, principal.subject, principal.name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{observation_id}/review")
def review_indicator_observation(
    observation_id: str,
    request: EnterpriseIndicatorObservationReview,
    repository: EnterpriseIndicatorObservationRepository = Depends(get_enterprise_indicator_observation_repository),
    document_repository: DocumentRepository = Depends(get_document_repository),
    principal: Principal = Depends(require_permissions("indicator_data:review")),
) -> dict:
    observation = repository.get(observation_id)
    if not observation:
        raise HTTPException(status_code=404, detail="指标数据记录不存在")
    enforce_counterparty_scope(principal, observation["counterparty_id"])
    if request.decision == "verify" and observation.get("evidence_document_id"):
        document = document_repository.get(observation["evidence_document_id"])
        if not document or document.get("review_status") != "verified":
            raise HTTPException(status_code=409, detail="关联证据资料已失效或尚未核验")
    try:
        return repository.review(observation_id, request.expected_row_version, request.decision, request.comment, principal.subject, principal.name)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
