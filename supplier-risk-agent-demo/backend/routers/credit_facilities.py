from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from backend.counterparty_repository import CounterpartyError, CounterpartyRepository
from backend.dependencies import get_approval_repository, get_counterparty_repository, get_credit_facility_repository
from backend.repository import ApprovalCaseRepository, ConcurrentUpdateError, CreditFacilityRepository
from backend.schemas import AlertDispositionRequest, CreditUsageRequest, FacilityControlConditionCompleteRequest, FacilityControlExtensionCreateRequest, FacilityControlExtensionReviewRequest, FacilityControlRequest, FacilityRenewalRequest, PostCreditReviewRequest, RiskEventCreate
from backend.security import Principal, enforce_counterparty_scope, require_permissions
from rating.approval_workflow import create_facility_renewal_case


router = APIRouter(prefix="/credit-facilities", tags=["post-credit-management"])


@router.get("")
def list_facilities(
    repository: CreditFacilityRepository = Depends(get_credit_facility_repository),
    principal: Principal = Depends(require_permissions("facilities:view")),
) -> list[dict]:
    return repository.list(principal.tenant_id, principal.counterparty_id if "client" in principal.roles else None)


@router.get("/summary")
def facility_summary(
    repository: CreditFacilityRepository = Depends(get_credit_facility_repository),
    principal: Principal = Depends(require_permissions("facilities:view")),
) -> dict:
    return repository.summary(principal.tenant_id, principal.counterparty_id if "client" in principal.roles else None)


@router.get("/alerts")
def list_facility_alerts(
    repository: CreditFacilityRepository = Depends(get_credit_facility_repository),
    principal: Principal = Depends(require_permissions("facilities:view")),
) -> list[dict]:
    return repository.list_alerts(principal.tenant_id, principal.counterparty_id if "client" in principal.roles else None)


@router.get("/risk-events")
def list_risk_events(
    repository: CreditFacilityRepository = Depends(get_credit_facility_repository),
    principal: Principal = Depends(require_permissions("facilities:view")),
) -> list[dict]:
    return repository.list_risk_events(principal.tenant_id, counterparty_id=principal.counterparty_id if "client" in principal.roles else None)


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge_alert(
    alert_id: str,
    repository: CreditFacilityRepository = Depends(get_credit_facility_repository),
    principal: Principal = Depends(require_permissions("facility_alerts:act")),
) -> dict:
    alert = repository.acknowledge_alert(principal.tenant_id, alert_id, principal.name)
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
        return repository.dispose_alert(principal.tenant_id, alert_id, request.expected_alert_version, request.expected_facility_version, request.action, request.target_limit, principal.name, request.conclusion)
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
    return repository.scan(principal.tenant_id, principal.name)


@router.get("/{facility_id}")
def get_facility(
    facility_id: str,
    repository: CreditFacilityRepository = Depends(get_credit_facility_repository),
    approval_repository: ApprovalCaseRepository = Depends(get_approval_repository),
    principal: Principal = Depends(require_permissions("facilities:view")),
) -> dict:
    facility = _scoped_facility(repository, facility_id, principal)
    renewal_case = approval_repository.latest_renewal(principal.tenant_id, facility_id)
    return {
        **facility,
        "transactions": repository.list_transactions(principal.tenant_id, facility_id),
        "control_conditions": repository.list_control_conditions(principal.tenant_id, facility_id),
        "renewal_case": _renewal_case_summary(renewal_case, facility),
    }


@router.post("/{facility_id}/control-conditions/{condition_id}/complete")
def complete_control_condition(
    facility_id: str,
    condition_id: str,
    request: FacilityControlConditionCompleteRequest,
    repository: CreditFacilityRepository = Depends(get_credit_facility_repository),
    principal: Principal = Depends(require_permissions("facilities:review")),
) -> dict:
    _scoped_facility(repository, facility_id, principal)
    if "admin" not in principal.roles and "risk_manager" not in principal.roles:
        raise HTTPException(status_code=403, detail="授信控制条件必须由风控经理完成闭环")
    try:
        return repository.complete_control_condition(
            principal.tenant_id,
            facility_id,
            condition_id,
            request.expected_row_version,
            principal.name,
            request.conclusion,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{facility_id}/control-conditions/{condition_id}/extensions", status_code=201)
def request_control_extension(
    facility_id: str,
    condition_id: str,
    request: FacilityControlExtensionCreateRequest,
    repository: CreditFacilityRepository = Depends(get_credit_facility_repository),
    principal: Principal = Depends(require_permissions("facilities:review")),
) -> dict:
    _scoped_facility(repository, facility_id, principal)
    if "admin" not in principal.roles and "risk_manager" not in principal.roles:
        raise HTTPException(status_code=403, detail="只有风控经理可以发起控制条件延期申请")
    try:
        return repository.request_control_extension(
            principal.tenant_id,
            facility_id,
            condition_id,
            request.expected_condition_version,
            request.extension_days,
            request.reason,
            principal.subject,
            principal.name,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{facility_id}/control-conditions/{condition_id}/extensions/{extension_id}/review")
def review_control_extension(
    facility_id: str,
    condition_id: str,
    extension_id: str,
    request: FacilityControlExtensionReviewRequest,
    repository: CreditFacilityRepository = Depends(get_credit_facility_repository),
    principal: Principal = Depends(require_permissions("facilities:control")),
) -> dict:
    _scoped_facility(repository, facility_id, principal)
    if "admin" not in principal.roles and "approver" not in principal.roles:
        raise HTTPException(status_code=403, detail="控制条件延期必须由授信审批人独立审批")
    try:
        return repository.review_control_extension(
            principal.tenant_id,
            facility_id,
            condition_id,
            extension_id,
            request.expected_extension_version,
            request.expected_condition_version,
            request.decision,
            request.comment,
            principal.subject,
            principal.name,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{facility_id}/renewals", status_code=201)
def create_facility_renewal(
    facility_id: str,
    request: FacilityRenewalRequest,
    response: Response,
    repository: CreditFacilityRepository = Depends(get_credit_facility_repository),
    approval_repository: ApprovalCaseRepository = Depends(get_approval_repository),
    counterparty_repository: CounterpartyRepository = Depends(get_counterparty_repository),
    principal: Principal = Depends(require_permissions("approvals:create")),
) -> dict:
    facility = _scoped_facility(repository, facility_id, principal)
    payload = request.model_dump()
    existing = approval_repository.latest_renewal(principal.tenant_id, facility_id, active_only=True)
    if existing:
        if _renewal_matches(existing, payload):
            response.status_code = 200
            return {**existing, "idempotent": True}
        raise HTTPException(status_code=409, detail=f"该授信已有在途续授信 {existing['case_id']}，请先处理原申请")
    if request.expected_row_version != facility["row_version"]:
        raise HTTPException(status_code=409, detail=f"授信台账版本已变化，当前版本为 {facility['row_version']}")
    if facility["status"] == "closed":
        raise HTTPException(status_code=409, detail="已关闭授信不能发起续授信")
    if request.requested_limit < facility["used_limit"]:
        raise HTTPException(
            status_code=422,
            detail=f"续授信申请额度不能低于当前已用余额 {facility['used_limit']:.2f}",
        )
    try:
        counterparty = counterparty_repository.get(principal.tenant_id, facility["counterparty_id"])
    except CounterpartyError as exc:
        raise HTTPException(status_code=404, detail="授信对应的客商主体不存在") from exc
    risk_baseline = repository.risk_snapshot(principal.tenant_id, facility_id)
    case = create_facility_renewal_case(
        counterparty,
        facility,
        request.requested_limit,
        request.requested_term_days,
        request.renewal_reason,
        principal.name,
        risk_baseline,
    )
    try:
        saved = approval_repository.save(
            principal.tenant_id,
            case,
            actor=principal.name,
            event_type="facility_renewal_case_created",
            audit_payload={
                "source_facility_id": facility_id,
                "requested_limit": request.requested_limit,
                "requested_term_days": request.requested_term_days,
                "unresolved_alert_count": risk_baseline["unresolved_alert_count"],
                "active_risk_event_count": risk_baseline["active_risk_event_count"],
            },
            commit=False,
        )
        repository.audit.append(
            "credit_facility",
            facility_id,
            "facility_renewal_initiated",
            principal.name,
            {
                "renewal_case_id": saved["case_id"],
                "requested_limit": request.requested_limit,
                "requested_term_days": request.requested_term_days,
                "source_row_version": request.expected_row_version,
                "unresolved_alert_count": risk_baseline["unresolved_alert_count"],
                "critical_alert_count": risk_baseline["critical_alert_count"],
            },
        )
        repository.commit()
        return {**saved, "idempotent": False}
    except ConcurrentUpdateError as exc:
        repository.rollback()
        concurrent = approval_repository.latest_renewal(principal.tenant_id, facility_id, active_only=True)
        if concurrent and _renewal_matches(concurrent, payload):
            response.status_code = 200
            return {**concurrent, "idempotent": True}
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{facility_id}/transactions")
def create_credit_transaction(
    facility_id: str,
    request: CreditUsageRequest,
    repository: CreditFacilityRepository = Depends(get_credit_facility_repository),
    principal: Principal = Depends(require_permissions("facilities:transact")),
) -> dict:
    _scoped_facility(repository, facility_id, principal)
    try:
        return repository.transact(principal.tenant_id, facility_id, request.transaction_ref, request.transaction_type, request.amount, request.expected_row_version, principal.name, request.reason)
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
        return repository.create_risk_event(principal.tenant_id, facility_id, request.model_dump(), principal.name)
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
        return repository.control(principal.tenant_id, facility_id, request.expected_row_version, request.action, request.target_limit, principal.name, request.reason)
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
        return repository.review(principal.tenant_id, facility_id, request.expected_row_version, request.rating, request.next_review_days, principal.name, request.conclusion)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _scoped_facility(repository: CreditFacilityRepository, facility_id: str, principal: Principal) -> dict:
    facility = repository.get(principal.tenant_id, facility_id)
    if not facility:
        raise HTTPException(status_code=404, detail="授信台账不存在")
    enforce_counterparty_scope(principal, facility["counterparty_id"])
    return facility


def _renewal_case_summary(case: dict | None, source_facility: dict | None = None) -> dict | None:
    if not case:
        return None
    renewal = case.get("data", {}).get("_workflow", {}).get("renewal_request", {})
    source_facility = source_facility or {}
    baseline_keys = {
        "current_payment_term_days",
        "current_rating",
        "current_access_strategy",
        "current_monitoring_frequency",
        "source_expires_at",
    }
    current_limit = float(renewal.get("current_approved_limit", source_facility.get("approved_limit", 0)) or 0)
    requested_limit = float(renewal.get("requested_limit", 0) or 0)
    current_term = int(renewal.get("current_payment_term_days", source_facility.get("payment_term_days", 0)) or 0)
    requested_term = int(renewal.get("requested_term_days", 0) or 0)
    return {
        "case_id": case["case_id"],
        "application_type": case["application_type"],
        "status": case["status"],
        "current_stage": case["current_stage"],
        "created_at": case["created_at"],
        "request_snapshot": {
            "baseline_status": "frozen" if baseline_keys.issubset(renewal) else "legacy_facility_fallback",
            "current_approved_limit": current_limit,
            "current_used_limit": float(renewal.get("current_used_limit", source_facility.get("used_limit", 0)) or 0),
            "current_payment_term_days": current_term,
            "current_rating": renewal.get("current_rating", source_facility.get("rating")),
            "current_access_strategy": renewal.get("current_access_strategy", source_facility.get("access_strategy")),
            "current_monitoring_frequency": renewal.get("current_monitoring_frequency", source_facility.get("monitoring_frequency")),
            "source_expires_at": renewal.get("source_expires_at", source_facility.get("expires_at")),
            "risk_baseline": renewal.get("risk_baseline", {
                "capture_status": "legacy_missing",
                "unresolved_alert_count": 0,
                "critical_alert_count": 0,
                "active_risk_event_count": 0,
                "critical_risk_event_count": 0,
                "signals": [],
            }),
            "requested_limit": requested_limit,
            "requested_term_days": requested_term,
            "limit_delta": requested_limit - current_limit,
            "term_delta_days": requested_term - current_term,
            "renewal_reason": renewal.get("renewal_reason", ""),
        },
    }


def _renewal_matches(case: dict, request: dict) -> bool:
    renewal = case.get("data", {}).get("_workflow", {}).get("renewal_request", {})
    return (
        float(renewal.get("requested_limit", -1)) == float(request["requested_limit"])
        and int(renewal.get("requested_term_days", -1)) == int(request["requested_term_days"])
        and str(renewal.get("renewal_reason", "")).strip() == str(request["renewal_reason"]).strip()
    )
