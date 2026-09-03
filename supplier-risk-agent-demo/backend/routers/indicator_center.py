from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database import get_db_session
from backend.db_models import IndicatorDefinition
from backend.credit_calibration import analyze_credit_calibration, build_credit_calibration_candidate, calibration_configuration
from backend.dependencies import get_credit_calibration_repository, get_demo_repository, get_model_governance_repository, get_model_monitoring_repository, get_rule_center_replay_dataset_repository, get_scorecard_repository
from backend.model_governance import validate_and_assess
from backend.monitoring_workflow import build_observed_monitoring_dataset, select_effective_monitoring_dataset
from backend.repository import ConcurrentUpdateError
from backend.repository import DemoRepository, ModelGovernanceRepository, ModelMonitoringRepository, RuleCenterReplayDatasetRepository, content_hash
from backend.schemas import CreditCalibrationAnalyze, CreditCalibrationComparisonRequest, CreditCalibrationModelChangeCreate, CreditCalibrationPlanCreate, CreditCalibrationPlanModelChange, CreditCalibrationPlanReview, CreditCalibrationPlanRun, CreditCalibrationPlanUpdate, ScorecardChangeCreate, ScorecardChangeReview, ScorecardChangeUpdate, ScorecardDevelopmentRunCreate, ScorecardDevelopmentRunReview, ScorecardMonitoringBulkAssignRequest, ScorecardMonitoringEventAction, ScorecardMonitoringEventFilters, ScorecardMonitoringPlanCreate, ScorecardMonitoringPlanRunRequest, ScorecardMonitoringPlanUpdate, ScorecardMonitoringSavedViewPayload, ScorecardMonitoringSavedViewUpdate, ScorecardMonitoringSchedulerRetryRequest, ScorecardMonitoringSlaPolicyCreate, ScorecardMonitoringSlaPolicyUpdate, ScorecardMonitoringTickRequest, ScorecardValidationPolicyCreate, ScorecardValidationPolicyUpdate, VersionedActionRequest
from backend.credit_calibration_repository import CreditCalibrationRepository
from backend.scorecard_repository import ScorecardRepository
from backend.security import Principal, get_current_principal, require_permissions
from rating.enterprise_indicator_pool import get_indicator_pool, list_enterprise_risk_indicators

router = APIRouter(prefix="/indicator-center", tags=["indicator-center"])


@router.get("/catalog")
def indicator_catalog(
    session: Session = Depends(get_db_session),
    _: Principal = Depends(require_permissions("models:view")),
) -> dict:
    governed = session.scalars(
        select(IndicatorDefinition).where(IndicatorDefinition.is_active.is_(True), IndicatorDefinition.status == "published")
    ).all()
    governed_by_code = {item.code: item for item in governed}
    pool = get_indicator_pool()
    items = []
    for item in list_enterprise_risk_indicators():
        versioned = governed_by_code.get(item["id"])
        items.append({
            "code": item["id"], "name": item["name"], "category": item["category"],
            "data_type": "numeric" if item["data_type"] in {"numeric", "count", "amount", "years", "ratio", "percentage", "days"} else "boolean",
            "version": str(versioned.version) if versioned else pool["version"],
            "version_source": "indicator_factory" if versioned else "enterprise_pool",
            "field_path": versioned.field_path if versioned else item["field_path"],
            "description": item["description"], "default_weight": float(versioned.default_weight) if versioned else item["default_weight"],
        })
    for code, item in governed_by_code.items():
        if not any(row["code"] == code for row in items):
            items.append({"code": code, "name": item.name, "category": item.category, "data_type": item.data_type, "version": str(item.version), "version_source": "indicator_factory", "field_path": item.field_path, "description": item.expression or "治理指标", "default_weight": float(item.default_weight)})
    return {"count": len(items), "items": sorted(items, key=lambda row: (row["category"], row["name"]))}


@router.get("/scorecards")
def list_scorecards(repository: ScorecardRepository = Depends(get_scorecard_repository), _: Principal = Depends(require_permissions("models:view"))) -> list[dict]:
    return repository.list_assets()


@router.get("/scorecard-changes")
def list_scorecard_changes(repository: ScorecardRepository = Depends(get_scorecard_repository), _: Principal = Depends(require_permissions("models:view"))) -> list[dict]:
    return repository.list_changes()


@router.get("/scorecard-development-runs")
def list_scorecard_development_runs(repository: ScorecardRepository = Depends(get_scorecard_repository), _: Principal = Depends(require_permissions("models:view"))) -> list[dict]:
    return repository.list_development_runs()


@router.get("/scorecard-development-trends")
def scorecard_development_trends(
    scorecard_code: str | None = Query(default=None, min_length=2, max_length=128),
    max_runs: int = Query(default=200, ge=1, le=500),
    repository: ScorecardRepository = Depends(get_scorecard_repository),
    _: Principal = Depends(require_permissions("models:view")),
) -> dict:
    return repository.development_trends(scorecard_code, max_runs)


@router.get("/scorecard-portfolio-stability")
def scorecard_portfolio_stability(
    repository: ScorecardRepository = Depends(get_scorecard_repository),
    _: Principal = Depends(require_permissions("models:view")),
) -> dict:
    return repository.portfolio_stability()


@router.get("/credit-calibration/config")
def credit_calibration_config(
    template_key: str = Query(default="corporate_credit_v2", min_length=2, max_length=64),
    demo_repository: DemoRepository = Depends(get_demo_repository),
    governance: ModelGovernanceRepository = Depends(get_model_governance_repository),
    _: Principal = Depends(require_permissions("models:view")),
) -> dict:
    config = governance.get_config(demo_repository, template_key)
    if not config:
        raise HTTPException(status_code=404, detail="模型模板不存在")
    try:
        return calibration_configuration(config)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/credit-calibration/analyze")
def run_credit_calibration(
    body: CreditCalibrationAnalyze,
    demo_repository: DemoRepository = Depends(get_demo_repository),
    governance: ModelGovernanceRepository = Depends(get_model_governance_repository),
    datasets: RuleCenterReplayDatasetRepository = Depends(get_rule_center_replay_dataset_repository),
    _: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    config = governance.get_config(demo_repository, body.template_key)
    if not config:
        raise HTTPException(status_code=404, detail="模型模板不存在")
    try:
        snapshot = datasets.get_snapshot_for_analysis(body.dataset_snapshot_id)
        return analyze_credit_calibration(config, snapshot, body.model_dump())
    except (LookupError, ValueError) as exc:
        raise _error(exc) from exc


@router.post("/credit-calibration/model-changes", status_code=status.HTTP_201_CREATED)
def create_credit_calibration_model_change(
    body: CreditCalibrationModelChangeCreate,
    demo_repository: DemoRepository = Depends(get_demo_repository),
    governance: ModelGovernanceRepository = Depends(get_model_governance_repository),
    monitoring: ModelMonitoringRepository = Depends(get_model_monitoring_repository),
    datasets: RuleCenterReplayDatasetRepository = Depends(get_rule_center_replay_dataset_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    raise HTTPException(status_code=410, detail="一次性校准不能直接生成模型草稿；请保存方案、完成运行并通过独立复核")


@router.get("/credit-calibration/plans")
def list_credit_calibration_plans(
    repository: CreditCalibrationRepository = Depends(get_credit_calibration_repository),
    _: Principal = Depends(require_permissions("models:view")),
) -> list[dict]:
    return repository.list_plans()


@router.post("/credit-calibration/plans", status_code=status.HTTP_201_CREATED)
def create_credit_calibration_plan(
    body: CreditCalibrationPlanCreate,
    repository: CreditCalibrationRepository = Depends(get_credit_calibration_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    try:
        return repository.create_plan(body.model_dump(), principal.subject, principal.name)
    except (ValueError, ConcurrentUpdateError) as exc:
        raise _error(exc) from exc


@router.put("/credit-calibration/plans/{plan_id}")
def update_credit_calibration_plan(
    plan_id: str, body: CreditCalibrationPlanUpdate,
    repository: CreditCalibrationRepository = Depends(get_credit_calibration_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    try:
        return repository.update_plan(plan_id, body.expected_row_version, body.model_dump(exclude={"expected_row_version"}), principal.subject, "admin" in principal.roles)
    except (LookupError, PermissionError, ValueError, ConcurrentUpdateError) as exc:
        raise _error(exc) from exc


@router.post("/credit-calibration/plans/{plan_id}/runs", status_code=status.HTTP_201_CREATED)
def run_credit_calibration_plan(
    plan_id: str, body: CreditCalibrationPlanRun,
    repository: CreditCalibrationRepository = Depends(get_credit_calibration_repository),
    demo_repository: DemoRepository = Depends(get_demo_repository),
    governance: ModelGovernanceRepository = Depends(get_model_governance_repository),
    datasets: RuleCenterReplayDatasetRepository = Depends(get_rule_center_replay_dataset_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    try:
        plan = repository.get_plan(plan_id)
        base = governance.get_config(demo_repository, plan["template_key"])
        if not base:
            raise LookupError("模型模板不存在")
        snapshot = datasets.get_snapshot_for_analysis(body.dataset_snapshot_id)
        analysis = analyze_credit_calibration(base, snapshot, {
            "dataset_snapshot_id": body.dataset_snapshot_id, "template_key": plan["template_key"],
            "positive_labels": plan["positive_labels"], "sample_limit": plan["sample_limit"], "candidate": plan["candidate"],
        })
        return repository.create_run(plan_id, body.expected_row_version, analysis, principal.subject, principal.name)
    except (LookupError, PermissionError, ValueError, ConcurrentUpdateError) as exc:
        raise _error(exc) from exc


@router.post("/credit-calibration/plans/{plan_id}/submit")
def submit_credit_calibration_plan(
    plan_id: str, body: VersionedActionRequest,
    repository: CreditCalibrationRepository = Depends(get_credit_calibration_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    try:
        return repository.submit_plan(plan_id, body.expected_row_version, principal.subject, "admin" in principal.roles)
    except (LookupError, PermissionError, ValueError, ConcurrentUpdateError) as exc:
        raise _error(exc) from exc


@router.post("/credit-calibration/plans/{plan_id}/review")
def review_credit_calibration_plan(
    plan_id: str, body: CreditCalibrationPlanReview,
    repository: CreditCalibrationRepository = Depends(get_credit_calibration_repository),
    principal: Principal = Depends(require_permissions("models:review")),
) -> dict:
    try:
        return repository.review_plan(plan_id, body.expected_row_version, body.decision, body.comment, principal.subject, principal.name)
    except (LookupError, PermissionError, ValueError, ConcurrentUpdateError) as exc:
        raise _error(exc) from exc


@router.post("/credit-calibration/comparisons")
def compare_credit_calibration_plans(
    body: CreditCalibrationComparisonRequest,
    repository: CreditCalibrationRepository = Depends(get_credit_calibration_repository),
    _: Principal = Depends(require_permissions("models:view")),
) -> dict:
    try:
        return repository.compare(body.plan_ids)
    except (LookupError, ValueError) as exc:
        raise _error(exc) from exc


@router.post("/credit-calibration/plans/{plan_id}/model-changes", status_code=status.HTTP_201_CREATED)
def create_governed_credit_calibration_model_change(
    plan_id: str, body: CreditCalibrationPlanModelChange,
    repository: CreditCalibrationRepository = Depends(get_credit_calibration_repository),
    demo_repository: DemoRepository = Depends(get_demo_repository),
    governance: ModelGovernanceRepository = Depends(get_model_governance_repository),
    monitoring: ModelMonitoringRepository = Depends(get_model_monitoring_repository),
    datasets: RuleCenterReplayDatasetRepository = Depends(get_rule_center_replay_dataset_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    try:
        plan, run = repository.approved_run(plan_id, body.expected_row_version, body.run_id)
        base = governance.get_config(demo_repository, plan["template_key"])
        if not base:
            raise LookupError("模型模板不存在")
        snapshot = datasets.get_snapshot_for_analysis(run["dataset_snapshot_id"])
        analysis = analyze_credit_calibration(base, snapshot, {
            "dataset_snapshot_id": run["dataset_snapshot_id"], "template_key": plan["template_key"],
            "positive_labels": plan["positive_labels"], "sample_limit": plan["sample_limit"], "candidate": plan["candidate"],
        })
        if analysis["evidence_hash"] != run["evidence_hash"]:
            raise ConcurrentUpdateError("已批准校准证据或模型基线已变化，请创建新方案版本并重新复核")
        candidate = build_credit_calibration_candidate(base, plan["candidate"], body.candidate_version, body.change_reason)
        outcomes = monitoring.list_outcomes(plan["template_key"])
        verified = [item for item in outcomes if item["verification_status"] == "verified"]
        observed_dataset, readiness = build_observed_monitoring_dataset(plan["template_key"], verified)
        monitoring_dataset, _ = select_effective_monitoring_dataset(observed_dataset, readiness, demo_repository.get_model_monitoring_dataset(plan["template_key"]))
        validation, impact = validate_and_assess(base, candidate, demo_repository.list_counterparties(), plan["template_key"], monitoring_dataset)
        if not validation["valid"]:
            raise ValueError("；".join(validation["errors"]))
        calibration_evidence = {
            "schema_version": "credit-calibration-evidence-v2", "plan_id": plan["id"], "plan_code": plan["code"],
            "plan_version": plan["version"], "plan_config_hash": plan["config_hash"], "plan_reviewed_by": plan["reviewed_by"],
            "calibration_run_id": run["id"], "dataset_snapshot_id": analysis["snapshot"]["id"],
            "dataset_snapshot_hash": analysis["snapshot"]["content_hash"], "template_key": plan["template_key"],
            "base_model_version": base["version"], "baseline_config_hash": analysis["model"]["baseline_config_hash"],
            "candidate_config_hash": content_hash(candidate), "analysis": analysis,
            "bound_at": datetime.now(timezone.utc).isoformat(), "bound_by": principal.subject, "bound_by_name": principal.name,
        }
        return governance.create_change({
            "template_key": plan["template_key"], "base_version": base["version"], "candidate_version": body.candidate_version,
            "config": candidate, "validation": validation, "impact": impact, "calibration_evidence": calibration_evidence,
            "change_reason": body.change_reason,
        }, principal.subject, principal.name)
    except (LookupError, PermissionError, ValueError, ConcurrentUpdateError) as exc:
        message = str(exc)
        if "候选版本不能重复" in message:
            raise HTTPException(status_code=409, detail=message) from exc
        raise _error(exc) from exc


@router.get("/scorecard-monitoring-plans")
def list_scorecard_monitoring_plans(repository: ScorecardRepository = Depends(get_scorecard_repository), _: Principal = Depends(require_permissions("models:view"))) -> list[dict]:
    return repository.list_monitoring_plans()


@router.post("/scorecard-monitoring-plans", status_code=status.HTTP_201_CREATED)
def create_scorecard_monitoring_plan(body: ScorecardMonitoringPlanCreate, repository: ScorecardRepository = Depends(get_scorecard_repository), principal: Principal = Depends(require_permissions("models:manage"))) -> dict:
    try:
        return repository.create_monitoring_plan(body.plan.model_dump(), principal.subject)
    except (LookupError, ValueError, ConcurrentUpdateError) as exc:
        raise _error(exc) from exc


@router.put("/scorecard-monitoring-plans/{plan_id}")
def update_scorecard_monitoring_plan(plan_id: str, body: ScorecardMonitoringPlanUpdate, repository: ScorecardRepository = Depends(get_scorecard_repository), principal: Principal = Depends(require_permissions("models:manage"))) -> dict:
    try:
        return repository.update_monitoring_plan(plan_id, body.expected_row_version, body.plan.model_dump(), principal.subject)
    except (LookupError, ValueError, ConcurrentUpdateError) as exc:
        raise _error(exc) from exc


@router.post("/scorecard-monitoring-plans/{plan_id}/run")
def run_scorecard_monitoring_plan(plan_id: str, body: ScorecardMonitoringPlanRunRequest, repository: ScorecardRepository = Depends(get_scorecard_repository), principal: Principal = Depends(require_permissions("models:manage"))) -> dict:
    try:
        return repository.run_monitoring_plan(plan_id, body.expected_row_version, principal.subject, principal.name)
    except (LookupError, ValueError, ConcurrentUpdateError) as exc:
        raise _error(exc) from exc


@router.post("/scorecard-monitoring-plans/run-due")
def run_due_scorecard_monitoring_plans(body: ScorecardMonitoringTickRequest, repository: ScorecardRepository = Depends(get_scorecard_repository), principal: Principal = Depends(require_permissions("models:manage"))) -> dict:
    try:
        return repository.run_monitoring_scheduler(
            body.as_of or datetime.now(timezone.utc), body.max_plans, principal.subject, principal.name,
            run_key=body.run_key, trigger_type=body.trigger_type,
        )
    except (LookupError, ValueError, ConcurrentUpdateError) as exc:
        raise _error(exc) from exc


@router.get("/scorecard-monitoring-scheduler/health")
def scorecard_monitoring_scheduler_health(
    max_runs: int = Query(default=20, ge=1, le=100),
    repository: ScorecardRepository = Depends(get_scorecard_repository),
    _: Principal = Depends(require_permissions("models:view")),
) -> dict:
    return repository.monitoring_scheduler_health(max_runs=max_runs)


@router.post("/scorecard-monitoring-scheduler/runs/{run_id}/retry")
def retry_scorecard_monitoring_scheduler_run(
    run_id: str,
    body: ScorecardMonitoringSchedulerRetryRequest,
    repository: ScorecardRepository = Depends(get_scorecard_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    try:
        return repository.retry_monitoring_scheduler_run(run_id, body.reason, principal.subject, principal.name, body.max_plans)
    except (LookupError, ValueError, ConcurrentUpdateError) as exc:
        raise _error(exc) from exc


@router.get("/scorecard-monitoring-events")
def list_scorecard_monitoring_events(
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    severity: str | None = Query(default=None, max_length=16),
    event_type: str | None = Query(default=None, max_length=64),
    assignee: str | None = Query(default=None, max_length=128),
    plan_id: str | None = Query(default=None, max_length=36),
    scorecard_code: str | None = Query(default=None, max_length=128),
    sla_status: str | None = Query(default=None, max_length=32),
    repository: ScorecardRepository = Depends(get_scorecard_repository),
    _: Principal = Depends(require_permissions("models:view")),
) -> list[dict]:
    try:
        filters = ScorecardMonitoringEventFilters(status=status_filter, severity=severity, event_type=event_type, assignee=assignee, plan_id=plan_id, scorecard_code=scorecard_code, sla_status=sla_status)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="预警筛选条件不合法") from exc
    return repository.list_monitoring_events(**filters.model_dump())


@router.get("/scorecard-monitoring-events/export")
def export_scorecard_monitoring_events(
    status_filter: str | None = Query(default=None, alias="status", max_length=32), severity: str | None = Query(default=None, max_length=16),
    event_type: str | None = Query(default=None, max_length=64), assignee: str | None = Query(default=None, max_length=128),
    plan_id: str | None = Query(default=None, max_length=36), scorecard_code: str | None = Query(default=None, max_length=128),
    sla_status: str | None = Query(default=None, max_length=32), repository: ScorecardRepository = Depends(get_scorecard_repository),
    _: Principal = Depends(require_permissions("models:view")),
) -> Response:
    try:
        filters = ScorecardMonitoringEventFilters(status=status_filter, severity=severity, event_type=event_type, assignee=assignee, plan_id=plan_id, scorecard_code=scorecard_code, sla_status=sla_status)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="预警筛选条件不合法") from exc
    content = repository.export_monitoring_events_csv(filters.model_dump())
    filename = f"scorecard-monitoring-events-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.csv"
    return Response(content=content.encode("utf-8"), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/scorecard-monitoring-events/bulk-assign")
def bulk_assign_scorecard_monitoring_events(body: ScorecardMonitoringBulkAssignRequest, repository: ScorecardRepository = Depends(get_scorecard_repository), principal: Principal = Depends(require_permissions("models:manage"))) -> dict:
    try:
        return repository.bulk_assign_monitoring_events([item.model_dump() for item in body.items], body.assignee, body.reason, principal.subject, principal.name)
    except (LookupError, ValueError, ConcurrentUpdateError) as exc:
        raise _error(exc) from exc


@router.get("/scorecard-monitoring-saved-views")
def list_scorecard_monitoring_saved_views(repository: ScorecardRepository = Depends(get_scorecard_repository), principal: Principal = Depends(require_permissions("models:view"))) -> list[dict]:
    return repository.list_monitoring_saved_views(principal.subject)


@router.post("/scorecard-monitoring-saved-views", status_code=status.HTTP_201_CREATED)
def create_scorecard_monitoring_saved_view(body: ScorecardMonitoringSavedViewPayload, repository: ScorecardRepository = Depends(get_scorecard_repository), principal: Principal = Depends(require_permissions("models:view"))) -> dict:
    try:
        return repository.create_monitoring_saved_view(body.model_dump(), principal.subject)
    except (ValueError, ConcurrentUpdateError) as exc:
        raise _error(exc) from exc


@router.put("/scorecard-monitoring-saved-views/{view_id}")
def update_scorecard_monitoring_saved_view(view_id: str, body: ScorecardMonitoringSavedViewUpdate, repository: ScorecardRepository = Depends(get_scorecard_repository), principal: Principal = Depends(require_permissions("models:view"))) -> dict:
    try:
        return repository.update_monitoring_saved_view(view_id, body.expected_row_version, body.model_dump(exclude={"expected_row_version"}), principal.subject)
    except (LookupError, ValueError, ConcurrentUpdateError) as exc:
        raise _error(exc) from exc


@router.delete("/scorecard-monitoring-saved-views/{view_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scorecard_monitoring_saved_view(view_id: str, expected_row_version: int = Query(ge=1), repository: ScorecardRepository = Depends(get_scorecard_repository), principal: Principal = Depends(require_permissions("models:view"))) -> Response:
    try:
        repository.delete_monitoring_saved_view(view_id, expected_row_version, principal.subject)
    except (LookupError, ConcurrentUpdateError) as exc:
        raise _error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/scorecard-monitoring-events/{event_id}/action")
def action_scorecard_monitoring_event(event_id: str, body: ScorecardMonitoringEventAction, repository: ScorecardRepository = Depends(get_scorecard_repository), principal: Principal = Depends(get_current_principal)) -> dict:
    required_permission = "models:review" if body.action == "review_revalidation" else "models:manage"
    if not principal.can(required_permission):
        raise HTTPException(status_code=403, detail=f"无权执行当前操作，缺少权限：{required_permission}")
    try:
        return repository.action_monitoring_event(event_id, body.expected_row_version, body.model_dump(), principal.subject, principal.name)
    except (LookupError, PermissionError, ValueError, ConcurrentUpdateError) as exc:
        raise _error(exc) from exc


@router.get("/scorecard-monitoring-sla-policies")
def list_scorecard_monitoring_sla_policies(repository: ScorecardRepository = Depends(get_scorecard_repository), _: Principal = Depends(require_permissions("models:view"))) -> list[dict]:
    return repository.list_monitoring_sla_policies()


@router.post("/scorecard-monitoring-sla-policies", status_code=status.HTTP_201_CREATED)
def create_scorecard_monitoring_sla_policy(body: ScorecardMonitoringSlaPolicyCreate, repository: ScorecardRepository = Depends(get_scorecard_repository), principal: Principal = Depends(require_permissions("models:manage"))) -> dict:
    try:
        return repository.create_monitoring_sla_policy(body.policy.model_dump(), body.change_reason, principal.subject, principal.name)
    except (ValueError, ConcurrentUpdateError) as exc:
        raise _error(exc) from exc


@router.put("/scorecard-monitoring-sla-policies/{policy_id}")
def update_scorecard_monitoring_sla_policy(policy_id: str, body: ScorecardMonitoringSlaPolicyUpdate, repository: ScorecardRepository = Depends(get_scorecard_repository), principal: Principal = Depends(require_permissions("models:manage"))) -> dict:
    try:
        return repository.update_monitoring_sla_policy(policy_id, body.expected_row_version, body.policy.model_dump(), body.change_reason, principal.subject, "admin" in principal.roles)
    except (LookupError, PermissionError, ValueError, ConcurrentUpdateError) as exc:
        raise _error(exc) from exc


@router.post("/scorecard-monitoring-sla-policies/{policy_id}/submit")
def submit_scorecard_monitoring_sla_policy(policy_id: str, body: VersionedActionRequest, repository: ScorecardRepository = Depends(get_scorecard_repository), principal: Principal = Depends(require_permissions("models:manage"))) -> dict:
    try:
        return repository.submit_monitoring_sla_policy(policy_id, body.expected_row_version, principal.subject, "admin" in principal.roles)
    except (LookupError, PermissionError, ValueError, ConcurrentUpdateError) as exc:
        raise _error(exc) from exc


@router.post("/scorecard-monitoring-sla-policies/{policy_id}/review")
def review_scorecard_monitoring_sla_policy(policy_id: str, body: ScorecardChangeReview, repository: ScorecardRepository = Depends(get_scorecard_repository), principal: Principal = Depends(require_permissions("models:review"))) -> dict:
    try:
        return repository.review_monitoring_sla_policy(policy_id, body.expected_row_version, body.decision, body.comment, principal.subject, principal.name)
    except (LookupError, PermissionError, ValueError, ConcurrentUpdateError) as exc:
        raise _error(exc) from exc


@router.get("/validation-policies")
def list_validation_policies(repository: ScorecardRepository = Depends(get_scorecard_repository), _: Principal = Depends(require_permissions("models:view"))) -> list[dict]:
    return repository.list_validation_policies()


@router.post("/validation-policies", status_code=status.HTTP_201_CREATED)
def create_validation_policy(body: ScorecardValidationPolicyCreate, repository: ScorecardRepository = Depends(get_scorecard_repository), principal: Principal = Depends(require_permissions("models:manage"))) -> dict:
    try:
        return repository.create_validation_policy(body.policy.model_dump(), body.change_reason, principal.subject, principal.name)
    except (ValueError, ConcurrentUpdateError) as exc:
        raise _error(exc) from exc


@router.put("/validation-policies/{policy_id}")
def update_validation_policy(policy_id: str, body: ScorecardValidationPolicyUpdate, repository: ScorecardRepository = Depends(get_scorecard_repository), principal: Principal = Depends(require_permissions("models:manage"))) -> dict:
    try:
        return repository.update_validation_policy(policy_id, body.expected_row_version, body.policy.model_dump(), body.change_reason, principal.subject, "admin" in principal.roles)
    except (LookupError, PermissionError, ValueError, ConcurrentUpdateError) as exc:
        raise _error(exc) from exc


@router.post("/validation-policies/{policy_id}/submit")
def submit_validation_policy(policy_id: str, body: VersionedActionRequest, repository: ScorecardRepository = Depends(get_scorecard_repository), principal: Principal = Depends(require_permissions("models:manage"))) -> dict:
    try:
        return repository.submit_validation_policy(policy_id, body.expected_row_version, principal.subject, "admin" in principal.roles)
    except (LookupError, PermissionError, ValueError, ConcurrentUpdateError) as exc:
        raise _error(exc) from exc


@router.post("/validation-policies/{policy_id}/review")
def review_validation_policy(policy_id: str, body: ScorecardChangeReview, repository: ScorecardRepository = Depends(get_scorecard_repository), principal: Principal = Depends(require_permissions("models:review"))) -> dict:
    try:
        return repository.review_validation_policy(policy_id, body.expected_row_version, body.decision, body.comment, principal.subject, principal.name)
    except (LookupError, PermissionError, ValueError, ConcurrentUpdateError) as exc:
        raise _error(exc) from exc


@router.post("/scorecard-development-runs", status_code=status.HTTP_201_CREATED)
def create_scorecard_development_run(body: ScorecardDevelopmentRunCreate, repository: ScorecardRepository = Depends(get_scorecard_repository), principal: Principal = Depends(require_permissions("models:manage"))) -> dict:
    try:
        return repository.create_development_run(body.model_dump(), principal.subject, principal.name)
    except (LookupError, ValueError) as exc:
        raise _error(exc) from exc


@router.post("/scorecard-development-runs/{run_id}/review")
def review_scorecard_development_run(run_id: str, body: ScorecardDevelopmentRunReview, repository: ScorecardRepository = Depends(get_scorecard_repository), principal: Principal = Depends(require_permissions("models:review"))) -> dict:
    try:
        return repository.review_development_run(run_id, body.expected_row_version, body.decision, body.comment, principal.subject, principal.name)
    except (LookupError, PermissionError, ValueError, ConcurrentUpdateError) as exc:
        raise _error(exc) from exc


@router.post("/scorecard-changes", status_code=status.HTTP_201_CREATED)
def create_scorecard_change(body: ScorecardChangeCreate, repository: ScorecardRepository = Depends(get_scorecard_repository), principal: Principal = Depends(require_permissions("models:manage"))) -> dict:
    try:
        return repository.create_draft(body.definition.model_dump(), body.change_reason, principal.subject, principal.name)
    except (ValueError, ConcurrentUpdateError) as exc:
        raise HTTPException(status_code=409 if isinstance(exc, ConcurrentUpdateError) else 422, detail=str(exc)) from exc


@router.put("/scorecard-changes/{change_id}")
def update_scorecard_change(change_id: str, body: ScorecardChangeUpdate, repository: ScorecardRepository = Depends(get_scorecard_repository), principal: Principal = Depends(require_permissions("models:manage"))) -> dict:
    try:
        return repository.update_draft(change_id, body.expected_row_version, body.definition.model_dump(), body.change_reason, principal.subject, "admin" in principal.roles)
    except (LookupError, PermissionError, ValueError, ConcurrentUpdateError) as exc:
        raise _error(exc) from exc


@router.post("/scorecard-changes/{change_id}/submit")
def submit_scorecard_change(change_id: str, body: VersionedActionRequest, repository: ScorecardRepository = Depends(get_scorecard_repository), principal: Principal = Depends(require_permissions("models:manage"))) -> dict:
    try:
        return repository.submit(change_id, body.expected_row_version, principal.subject, "admin" in principal.roles)
    except (LookupError, PermissionError, ValueError, ConcurrentUpdateError) as exc:
        raise _error(exc) from exc


@router.post("/scorecard-changes/{change_id}/review")
def review_scorecard_change(change_id: str, body: ScorecardChangeReview, repository: ScorecardRepository = Depends(get_scorecard_repository), principal: Principal = Depends(require_permissions("models:review"))) -> dict:
    try:
        return repository.review(change_id, body.expected_row_version, body.decision, body.comment, principal.subject, principal.name)
    except (LookupError, PermissionError, ValueError, ConcurrentUpdateError) as exc:
        raise _error(exc) from exc


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, ConcurrentUpdateError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))
