"""Rule Center API endpoints."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database import get_db_session
from backend.db_models import (
    DecisionPipelineDefinition,
    RuleDefinition,
    RuleSetDefinition,
)
from backend.dependencies import (
    get_demo_repository,
    get_decision_pipeline_repository,
    get_model_governance_repository,
    get_rule_center_governance_repository,
    get_rule_center_release_package_repository,
    get_rule_center_replay_comparison_repository,
    get_rule_center_replay_dataset_repository,
    get_rule_definition_repository,
    get_rule_set_definition_repository,
)
from backend.repository import (
    ConcurrentUpdateError,
    DecisionPipelineRepository,
    DemoRepository,
    ModelGovernanceRepository,
    RuleCenterGovernanceRepository,
    RuleCenterReleasePackageRepository,
    RuleCenterReplayComparisonRepository,
    RuleCenterReplayDatasetRepository,
    RuleDefinitionRepository,
    RuleSetDefinitionRepository,
)
from backend.schemas import (
    PipelineCreate,
    PipelineSimulateRequest,
    RuleCreate,
    RuleCenterActivationScan,
    RuleCenterChangeCreate,
    RuleCenterChangeReview,
    RuleCenterChangeUpdate,
    RuleCenterRestoreDraft,
    RuleCenterPackageCreate,
    RuleCenterPackagePreview,
    RuleCenterPackageReview,
    RuleCenterReplayCreate,
    RuleCenterReplayComparisonCreate,
    RuleCenterReplayComparisonExceptionCreate,
    RuleCenterReplayComparisonExceptionReview,
    RuleCenterReplayDatasetCreate,
    RuleCenterReplaySnapshotImport,
    RuleSetCreate,
    RuleTestRequest,
    VersionedActionRequest,
)
from backend.security import Principal, require_permissions
from rating.decision_pipeline import run_decision_pipeline
from rating.rule_evaluator import evaluate_rule_conditions


router = APIRouter(prefix="/rule-center", tags=["rule-center"])


@router.get("/rules")
def list_rules(
    rule_type: str | None = None,
    category: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    session: Session = Depends(get_db_session),
    _: Principal = Depends(require_permissions("models:view")),
) -> list[dict]:
    statement = select(RuleDefinition).where(RuleDefinition.is_active.is_(True))
    if rule_type:
        statement = statement.where(RuleDefinition.rule_type == rule_type)
    if category:
        statement = statement.where(RuleDefinition.category == category)
    if status_filter:
        statement = statement.where(RuleDefinition.status == status_filter)
    rules = session.scalars(statement.order_by(RuleDefinition.code)).all()
    return [_rule_to_dict(rule) for rule in rules]


@router.get("/rules/{code}")
def get_rule(
    code: str,
    session: Session = Depends(get_db_session),
    _: Principal = Depends(require_permissions("models:view")),
) -> dict:
    rule = _active_definition(session, RuleDefinition, code)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"规则 {code} 不存在")
    return _rule_to_dict(rule)


@router.post("/rules", status_code=status.HTTP_201_CREATED)
def create_rule(
    body: RuleCreate,
    repository: RuleDefinitionRepository = Depends(
        get_rule_definition_repository
    ),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    try:
        rule = repository.publish_rule(
            body.model_dump(), principal.subject, principal.name
        )
    except (ValueError, ConcurrentUpdateError) as exc:
        raise _publication_error(exc) from exc
    return _rule_to_dict(rule)


@router.post("/rules/{code}/publish")
def publish_rule(
    code: str,
    session: Session = Depends(get_db_session),
    repository: RuleDefinitionRepository = Depends(
        get_rule_definition_repository
    ),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    existing = _active_definition(session, RuleDefinition, code)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"规则 {code} 不存在")
    try:
        result = repository.publish_rule(
            _rule_definition(existing), principal.subject, principal.name
        )
    except (ValueError, ConcurrentUpdateError) as exc:
        raise _publication_error(exc) from exc
    return _rule_to_dict(result)


@router.post("/rules/{code}/test")
def test_rule(
    code: str,
    body: RuleTestRequest,
    session: Session = Depends(get_db_session),
    _: Principal = Depends(require_permissions("models:view")),
) -> dict:
    rule = _active_definition(session, RuleDefinition, code)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"规则 {code} 不存在")
    triggered, details = evaluate_rule_conditions(rule, body.context)
    return {"triggered": triggered, "details": details}


@router.get("/rule-sets")
def list_rule_sets(
    session: Session = Depends(get_db_session),
    _: Principal = Depends(require_permissions("models:view")),
) -> list[dict]:
    items = session.scalars(
        select(RuleSetDefinition)
        .where(RuleSetDefinition.is_active.is_(True))
        .order_by(RuleSetDefinition.code)
    ).all()
    return [_rule_set_to_dict(item) for item in items]


@router.get("/rule-sets/{code}")
def get_rule_set(
    code: str,
    session: Session = Depends(get_db_session),
    _: Principal = Depends(require_permissions("models:view")),
) -> dict:
    item = _active_definition(session, RuleSetDefinition, code)
    if item is None:
        raise HTTPException(status_code=404, detail=f"规则集 {code} 不存在")
    return _rule_set_to_dict(item)


@router.post("/rule-sets", status_code=status.HTTP_201_CREATED)
def create_rule_set(
    body: RuleSetCreate,
    repository: RuleSetDefinitionRepository = Depends(
        get_rule_set_definition_repository
    ),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    try:
        item = repository.publish_rule_set(
            body.model_dump(), principal.subject, principal.name
        )
    except (ValueError, ConcurrentUpdateError) as exc:
        raise _publication_error(exc) from exc
    return _rule_set_to_dict(item)


@router.post("/rule-sets/{code}/publish")
def publish_rule_set(
    code: str,
    session: Session = Depends(get_db_session),
    repository: RuleSetDefinitionRepository = Depends(
        get_rule_set_definition_repository
    ),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    existing = _active_definition(session, RuleSetDefinition, code)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"规则集 {code} 不存在")
    try:
        result = repository.publish_rule_set(
            _rule_set_definition(existing), principal.subject, principal.name
        )
    except (ValueError, ConcurrentUpdateError) as exc:
        raise _publication_error(exc) from exc
    return _rule_set_to_dict(result)


@router.get("/pipelines")
def list_pipelines(
    session: Session = Depends(get_db_session),
    _: Principal = Depends(require_permissions("models:view")),
) -> list[dict]:
    items = session.scalars(
        select(DecisionPipelineDefinition)
        .where(DecisionPipelineDefinition.is_active.is_(True))
        .order_by(DecisionPipelineDefinition.code)
    ).all()
    return [_pipeline_to_dict(item) for item in items]


@router.get("/pipelines/{code}")
def get_pipeline(
    code: str,
    session: Session = Depends(get_db_session),
    _: Principal = Depends(require_permissions("models:view")),
) -> dict:
    item = _active_definition(session, DecisionPipelineDefinition, code)
    if item is None:
        raise HTTPException(status_code=404, detail=f"决策管线 {code} 不存在")
    return _pipeline_to_dict(item)


@router.post("/pipelines", status_code=status.HTTP_201_CREATED)
def create_pipeline(
    body: PipelineCreate,
    repository: DecisionPipelineRepository = Depends(
        get_decision_pipeline_repository
    ),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    try:
        item = repository.publish_pipeline(
            body.model_dump(exclude_none=True), principal.subject, principal.name
        )
    except (ValueError, ConcurrentUpdateError) as exc:
        raise _publication_error(exc) from exc
    return _pipeline_to_dict(item)


@router.post("/pipelines/{code}/publish")
def publish_pipeline(
    code: str,
    session: Session = Depends(get_db_session),
    repository: DecisionPipelineRepository = Depends(
        get_decision_pipeline_repository
    ),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    existing = _active_definition(session, DecisionPipelineDefinition, code)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"决策管线 {code} 不存在")
    try:
        result = repository.publish_pipeline(
            _pipeline_definition(existing), principal.subject, principal.name
        )
    except (ValueError, ConcurrentUpdateError) as exc:
        raise _publication_error(exc) from exc
    return _pipeline_to_dict(result)


@router.post("/pipelines/{code}/simulate")
def simulate_pipeline(
    code: str,
    body: PipelineSimulateRequest,
    _: Principal = Depends(require_permissions("models:view")),
) -> dict:
    context = {"counterparty": body.counterparty, "config": body.config}
    result = run_decision_pipeline(code, context)
    if result is None:
        raise HTTPException(
            status_code=422,
            detail=f"决策管线 {code} 不存在、未激活或依赖不完整",
        )
    return {"result": result, "trace": context.get("pipeline_trace", {})}


@router.get("/governance/changes")
def list_governance_changes(
    asset_type: str | None = None,
    code: str | None = None,
    repository: RuleCenterGovernanceRepository = Depends(
        get_rule_center_governance_repository
    ),
    _: Principal = Depends(require_permissions("models:view")),
) -> list[dict]:
    try:
        return repository.list_changes(asset_type, code)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/governance/changes", status_code=status.HTTP_201_CREATED)
def create_governance_change(
    body: RuleCenterChangeCreate,
    repository: RuleCenterGovernanceRepository = Depends(
        get_rule_center_governance_repository
    ),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    definition = _validated_governance_definition(
        body.asset_type, body.definition
    )
    try:
        return repository.create_draft(
            body.asset_type,
            definition,
            body.change_reason,
            principal.subject,
            principal.name,
        )
    except (ValueError, ConcurrentUpdateError) as exc:
        raise _governance_error(exc) from exc


@router.put("/governance/changes/{change_id}")
def update_governance_change(
    change_id: str,
    body: RuleCenterChangeUpdate,
    repository: RuleCenterGovernanceRepository = Depends(
        get_rule_center_governance_repository
    ),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    current = repository.get_change(change_id)
    if current is None:
        raise HTTPException(status_code=404, detail="规则中心治理变更不存在")
    definition = _validated_governance_definition(
        current["asset_type"], body.definition
    )
    try:
        return repository.update_draft(
            change_id,
            body.expected_row_version,
            definition,
            body.change_reason,
            principal.subject,
            principal.name,
            "admin" in principal.roles,
        )
    except (LookupError, PermissionError, ValueError, ConcurrentUpdateError) as exc:
        raise _governance_error(exc) from exc


@router.post("/governance/changes/{change_id}/submit")
def submit_governance_change(
    change_id: str,
    body: VersionedActionRequest,
    repository: RuleCenterGovernanceRepository = Depends(
        get_rule_center_governance_repository
    ),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    try:
        return repository.submit(
            change_id,
            body.expected_row_version,
            principal.subject,
            principal.name,
            "admin" in principal.roles,
        )
    except (LookupError, PermissionError, ValueError, ConcurrentUpdateError) as exc:
        raise _governance_error(exc) from exc


@router.post("/governance/changes/{change_id}/review")
def review_governance_change(
    change_id: str,
    body: RuleCenterChangeReview,
    repository: RuleCenterGovernanceRepository = Depends(
        get_rule_center_governance_repository
    ),
    principal: Principal = Depends(require_permissions("models:review")),
) -> dict:
    try:
        return repository.review(
            change_id,
            body.expected_row_version,
            body.decision,
            body.comment,
            principal.subject,
            principal.name,
            body.effective_at,
        )
    except (LookupError, PermissionError, ValueError, ConcurrentUpdateError) as exc:
        raise _governance_error(exc) from exc


@router.post("/governance/activation-scan")
def activate_due_governance_changes(
    body: RuleCenterActivationScan,
    repository: RuleCenterGovernanceRepository = Depends(
        get_rule_center_governance_repository
    ),
    principal: Principal = Depends(require_permissions("models:review")),
) -> dict:
    return repository.activate_due(
        body.as_of or datetime.now(timezone.utc),
        principal.subject,
        principal.name,
    )


@router.get("/governance/history")
def governance_history(
    asset_type: str,
    code: str,
    repository: RuleCenterGovernanceRepository = Depends(
        get_rule_center_governance_repository
    ),
    _: Principal = Depends(require_permissions("models:view")),
) -> list[dict]:
    try:
        return repository.list_history(asset_type, code)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/governance/restore-drafts", status_code=status.HTTP_201_CREATED)
def create_governance_restore_draft(
    body: RuleCenterRestoreDraft,
    repository: RuleCenterGovernanceRepository = Depends(
        get_rule_center_governance_repository
    ),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    try:
        return repository.create_restore_draft(
            body.asset_type,
            body.code,
            body.version,
            body.change_reason,
            principal.subject,
            principal.name,
        )
    except (LookupError, PermissionError, ValueError, ConcurrentUpdateError) as exc:
        raise _governance_error(exc) from exc


@router.post("/governance/packages/impact")
def preview_release_package(
    body: RuleCenterPackagePreview,
    repository: RuleCenterReleasePackageRepository = Depends(
        get_rule_center_release_package_repository
    ),
    _: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    try:
        return repository.preview(body.change_ids)
    except (LookupError, PermissionError, ValueError, ConcurrentUpdateError) as exc:
        raise _governance_error(exc) from exc


@router.get("/governance/packages")
def list_release_packages(
    repository: RuleCenterReleasePackageRepository = Depends(
        get_rule_center_release_package_repository
    ),
    _: Principal = Depends(require_permissions("models:view")),
) -> list[dict]:
    return repository.list_packages()


@router.post("/governance/packages", status_code=status.HTTP_201_CREATED)
def create_release_package(
    body: RuleCenterPackageCreate,
    repository: RuleCenterReleasePackageRepository = Depends(
        get_rule_center_release_package_repository
    ),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    try:
        return repository.create(
            body.name,
            body.change_reason,
            body.change_ids,
            principal.subject,
            principal.name,
            "admin" in principal.roles,
        )
    except (LookupError, PermissionError, ValueError, ConcurrentUpdateError) as exc:
        raise _governance_error(exc) from exc


@router.get("/governance/replay-datasets")
def list_replay_datasets(
    repository: RuleCenterReplayDatasetRepository = Depends(
        get_rule_center_replay_dataset_repository
    ),
    principal: Principal = Depends(require_permissions("models:view")),
) -> list[dict]:
    return repository.list_datasets(principal.tenant_id)


@router.post("/governance/replay-datasets", status_code=status.HTTP_201_CREATED)
def create_replay_dataset(
    body: RuleCenterReplayDatasetCreate,
    repository: RuleCenterReplayDatasetRepository = Depends(
        get_rule_center_replay_dataset_repository
    ),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    try:
        return repository.create_dataset(
            principal.tenant_id, body.code, body.name, body.description, principal.subject, principal.name
        )
    except (ValueError, ConcurrentUpdateError) as exc:
        raise _governance_error(exc) from exc


@router.get("/governance/replay-datasets/snapshots")
def list_all_replay_dataset_snapshots(
    repository: RuleCenterReplayDatasetRepository = Depends(
        get_rule_center_replay_dataset_repository
    ),
    principal: Principal = Depends(require_permissions("models:view")),
) -> list[dict]:
    return repository.list_snapshots(principal.tenant_id)


@router.get("/governance/replay-datasets/{dataset_id}/snapshots")
def list_replay_dataset_snapshots(
    dataset_id: str,
    repository: RuleCenterReplayDatasetRepository = Depends(
        get_rule_center_replay_dataset_repository
    ),
    principal: Principal = Depends(require_permissions("models:view")),
) -> list[dict]:
    try:
        return repository.list_snapshots(principal.tenant_id, dataset_id)
    except LookupError as exc:
        raise _governance_error(exc) from exc


@router.post("/governance/replay-datasets/{dataset_id}/snapshots", status_code=status.HTTP_201_CREATED)
def import_replay_dataset_snapshot(
    dataset_id: str,
    body: RuleCenterReplaySnapshotImport,
    repository: RuleCenterReplayDatasetRepository = Depends(
        get_rule_center_replay_dataset_repository
    ),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    try:
        return repository.import_snapshot(
            principal.tenant_id, dataset_id, body.model_dump(), principal.subject, principal.name
        )
    except (LookupError, ValueError, ConcurrentUpdateError) as exc:
        raise _governance_error(exc) from exc


@router.get("/governance/replay-comparisons")
def list_replay_comparisons(
    repository: RuleCenterReplayComparisonRepository = Depends(
        get_rule_center_replay_comparison_repository
    ),
    principal: Principal = Depends(require_permissions("models:view")),
) -> list[dict]:
    return repository.list_runs(principal.tenant_id)


@router.post("/governance/replay-comparisons", status_code=status.HTTP_201_CREATED)
def run_replay_comparison(
    body: RuleCenterReplayComparisonCreate,
    repository: RuleCenterReplayComparisonRepository = Depends(
        get_rule_center_replay_comparison_repository
    ),
    model_repository: ModelGovernanceRepository = Depends(get_model_governance_repository),
    demo_repository: DemoRepository = Depends(get_demo_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    try:
        return repository.run(
            principal.tenant_id, body.model_dump(), demo_repository, model_repository,
            principal.subject, principal.name,
        )
    except (LookupError, ValueError, ConcurrentUpdateError) as exc:
        raise _governance_error(exc) from exc


@router.get("/governance/replay-comparisons/{comparison_run_id}/exceptions")
def list_replay_comparison_exceptions(
    comparison_run_id: str,
    repository: RuleCenterReplayComparisonRepository = Depends(
        get_rule_center_replay_comparison_repository
    ),
    principal: Principal = Depends(require_permissions("models:view")),
) -> list[dict]:
    try:
        return repository.list_exceptions(principal.tenant_id, comparison_run_id)
    except LookupError as exc:
        raise _governance_error(exc) from exc


@router.post("/governance/replay-comparisons/{comparison_run_id}/exceptions", status_code=status.HTTP_201_CREATED)
def request_replay_comparison_exception(
    comparison_run_id: str,
    body: RuleCenterReplayComparisonExceptionCreate,
    repository: RuleCenterReplayComparisonRepository = Depends(
        get_rule_center_replay_comparison_repository
    ),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    try:
        return repository.request_exception(
            principal.tenant_id, comparison_run_id, body.model_dump(), principal.subject, principal.name
        )
    except (LookupError, ValueError, ConcurrentUpdateError) as exc:
        raise _governance_error(exc) from exc


@router.post("/governance/replay-comparisons/{comparison_run_id}/exceptions/{exception_id}/review")
def review_replay_comparison_exception(
    comparison_run_id: str,
    exception_id: str,
    body: RuleCenterReplayComparisonExceptionReview,
    repository: RuleCenterReplayComparisonRepository = Depends(
        get_rule_center_replay_comparison_repository
    ),
    principal: Principal = Depends(require_permissions("models:review")),
) -> dict:
    try:
        return repository.review_exception(
            principal.tenant_id, comparison_run_id, exception_id, body.expected_row_version,
            body.decision, body.comment, principal.subject, principal.name,
        )
    except (LookupError, PermissionError, ValueError, ConcurrentUpdateError) as exc:
        raise _governance_error(exc) from exc


@router.post("/governance/packages/{package_id}/submit")
def submit_release_package(
    package_id: str,
    body: VersionedActionRequest,
    repository: RuleCenterReleasePackageRepository = Depends(
        get_rule_center_release_package_repository
    ),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    try:
        return repository.submit(
            principal.tenant_id,
            package_id,
            body.expected_row_version,
            principal.subject,
            principal.name,
            "admin" in principal.roles,
        )
    except (LookupError, PermissionError, ValueError, ConcurrentUpdateError) as exc:
        raise _governance_error(exc) from exc


@router.get("/governance/packages/{package_id}/replays")
def list_release_package_replays(
    package_id: str,
    repository: RuleCenterReleasePackageRepository = Depends(
        get_rule_center_release_package_repository
    ),
    principal: Principal = Depends(require_permissions("models:view")),
) -> list[dict]:
    try:
        return repository.list_replays(principal.tenant_id, package_id)
    except LookupError as exc:
        raise _governance_error(exc) from exc


@router.post("/governance/packages/{package_id}/replays", status_code=status.HTTP_201_CREATED)
def run_release_package_replay(
    package_id: str,
    body: RuleCenterReplayCreate,
    repository: RuleCenterReleasePackageRepository = Depends(
        get_rule_center_release_package_repository
    ),
    demo_repository: DemoRepository = Depends(get_demo_repository),
    governance: ModelGovernanceRepository = Depends(get_model_governance_repository),
    principal: Principal = Depends(require_permissions("models:manage")),
) -> dict:
    try:
        if body.min_sample_count > body.sample_limit:
            raise ValueError("最低样本数不能大于样本上限")
        config = governance.get_config(demo_repository, body.model_key)
        if not config:
            raise LookupError("评分模型不存在")
        return repository.run_replay(
            principal.tenant_id,
            package_id,
            body.dataset_snapshot_id,
            body.model_key,
            config,
            body.pipeline_code,
            {
                "sample_limit": body.sample_limit,
                "min_sample_count": body.min_sample_count,
                "max_decision_change_rate": body.max_decision_change_rate,
                "max_execution_failure_rate": body.max_execution_failure_rate,
            },
            principal.subject,
            principal.name,
        )
    except (LookupError, PermissionError, ValueError, ConcurrentUpdateError) as exc:
        raise _governance_error(exc) from exc


@router.post("/governance/packages/{package_id}/review")
def review_release_package(
    package_id: str,
    body: RuleCenterPackageReview,
    repository: RuleCenterReleasePackageRepository = Depends(
        get_rule_center_release_package_repository
    ),
    principal: Principal = Depends(require_permissions("models:review")),
) -> dict:
    try:
        return repository.review(
            principal.tenant_id,
            package_id,
            body.expected_row_version,
            body.decision,
            body.comment,
            principal.subject,
            principal.name,
        )
    except (LookupError, PermissionError, ValueError, ConcurrentUpdateError) as exc:
        raise _governance_error(exc) from exc


def _validated_governance_definition(
    asset_type: str, definition: dict
) -> dict:
    schema = {
        "rule": RuleCreate,
        "rule_set": RuleSetCreate,
        "pipeline": PipelineCreate,
    }.get(asset_type)
    if schema is None:
        raise HTTPException(status_code=422, detail="不支持的规则中心资产类型")
    try:
        return schema.model_validate(definition).model_dump(exclude_none=True)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _governance_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        code = 404
    elif isinstance(exc, PermissionError):
        code = 403
    elif isinstance(exc, ConcurrentUpdateError):
        code = 409
    else:
        code = 422
    return HTTPException(status_code=code, detail=str(exc))


def _active_definition(session: Session, model, code: str):
    return session.scalars(
        select(model).where(model.code == code, model.is_active.is_(True))
    ).first()


def _publication_error(exc: Exception) -> HTTPException:
    status_code = 409 if isinstance(exc, ConcurrentUpdateError) else 422
    return HTTPException(status_code=status_code, detail=str(exc))


def _rule_definition(rule: RuleDefinition) -> dict:
    return {
        "code": rule.code,
        "name": rule.name,
        "rule_type": rule.rule_type,
        "category": rule.category,
        "enabled": rule.enabled,
        "conditions_json": rule.conditions_json,
        "condition_relation": rule.condition_relation,
        "actions_json": rule.actions_json,
        "priority": rule.priority,
    }


def _rule_set_definition(item: RuleSetDefinition) -> dict:
    return {
        "code": item.code,
        "name": item.name,
        "rule_codes": item.rule_codes,
        "evaluation_strategy": item.evaluation_strategy,
    }


def _pipeline_definition(item: DecisionPipelineDefinition) -> dict:
    return {
        "code": item.code,
        "name": item.name,
        "stages_json": item.stages_json,
    }


def _rule_to_dict(rule: RuleDefinition) -> dict:
    return {
        "id": rule.id,
        **_rule_definition(rule),
        "version": rule.version,
        "status": rule.status,
        "is_active": rule.is_active,
        "created_at": rule.created_at.isoformat() if rule.created_at else None,
        "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
        "created_by": rule.created_by,
    }


def _rule_set_to_dict(item: RuleSetDefinition) -> dict:
    return {
        "id": item.id,
        **_rule_set_definition(item),
        "version": item.version,
        "status": item.status,
        "is_active": item.is_active,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        "created_by": item.created_by,
    }


def _pipeline_to_dict(item: DecisionPipelineDefinition) -> dict:
    return {
        "id": item.id,
        **_pipeline_definition(item),
        "version": item.version,
        "status": item.status,
        "is_active": item.is_active,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        "created_by": item.created_by,
    }
