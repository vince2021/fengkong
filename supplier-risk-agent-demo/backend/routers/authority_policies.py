from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.authority_policy_impact import build_authority_policy_impact, compare_authority_policy_scenarios
from backend.authority_policy_repository import AuthorityPolicyRepository, normalize_authority_policy_config
from backend.dependencies import get_authority_policy_repository, get_demo_repository, get_model_governance_repository
from backend.repository import ConcurrentUpdateError, DemoRepository, ModelGovernanceRepository
from backend.schemas import AuthorityPolicyActivationIncidentAction, AuthorityPolicyActivationRetry, AuthorityPolicyActivationScanRequest, AuthorityPolicyCreate, AuthorityPolicyEvidenceAnchorReplace, AuthorityPolicyEvidenceAnchorRevoke, AuthorityPolicyImpactRequest, AuthorityPolicyRestoreDraftRequest, AuthorityPolicyReview, AuthorityPolicyScenarioCompareRequest, AuthorityPolicyScheduleCancel, AuthorityPolicyUpdate, VersionedActionRequest
from backend.security import Principal, require_permissions


router = APIRouter(prefix="/authority-policies", tags=["credit-authority-governance"])


def _evaluate_impact(
    policy_version: str,
    config: dict,
    repository: AuthorityPolicyRepository,
    demo_repository: DemoRepository,
    governance: ModelGovernanceRepository,
) -> dict:
    normalized = normalize_authority_policy_config(config)
    return build_authority_policy_impact(
        active_policy=repository.active_snapshot(),
        candidate_config=normalized,
        candidate_policy_version=policy_version,
        counterparties=demo_repository.list_counterparties(),
        model_config_resolver=lambda template_key: governance.get_config(demo_repository, template_key),
    )


@router.get("")
def list_authority_policies(
    repository: AuthorityPolicyRepository = Depends(get_authority_policy_repository),
    _: Principal = Depends(require_permissions("authority_policy:view")),
) -> list[dict]:
    return repository.list()


@router.get("/active")
def get_active_authority_policy(
    repository: AuthorityPolicyRepository = Depends(get_authority_policy_repository),
    _: Principal = Depends(require_permissions("authority_policy:view")),
) -> dict:
    return repository.active_snapshot()


@router.post("/impact")
def evaluate_authority_policy_impact(
    request: AuthorityPolicyImpactRequest,
    repository: AuthorityPolicyRepository = Depends(get_authority_policy_repository),
    demo_repository: DemoRepository = Depends(get_demo_repository),
    governance: ModelGovernanceRepository = Depends(get_model_governance_repository),
    _: Principal = Depends(require_permissions("authority_policy:manage")),
) -> dict:
    try:
        return _evaluate_impact(request.policy_version, request.config.model_dump(), repository, demo_repository, governance)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/scenarios")
def compare_authority_policy_scenario_set(
    request: AuthorityPolicyScenarioCompareRequest,
    repository: AuthorityPolicyRepository = Depends(get_authority_policy_repository),
    demo_repository: DemoRepository = Depends(get_demo_repository),
    governance: ModelGovernanceRepository = Depends(get_model_governance_repository),
    _: Principal = Depends(require_permissions("authority_policy:manage")),
) -> dict:
    try:
        scenarios = [
            {
                **scenario.model_dump(exclude={"config"}),
                "config": normalize_authority_policy_config(scenario.config.model_dump()),
            }
            for scenario in request.scenarios
        ]
        return compare_authority_policy_scenarios(
            active_policy=repository.active_snapshot(),
            scenarios=scenarios,
            counterparties=demo_repository.list_counterparties(),
            model_config_resolver=lambda template_key: governance.get_config(demo_repository, template_key),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/restore-drafts", status_code=201)
def create_authority_policy_restore_draft(
    request: AuthorityPolicyRestoreDraftRequest,
    repository: AuthorityPolicyRepository = Depends(get_authority_policy_repository),
    demo_repository: DemoRepository = Depends(get_demo_repository),
    governance: ModelGovernanceRepository = Depends(get_model_governance_repository),
    principal: Principal = Depends(require_permissions("authority_policy:manage")),
) -> dict:
    try:
        source = repository.restore_source_snapshot(request.source_policy_ref)
        impact = _evaluate_impact(
            request.policy_version,
            source["config"],
            repository,
            demo_repository,
            governance,
        )
        return repository.create(
            request.policy_version,
            request.change_reason,
            source["config"],
            impact,
            principal.subject,
            principal.name,
            restore_source=source,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("", status_code=201)
def create_authority_policy(
    request: AuthorityPolicyCreate,
    repository: AuthorityPolicyRepository = Depends(get_authority_policy_repository),
    demo_repository: DemoRepository = Depends(get_demo_repository),
    governance: ModelGovernanceRepository = Depends(get_model_governance_repository),
    principal: Principal = Depends(require_permissions("authority_policy:manage")),
) -> dict:
    try:
        config = request.config.model_dump()
        impact = _evaluate_impact(request.policy_version, config, repository, demo_repository, governance)
        return repository.create(
            request.policy_version,
            request.change_reason,
            config,
            impact,
            principal.subject,
            principal.name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/{policy_id}")
def update_authority_policy(
    policy_id: str,
    request: AuthorityPolicyUpdate,
    repository: AuthorityPolicyRepository = Depends(get_authority_policy_repository),
    demo_repository: DemoRepository = Depends(get_demo_repository),
    governance: ModelGovernanceRepository = Depends(get_model_governance_repository),
    principal: Principal = Depends(require_permissions("authority_policy:manage")),
) -> dict:
    try:
        config = request.config.model_dump()
        impact = _evaluate_impact(
            repository.get(policy_id)["policy_version"],
            config,
            repository,
            demo_repository,
            governance,
        )
        return repository.update(
            policy_id,
            request.expected_row_version,
            request.change_reason,
            config,
            impact,
            principal.subject,
            principal.name,
            "admin" in principal.roles,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{policy_id}/submit")
def submit_authority_policy(
    policy_id: str,
    request: VersionedActionRequest,
    repository: AuthorityPolicyRepository = Depends(get_authority_policy_repository),
    demo_repository: DemoRepository = Depends(get_demo_repository),
    governance: ModelGovernanceRepository = Depends(get_model_governance_repository),
    principal: Principal = Depends(require_permissions("authority_policy:manage")),
) -> dict:
    try:
        record = repository.get(policy_id)
        current_impact = _evaluate_impact(
            record["policy_version"],
            record["config"],
            repository,
            demo_repository,
            governance,
        )
        repository.assert_impact_current(policy_id, current_impact)
        return repository.submit(
            policy_id,
            request.expected_row_version,
            principal.subject,
            principal.name,
            "admin" in principal.roles,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{policy_id}/review")
def review_authority_policy(
    policy_id: str,
    request: AuthorityPolicyReview,
    repository: AuthorityPolicyRepository = Depends(get_authority_policy_repository),
    demo_repository: DemoRepository = Depends(get_demo_repository),
    governance: ModelGovernanceRepository = Depends(get_model_governance_repository),
    principal: Principal = Depends(require_permissions("authority_policy:review")),
) -> dict:
    try:
        if request.decision == "publish":
            record = repository.get(policy_id)
            current_impact = _evaluate_impact(
                record["policy_version"],
                record["config"],
                repository,
                demo_repository,
                governance,
            )
            repository.assert_impact_current(policy_id, current_impact)
        return repository.review(
            policy_id,
            request.expected_row_version,
            request.decision,
            request.comment,
            principal.subject,
            principal.name,
            request.effective_at,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/activation-scan")
def activate_due_authority_policy(
    request: AuthorityPolicyActivationScanRequest | None = None,
    repository: AuthorityPolicyRepository = Depends(get_authority_policy_repository),
    principal: Principal = Depends(require_permissions("authority_policy:review")),
) -> dict:
    try:
        return repository.activate_due(
            principal.subject,
            principal.name,
            run_key=request.run_key if request else None,
            trigger_type=request.trigger_type if request else "manual",
        )
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/activation-status")
def get_authority_policy_activation_status(
    limit: int = Query(default=12, ge=1, le=50),
    repository: AuthorityPolicyRepository = Depends(get_authority_policy_repository),
    _: Principal = Depends(require_permissions("authority_policy:view")),
) -> dict:
    return repository.activation_status(limit)


@router.get("/evidence/compare")
def compare_authority_policy_evidence(
    base_policy_id: str = Query(min_length=1, max_length=36),
    candidate_policy_id: str = Query(min_length=1, max_length=36),
    repository: AuthorityPolicyRepository = Depends(get_authority_policy_repository),
    _: Principal = Depends(require_permissions("authority_policy:view")),
) -> dict:
    try:
        return repository.compare_evidence_packages(base_policy_id, candidate_policy_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/evidence/anchors/{anchor_id}")
def get_authority_policy_evidence_anchor(
    anchor_id: str,
    repository: AuthorityPolicyRepository = Depends(get_authority_policy_repository),
    _: Principal = Depends(require_permissions("authority_policy:view")),
) -> dict:
    try:
        return repository.get_evidence_anchor(anchor_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/evidence/anchors/{anchor_id}/receipt")
def get_authority_policy_evidence_anchor_receipt(
    anchor_id: str,
    repository: AuthorityPolicyRepository = Depends(get_authority_policy_repository),
    _: Principal = Depends(require_permissions("authority_policy:view")),
) -> dict:
    try:
        return repository.evidence_anchor_receipt(anchor_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/evidence/anchors/{anchor_id}/revoke")
def revoke_authority_policy_evidence_anchor(
    anchor_id: str,
    request: AuthorityPolicyEvidenceAnchorRevoke,
    repository: AuthorityPolicyRepository = Depends(get_authority_policy_repository),
    principal: Principal = Depends(require_permissions("authority_policy:anchor_revoke")),
) -> dict:
    try:
        return repository.revoke_evidence_anchor(
            anchor_id,
            request.expected_row_version,
            request.reason,
            principal.subject,
            principal.name,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/evidence/anchors/{anchor_id}/replace", status_code=201)
def replace_authority_policy_evidence_anchor(
    anchor_id: str,
    request: AuthorityPolicyEvidenceAnchorReplace,
    repository: AuthorityPolicyRepository = Depends(get_authority_policy_repository),
    principal: Principal = Depends(require_permissions("authority_policy:anchor")),
) -> dict:
    try:
        return repository.replace_evidence_anchor(
            anchor_id,
            request.expected_row_version,
            request.reason,
            principal.subject,
            principal.name,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{policy_id}/evidence/anchors")
def list_authority_policy_evidence_anchors(
    policy_id: str,
    limit: int = Query(default=100, ge=1, le=200),
    repository: AuthorityPolicyRepository = Depends(get_authority_policy_repository),
    _: Principal = Depends(require_permissions("authority_policy:view")),
) -> list[dict]:
    try:
        return repository.list_evidence_anchors(policy_id, limit)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{policy_id}/evidence/anchors", status_code=201)
def issue_authority_policy_evidence_anchor(
    policy_id: str,
    repository: AuthorityPolicyRepository = Depends(get_authority_policy_repository),
    principal: Principal = Depends(require_permissions("authority_policy:anchor")),
) -> dict:
    try:
        return repository.issue_evidence_anchor(
            policy_id,
            principal.subject,
            principal.name,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{policy_id}/evidence")
def get_authority_policy_evidence(
    policy_id: str,
    repository: AuthorityPolicyRepository = Depends(get_authority_policy_repository),
    _: Principal = Depends(require_permissions("authority_policy:view")),
) -> dict:
    try:
        return repository.evidence_package(policy_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/activation-runs/{run_id}/acknowledge")
def acknowledge_authority_policy_activation_incident(
    run_id: str,
    request: AuthorityPolicyActivationIncidentAction,
    repository: AuthorityPolicyRepository = Depends(get_authority_policy_repository),
    principal: Principal = Depends(require_permissions("authority_policy:review")),
) -> dict:
    try:
        return repository.acknowledge_activation_incident(
            run_id,
            request.expected_row_version,
            request.note,
            principal.subject,
            principal.name,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/activation-runs/{run_id}/retry")
def retry_authority_policy_activation_incident(
    run_id: str,
    request: AuthorityPolicyActivationRetry,
    repository: AuthorityPolicyRepository = Depends(get_authority_policy_repository),
    principal: Principal = Depends(require_permissions("authority_policy:review")),
) -> dict:
    try:
        return repository.retry_activation_incident(
            run_id,
            request.expected_row_version,
            request.note,
            principal.subject,
            principal.name,
            request.run_key,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{policy_id}/cancel-schedule")
def cancel_authority_policy_schedule(
    policy_id: str,
    request: AuthorityPolicyScheduleCancel,
    repository: AuthorityPolicyRepository = Depends(get_authority_policy_repository),
    principal: Principal = Depends(require_permissions("authority_policy:review")),
) -> dict:
    try:
        return repository.cancel_schedule(
            policy_id,
            request.expected_row_version,
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
