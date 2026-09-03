from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from backend.dependencies import get_demo_repository, get_model_governance_repository, get_model_monitoring_repository, get_scorecard_repository
from backend.model_governance import build_candidate_config, validate_and_assess
from backend.model_monitoring import build_monitoring_metrics
from backend.model_validation import build_model_validation_report
from backend.monitoring_workflow import build_observed_monitoring_dataset, select_effective_monitoring_dataset
from backend.repository import ConcurrentUpdateError, DemoRepository, ModelGovernanceRepository, ModelMonitoringRepository, content_hash
from backend.scorecard_repository import ScorecardRepository
from backend.schemas import ModelChangeComparisonEvidenceRun, ModelChangeCreate, ModelChangeUpdate, ModelMonitoringRunRequest, ModelMonitoringScheduleCreate, ModelMonitoringScheduleUpdate, ModelOutcomeBatchCreate, ModelOutcomeCreate, ModelOutcomeImportCreate, ModelOutcomeVerificationRequest, ModelReviewRequest, ModelRollbackRequest, MonitoringIssueLinkChangeRequest, MonitoringRemediationRequest, MonitoringRevalidationReviewRequest, MonitoringRevalidationSubmitRequest, MonitoringSchedulerTickRequest, VersionedActionRequest
from backend.security import Principal, require_permissions


router = APIRouter(prefix="/model-governance", tags=["model-governance"])


def _resolve_scorecard_validation_evidence(
    scorecards: ScorecardRepository,
    scorecard_binding: dict | None,
    validation_run_id: str | None,
    principal: Principal,
) -> dict:
    if validation_run_id and not scorecard_binding:
        raise ValueError("未绑定评分卡时不能选择评分卡开发验证证据")
    if not validation_run_id:
        return {}
    evidence = scorecards.approved_validation_evidence(validation_run_id, scorecard_binding or {})
    evidence.update({
        "bound_at": datetime.now(timezone.utc).isoformat(),
        "bound_by": principal.subject,
        "bound_by_name": principal.name,
    })
    return evidence


@router.get("/validation")
def get_validation_report(
    template_key: str,
    candidate_change_id: str | None = None,
    demo_repository: DemoRepository = Depends(get_demo_repository),
    repository: ModelGovernanceRepository = Depends(get_model_governance_repository),
    monitoring_repository: ModelMonitoringRepository = Depends(get_model_monitoring_repository),
    principal: Principal = Depends(require_permissions("models:view")),
) -> dict:
    if candidate_change_id:
        change = repository.get_change(candidate_change_id)
        if not change:
            raise HTTPException(status_code=404, detail="模型变更单不存在")
        if change["template_key"] != template_key:
            raise HTTPException(status_code=422, detail="变更单与模型模板不匹配")
        config = change["config"]
    else:
        config = repository.get_config(demo_repository, template_key)
    if not config:
        raise HTTPException(status_code=404, detail="模型模板不存在")
    dataset, _, _ = _effective_monitoring_context(template_key, demo_repository, monitoring_repository)
    return build_model_validation_report(config, demo_repository.list_counterparties(), template_key, dataset)


@router.get("/monitoring-summary")
def get_monitoring_summary(
    template_key: str,
    demo_repository: DemoRepository = Depends(get_demo_repository),
    monitoring_repository: ModelMonitoringRepository = Depends(get_model_monitoring_repository),
    principal: Principal = Depends(require_permissions("models:view")),
) -> dict:
    dataset, readiness, effective_source = _effective_monitoring_context(template_key, demo_repository, monitoring_repository)
    return {"template_key": template_key, "readiness": readiness, "effective_source": effective_source, "monitoring": build_monitoring_metrics(dataset)}


@router.get("/outcomes")
def list_model_outcomes(
    template_key: str,
    repository: ModelMonitoringRepository = Depends(get_model_monitoring_repository),
    principal: Principal = Depends(require_permissions("models:view")),
) -> list[dict]:
    return repository.list_outcomes(template_key)


@router.post("/outcomes", status_code=201)
def create_model_outcome(
    request: ModelOutcomeCreate,
    demo_repository: DemoRepository = Depends(get_demo_repository),
    governance_repository: ModelGovernanceRepository = Depends(get_model_governance_repository),
    repository: ModelMonitoringRepository = Depends(get_model_monitoring_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    _validate_outcome_reference(request, demo_repository, governance_repository)
    try:
        return repository.create_outcome(request.model_dump(), principal.subject)
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/outcomes/batch")
def create_model_outcomes_batch(
    request: ModelOutcomeBatchCreate,
    demo_repository: DemoRepository = Depends(get_demo_repository),
    governance_repository: ModelGovernanceRepository = Depends(get_model_governance_repository),
    repository: ModelMonitoringRepository = Depends(get_model_monitoring_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    results = _ingest_outcome_rows(request.outcomes, demo_repository, governance_repository, repository, principal.subject)
    return {
        "total": len(results),
        "created": sum(item["status"] == "created" for item in results),
        "idempotent": sum(item["status"] == "idempotent" for item in results),
        "rejected": sum(item["status"] == "rejected" for item in results),
        "results": results,
    }


@router.get("/outcome-imports")
def list_outcome_imports(
    template_key: str | None = None,
    repository: ModelMonitoringRepository = Depends(get_model_monitoring_repository),
    principal: Principal = Depends(require_permissions("models:view")),
) -> list[dict]:
    return repository.list_outcome_imports(template_key)


@router.post("/outcome-imports", status_code=201)
def create_outcome_import(
    request: ModelOutcomeImportCreate,
    demo_repository: DemoRepository = Depends(get_demo_repository),
    governance_repository: ModelGovernanceRepository = Depends(get_model_governance_repository),
    repository: ModelMonitoringRepository = Depends(get_model_monitoring_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    if not demo_repository.get_template(request.template_key):
        raise HTTPException(status_code=404, detail="模型模板不存在")
    try:
        import_record = repository.begin_outcome_import(
            {
                "import_key": request.import_key,
                "source": request.source,
                "template_key": request.template_key,
                "population_period": request.population_period,
                "expected_count": request.expected_count,
                "received_count": len(request.outcomes),
                "payload_hash": content_hash(request.model_dump(mode="json")),
            },
            principal.subject,
        )
        resumed = bool(import_record["idempotent"])
        if resumed and import_record["status"] != "processing":
            return import_record
        try:
            results = _ingest_outcome_rows(
                request.outcomes,
                demo_repository,
                governance_repository,
                repository,
                principal.subject,
                expected_metadata=(request.source, request.template_key, request.population_period),
            )
            return {**repository.complete_outcome_import(import_record["id"], results, principal.subject), "idempotent": resumed}
        except Exception as exc:
            try:
                repository.fail_outcome_import(import_record["id"], str(exc), principal.subject)
            except Exception:
                pass
            raise
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/outcomes/{outcome_id}/verify")
def verify_model_outcome(
    outcome_id: str,
    request: ModelOutcomeVerificationRequest,
    repository: ModelMonitoringRepository = Depends(get_model_monitoring_repository),
    principal: Principal = Depends(require_permissions("models:review")),
) -> dict:
    try:
        return repository.verify_outcome(outcome_id, request.expected_row_version, request.decision, request.note, principal.subject)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/runs")
def list_monitoring_runs(
    template_key: str | None = None,
    repository: ModelMonitoringRepository = Depends(get_model_monitoring_repository),
    principal: Principal = Depends(require_permissions("models:view")),
) -> list[dict]:
    return repository.list_runs(template_key)


@router.post("/runs")
def execute_monitoring_run(
    request: ModelMonitoringRunRequest,
    demo_repository: DemoRepository = Depends(get_demo_repository),
    governance_repository: ModelGovernanceRepository = Depends(get_model_governance_repository),
    monitoring_repository: ModelMonitoringRepository = Depends(get_model_monitoring_repository),
    principal: Principal = Depends(require_permissions("models:review")),
) -> dict:
    try:
        return _execute_monitoring_run(request.model_dump(), demo_repository, governance_repository, monitoring_repository, principal.subject)
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/schedules")
def list_monitoring_schedules(
    template_key: str | None = None,
    repository: ModelMonitoringRepository = Depends(get_model_monitoring_repository),
    principal: Principal = Depends(require_permissions("models:view")),
) -> list[dict]:
    return repository.list_schedules(template_key)


@router.post("/schedules", status_code=201)
def create_monitoring_schedule(
    request: ModelMonitoringScheduleCreate,
    demo_repository: DemoRepository = Depends(get_demo_repository),
    repository: ModelMonitoringRepository = Depends(get_model_monitoring_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    if not demo_repository.get_template(request.template_key):
        raise HTTPException(status_code=404, detail="模型模板不存在")
    try:
        return repository.create_schedule(request.model_dump(), principal.subject)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/schedules/{schedule_id}")
def update_monitoring_schedule(
    schedule_id: str,
    request: ModelMonitoringScheduleUpdate,
    repository: ModelMonitoringRepository = Depends(get_model_monitoring_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    try:
        return repository.update_schedule(schedule_id, request.expected_row_version, request.model_dump(exclude={"expected_row_version"}), principal.subject)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/schedules/run-due")
def run_due_monitoring_schedules(
    request: MonitoringSchedulerTickRequest,
    demo_repository: DemoRepository = Depends(get_demo_repository),
    governance_repository: ModelGovernanceRepository = Depends(get_model_governance_repository),
    repository: ModelMonitoringRepository = Depends(get_model_monitoring_repository),
    principal: Principal = Depends(require_permissions("models:review")),
) -> dict:
    as_of = _as_utc(request.as_of or datetime.now(timezone.utc))
    due_schedules = repository.list_due_schedules(as_of)
    results = []
    for schedule in due_schedules:
        scheduled_for = _as_utc(datetime.fromisoformat(schedule["next_run_at"]))
        run_key = f"SCHEDULE:{schedule['id']}:{scheduled_for.isoformat()}"
        try:
            run = _execute_monitoring_run(
                {"run_key": run_key, "template_key": schedule["template_key"], "as_of_period": _quarter_period(scheduled_for), "trigger_type": "scheduled"},
                demo_repository,
                governance_repository,
                repository,
                principal.subject,
            )
            if run["status"] == "running":
                results.append({"schedule_id": schedule["id"], "run_id": run["id"], "status": "deferred", "error": None})
                continue
            updated = repository.record_schedule_execution(schedule["id"], schedule["row_version"], scheduled_for, as_of, run["id"], run["status"], run.get("error_message"), principal.subject)
            results.append({"schedule_id": schedule["id"], "run_id": run["id"], "status": run["status"], "error": run.get("error_message"), "next_run_at": updated["next_run_at"], "idempotent": bool(run.get("idempotent"))})
        except Exception as exc:
            detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
            failed_run = repository.get_run_by_key(run_key)
            try:
                updated = repository.record_schedule_execution(schedule["id"], schedule["row_version"], scheduled_for, as_of, failed_run["id"] if failed_run else None, "failed", detail, principal.subject)
                next_run_at = updated["next_run_at"]
            except (ConcurrentUpdateError, LookupError) as schedule_exc:
                detail = f"{detail}；计划状态更新失败：{schedule_exc}"
                next_run_at = schedule["next_run_at"]
            results.append({"schedule_id": schedule["id"], "run_id": failed_run["id"] if failed_run else None, "status": "failed", "error": detail, "next_run_at": next_run_at, "idempotent": False})
    return {
        "as_of": as_of.isoformat(),
        "due_count": len(due_schedules),
        "completed": sum(item["status"] == "completed" for item in results),
        "failed": sum(item["status"] == "failed" for item in results),
        "deferred": sum(item["status"] == "deferred" for item in results),
        "results": results,
    }


@router.get("/governance-notifications")
def list_governance_notifications(
    unread_only: bool = False,
    repository: ModelMonitoringRepository = Depends(get_model_monitoring_repository),
    principal: Principal = Depends(require_permissions("models:view")),
) -> list[dict]:
    return repository.list_governance_notifications(principal.roles, unread_only)


@router.post("/governance-notifications/{notification_id}/read")
def read_governance_notification(
    notification_id: str,
    repository: ModelMonitoringRepository = Depends(get_model_monitoring_repository),
    principal: Principal = Depends(require_permissions("models:view")),
) -> dict:
    try:
        return repository.read_governance_notification(notification_id, principal.roles, principal.subject)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/issues")
def list_monitoring_issues(
    template_key: str,
    repository: ModelMonitoringRepository = Depends(get_model_monitoring_repository),
    principal: Principal = Depends(require_permissions("models:view")),
) -> list[dict]:
    return repository.list_issues(template_key)


@router.post("/issues/scan")
def scan_monitoring_issues(
    template_key: str,
    demo_repository: DemoRepository = Depends(get_demo_repository),
    governance_repository: ModelGovernanceRepository = Depends(get_model_governance_repository),
    monitoring_repository: ModelMonitoringRepository = Depends(get_model_monitoring_repository),
    principal: Principal = Depends(require_permissions("models:review")),
) -> list[dict]:
    config = governance_repository.get_config(demo_repository, template_key)
    if not config:
        raise HTTPException(status_code=404, detail="模型模板不存在")
    dataset, _, _ = _effective_monitoring_context(template_key, demo_repository, monitoring_repository)
    monitoring = build_monitoring_metrics(dataset)
    try:
        return monitoring_repository.sync_issues(template_key, config["version"], monitoring, principal.subject)
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/issues/{issue_id}/remediation")
def start_monitoring_remediation(
    issue_id: str,
    request: MonitoringRemediationRequest,
    repository: ModelMonitoringRepository = Depends(get_model_monitoring_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    try:
        return repository.start_remediation(issue_id, request.expected_row_version, request.owner, request.plan, request.due_days, principal.subject)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/issues/{issue_id}/link-change")
def link_monitoring_issue_to_change(
    issue_id: str,
    request: MonitoringIssueLinkChangeRequest,
    repository: ModelMonitoringRepository = Depends(get_model_monitoring_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    try:
        return repository.link_issue_change(issue_id, request.expected_row_version, request.change_id, principal.subject)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/issues/{issue_id}/submit-revalidation")
def submit_monitoring_revalidation(
    issue_id: str,
    request: MonitoringRevalidationSubmitRequest,
    repository: ModelMonitoringRepository = Depends(get_model_monitoring_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    try:
        return repository.submit_revalidation(issue_id, request.expected_row_version, request.result, principal.subject)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/issues/{issue_id}/review")
def review_monitoring_revalidation(
    issue_id: str,
    request: MonitoringRevalidationReviewRequest,
    repository: ModelMonitoringRepository = Depends(get_model_monitoring_repository),
    principal: Principal = Depends(require_permissions("models:review")),
) -> dict:
    try:
        return repository.review_revalidation(issue_id, request.expected_row_version, request.decision, request.conclusion, principal.subject)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/changes")
def list_changes(
    template_key: str | None = None,
    repository: ModelGovernanceRepository = Depends(get_model_governance_repository),
    principal: Principal = Depends(require_permissions("models:view")),
) -> list[dict]:
    return repository.list_changes(template_key)


@router.post("/changes", status_code=201)
def create_change(
    request: ModelChangeCreate,
    demo_repository: DemoRepository = Depends(get_demo_repository),
    repository: ModelGovernanceRepository = Depends(get_model_governance_repository),
    monitoring_repository: ModelMonitoringRepository = Depends(get_model_monitoring_repository),
    scorecards: ScorecardRepository = Depends(get_scorecard_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    base = repository.get_config(demo_repository, request.template_key)
    if not base:
        raise HTTPException(status_code=404, detail="模型模板不存在")
    payload = request.model_dump()
    try:
        payload["scorecard_binding"] = scorecards.binding_for_asset(request.scorecard_id) if request.scorecard_id else None
        payload["scorecard_validation_evidence"] = _resolve_scorecard_validation_evidence(
            scorecards, payload["scorecard_binding"], request.scorecard_validation_run_id, principal
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    candidate = build_candidate_config(base, payload)
    dataset, _, _ = _effective_monitoring_context(request.template_key, demo_repository, monitoring_repository)
    validation, impact = validate_and_assess(base, candidate, demo_repository.list_counterparties(), request.template_key, dataset)
    if not validation["valid"]:
        raise HTTPException(status_code=422, detail="；".join(validation["errors"]))
    try:
        return repository.create_change(
            {
                "template_key": request.template_key,
                "base_version": base["version"],
                "candidate_version": request.candidate_version,
                "config": candidate,
                "validation": validation,
                "impact": impact,
                "scorecard_validation_evidence": payload["scorecard_validation_evidence"],
                "change_reason": request.change_reason,
            },
            principal.subject,
            principal.name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.put("/changes/{change_id}")
def update_change(
    change_id: str,
    request: ModelChangeUpdate,
    demo_repository: DemoRepository = Depends(get_demo_repository),
    repository: ModelGovernanceRepository = Depends(get_model_governance_repository),
    monitoring_repository: ModelMonitoringRepository = Depends(get_model_monitoring_repository),
    scorecards: ScorecardRepository = Depends(get_scorecard_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    change = repository.get_change(change_id)
    if not change:
        raise HTTPException(status_code=404, detail="模型变更单不存在")
    base = repository.get_config(demo_repository, change["template_key"], change["base_version"])
    if not base:
        raise HTTPException(status_code=409, detail="变更单基线版本已不可用")
    payload = {**request.model_dump(), "candidate_version": change["candidate_version"]}
    try:
        payload["scorecard_binding"] = scorecards.binding_for_asset(request.scorecard_id) if request.scorecard_id else None
        payload["scorecard_validation_evidence"] = _resolve_scorecard_validation_evidence(
            scorecards, payload["scorecard_binding"], request.scorecard_validation_run_id, principal
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    candidate = build_candidate_config(base, payload)
    dataset, _, _ = _effective_monitoring_context(change["template_key"], demo_repository, monitoring_repository)
    validation, impact = validate_and_assess(base, candidate, demo_repository.list_counterparties(), change["template_key"], dataset)
    if not validation["valid"]:
        raise HTTPException(status_code=422, detail="；".join(validation["errors"]))
    try:
        return repository.update_change(
            change_id,
            request.expected_row_version,
            {"config": candidate, "validation": validation, "impact": impact, "scorecard_validation_evidence": payload["scorecard_validation_evidence"], "change_reason": request.change_reason},
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


@router.post("/changes/{change_id}/submit")
def submit_change(
    change_id: str,
    request: VersionedActionRequest,
    repository: ModelGovernanceRepository = Depends(get_model_governance_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    try:
        return repository.submit_change(change_id, request.expected_row_version, principal.subject, principal.name, "admin" in principal.roles)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/changes/{change_id}/comparison-evidence/run")
def run_change_comparison_evidence(
    change_id: str,
    request: ModelChangeComparisonEvidenceRun,
    demo_repository: DemoRepository = Depends(get_demo_repository),
    repository: ModelGovernanceRepository = Depends(get_model_governance_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    try:
        return repository.run_and_bind_comparison_evidence(
            change_id, request.expected_row_version, request.model_dump(),
            demo_repository, principal.subject, principal.name, "admin" in principal.roles,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/changes/{change_id}/review")
def review_change(
    change_id: str,
    request: ModelReviewRequest,
    demo_repository: DemoRepository = Depends(get_demo_repository),
    repository: ModelGovernanceRepository = Depends(get_model_governance_repository),
    principal: Principal = Depends(require_permissions("models:review")),
) -> dict:
    try:
        return repository.review_change(change_id, request.expected_row_version, request.decision, request.comment, principal.subject, principal.name, demo_repository)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/releases")
def list_releases(
    template_key: str | None = None,
    repository: ModelGovernanceRepository = Depends(get_model_governance_repository),
    principal: Principal = Depends(require_permissions("models:view")),
) -> list[dict]:
    return repository.list_releases(template_key)


@router.post("/releases/{release_id}/rollback")
def rollback_release(
    release_id: str,
    request: ModelRollbackRequest,
    repository: ModelGovernanceRepository = Depends(get_model_governance_repository),
    principal: Principal = Depends(require_permissions("models:review")),
) -> dict:
    try:
        return repository.rollback(release_id, principal.name, request.comment)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _ingest_outcome_rows(
    outcomes: list[ModelOutcomeCreate],
    demo_repository: DemoRepository,
    governance_repository: ModelGovernanceRepository,
    repository: ModelMonitoringRepository,
    actor: str,
    expected_metadata: tuple[str, str, str] | None = None,
) -> list[dict]:
    results = []
    for index, outcome in enumerate(outcomes):
        try:
            if expected_metadata and (outcome.source, outcome.template_key, outcome.population_period) != expected_metadata:
                raise ValueError("结果行的来源、模型模板或样本期间与导入任务不一致")
            _validate_outcome_reference(outcome, demo_repository, governance_repository)
            saved = repository.create_outcome(outcome.model_dump(), actor)
            results.append({"index": index, "external_observation_id": outcome.external_observation_id, "status": "idempotent" if saved["idempotent"] else "created", "outcome_id": saved["id"], "error": None})
        except (HTTPException, ConcurrentUpdateError, ValueError) as exc:
            detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
            results.append({"index": index, "external_observation_id": outcome.external_observation_id, "status": "rejected", "outcome_id": None, "error": detail})
    return results


def _execute_monitoring_run(
    payload: dict,
    demo_repository: DemoRepository,
    governance_repository: ModelGovernanceRepository,
    monitoring_repository: ModelMonitoringRepository,
    actor: str,
) -> dict:
    template_key = payload["template_key"]
    config = governance_repository.get_config(demo_repository, template_key)
    if not config:
        raise HTTPException(status_code=404, detail="模型模板不存在")
    dataset, readiness, effective_source = _effective_monitoring_context(template_key, demo_repository, monitoring_repository)
    monitoring = build_monitoring_metrics(dataset)
    dataset_meta = monitoring.get("dataset") or {}
    run = monitoring_repository.begin_run(
        {
            **payload,
            "model_version": config["version"],
            "effective_source": effective_source,
            "evidence_level": dataset_meta.get("evidence_level", "none"),
            "dataset_id": dataset_meta.get("dataset_id", f"missing-{template_key}"),
            "readiness": readiness,
        },
        actor,
    )
    if run["idempotent"]:
        return run
    try:
        issues = monitoring_repository.sync_issues(template_key, config["version"], monitoring, actor)
        return {**monitoring_repository.complete_run(run["id"], monitoring, issues, actor), "idempotent": False}
    except Exception as exc:
        try:
            monitoring_repository.fail_run(run["id"], str(exc), actor)
        except Exception:
            pass
        raise


def _as_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _quarter_period(value: datetime) -> str:
    return f"{value.year}Q{(value.month - 1) // 3 + 1}"


def _effective_monitoring_context(
    template_key: str,
    demo_repository: DemoRepository,
    monitoring_repository: ModelMonitoringRepository,
) -> tuple[dict | None, dict, str]:
    outcomes = monitoring_repository.list_outcomes(template_key)
    verified_outcomes = [item for item in outcomes if item["verification_status"] == "verified"]
    observed_dataset, readiness = build_observed_monitoring_dataset(template_key, verified_outcomes)
    readiness.update(
        {
            "submitted_count": len(outcomes),
            "pending_verification_count": sum(item["verification_status"] == "pending_verification" for item in outcomes),
            "rejected_count": sum(item["verification_status"] == "rejected" for item in outcomes),
        }
    )
    dataset, effective_source = select_effective_monitoring_dataset(
        observed_dataset,
        readiness,
        demo_repository.get_model_monitoring_dataset(template_key),
    )
    return dataset, readiness, effective_source


def _validate_outcome_reference(
    request: ModelOutcomeCreate,
    demo_repository: DemoRepository,
    governance_repository: ModelGovernanceRepository,
) -> None:
    if not demo_repository.get_template(request.template_key):
        raise HTTPException(status_code=404, detail="模型模板不存在")
    if not demo_repository.get_counterparty(request.counterparty_id):
        raise HTTPException(status_code=404, detail="客商不存在")
    if not governance_repository.get_config(demo_repository, request.template_key, request.model_version):
        raise HTTPException(status_code=422, detail="观察结果引用的模型版本不存在")
