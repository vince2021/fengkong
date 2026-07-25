from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.dependencies import get_credit_facility_repository
from backend.repository import ConcurrentUpdateError, CreditFacilityRepository
from backend.schemas import AlertDispositionRequest, CreditUsageRequest, FacilityControlRequest, PostCreditReviewRequest, RiskEventCreate
from backend.security import Principal, enforce_counterparty_scope, require_permissions


router = APIRouter(prefix="/credit-facilities", tags=["post-credit-management"])


@router.get("")
def list_facilities(
    repository: CreditFacilityRepository = Depends(get_credit_facility_repository),
    principal: Principal = Depends(require_permissions("facilities:view")),
) -> list[dict]:
    return repository.list(principal.counterparty_id if "client" in principal.roles else None)


@router.get("/summary")
def facility_summary(
    repository: CreditFacilityRepository = Depends(get_credit_facility_repository),
    principal: Principal = Depends(require_permissions("facilities:view")),
) -> dict:
    return repository.summary(principal.counterparty_id if "client" in principal.roles else None)


@router.get("/alerts")
def list_facility_alerts(
    repository: CreditFacilityRepository = Depends(get_credit_facility_repository),
    principal: Principal = Depends(require_permissions("facilities:view")),
) -> list[dict]:
    return repository.list_alerts(principal.counterparty_id if "client" in principal.roles else None)


@router.get("/risk-events")
def list_risk_events(
    repository: CreditFacilityRepository = Depends(get_credit_facility_repository),
    principal: Principal = Depends(require_permissions("facilities:view")),
) -> list[dict]:
    return repository.list_risk_events(counterparty_id=principal.counterparty_id if "client" in principal.roles else None)


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge_alert(
    alert_id: str,
    repository: CreditFacilityRepository = Depends(get_credit_facility_repository),
    principal: Principal = Depends(require_permissions("facility_alerts:act")),
) -> dict:
    alert = repository.acknowledge_alert(alert_id, principal.name)
    if not alert:
        raise HTTPException(status_code=404, detail="贷后预警不存在")
    return alert


@router.post("/alerts/{alert_id}/dispose")
def dispose_alert(
    alert_id: str,
    request: AlertDispositionRequest,
    repository: CreditFacilityRepository = Depends(get_credit_facility_repository),
    principal: Principal = Depends(require_permissions("facility_alerts:act")),
) -> dict:
    if request.action != "monitor" and not principal.can("facilities:control"):
        raise HTTPException(status_code=403, detail="当前角色只能持续监控预警，无权执行授信控制")
    try:
        return repository.dispose_alert(alert_id, request.expected_alert_version, request.expected_facility_version, request.action, request.target_limit, principal.name, request.conclusion)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/scan")
def scan_facilities(
    repository: CreditFacilityRepository = Depends(get_credit_facility_repository),
    principal: Principal = Depends(require_permissions("facilities:scan")),
) -> dict:
    return repository.scan(principal.name)


@router.get("/{facility_id}")
def get_facility(
    facility_id: str,
    repository: CreditFacilityRepository = Depends(get_credit_facility_repository),
    principal: Principal = Depends(require_permissions("facilities:view")),
) -> dict:
    facility = _scoped_facility(repository, facility_id, principal)
    return {**facility, "transactions": repository.list_transactions(facility_id)}


@router.post("/{facility_id}/transactions")
def create_credit_transaction(
    facility_id: str,
    request: CreditUsageRequest,
    repository: CreditFacilityRepository = Depends(get_credit_facility_repository),
    principal: Principal = Depends(require_permissions("facilities:transact")),
) -> dict:
    _scoped_facility(repository, facility_id, principal)
    try:
        return repository.transact(facility_id, request.transaction_ref, request.transaction_type, request.amount, request.expected_row_version, principal.name, request.reason)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{facility_id}/risk-events", status_code=201)
def create_risk_event(
    facility_id: str,
    request: RiskEventCreate,
    repository: CreditFacilityRepository = Depends(get_credit_facility_repository),
    principal: Principal = Depends(require_permissions("risk_events:create")),
) -> dict:
    _scoped_facility(repository, facility_id, principal)
    try:
        return repository.create_risk_event(facility_id, request.model_dump(), principal.name)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{facility_id}/controls")
def control_facility(
    facility_id: str,
    request: FacilityControlRequest,
    repository: CreditFacilityRepository = Depends(get_credit_facility_repository),
    principal: Principal = Depends(require_permissions("facilities:control")),
) -> dict:
    _scoped_facility(repository, facility_id, principal)
    try:
        return repository.control(facility_id, request.expected_row_version, request.action, request.target_limit, principal.name, request.reason)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{facility_id}/reviews")
def review_facility(
    facility_id: str,
    request: PostCreditReviewRequest,
    repository: CreditFacilityRepository = Depends(get_credit_facility_repository),
    principal: Principal = Depends(require_permissions("facilities:review")),
) -> dict:
    _scoped_facility(repository, facility_id, principal)
    try:
        return repository.review(facility_id, request.expected_row_version, request.rating, request.next_review_days, principal.name, request.conclusion)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _scoped_facility(repository: CreditFacilityRepository, facility_id: str, principal: Principal) -> dict:
    facility = repository.get(facility_id)
    if not facility:
        raise HTTPException(status_code=404, detail="授信台账不存在")
    enforce_counterparty_scope(principal, facility["counterparty_id"])
    return facility
