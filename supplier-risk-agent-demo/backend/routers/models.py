from __future__ import annotations

from copy import deepcopy
from time import perf_counter_ns
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.counterparty_repository import CounterpartyError, CounterpartyRepository
from backend.dependencies import get_counterparty_repository, get_demo_repository, get_enterprise_data_repository, get_enterprise_indicator_observation_repository, get_model_governance_repository, get_portfolio_rating_batch_repository, get_rating_run_repository, get_tenant_runtime_asset_resolver
from backend.indicator_observations import apply_effective_observations
from backend.rating_input_mapping import prepare_rating_input, readiness_summary
from backend.repository import ConcurrentUpdateError, DemoRepository, EnterpriseDataRepository, EnterpriseIndicatorObservationRepository, ModelGovernanceRepository, PortfolioRatingBatchRepository, RatingRunRepository, content_hash
from backend.schemas import ModelImpactRequest, PortfolioRatingBatchCreate, RatingRequest
from backend.security import Principal, require_permissions
from backend.tenant_asset_repository import TenantAssetError
from backend.tenant_runtime_assets import TenantRuntimeAssetResolver
from backend.tenant_rollout_repository import TenantRolloutError
from rating.model_impact import build_score_calculation_trace, get_editable_indicators, simulate_indicator_change
from rating.enterprise_indicator_pool import (
    build_model_indicator_details,
    evaluate_indicator_pool,
    get_indicator_pool,
    list_enterprise_risk_indicators,
)
from rating.risk_screening_policy import get_risk_screening_policy
from rating.portfolio_rating import build_portfolio_result, build_portfolio_summary


router = APIRouter(tags=["ratings-and-models"])


def _resolve_inputs(
    tenant_id: str,
    counterparty_id: str,
    template_key: str,
    counterparty_repository: CounterpartyRepository,
    runtime_assets: TenantRuntimeAssetResolver,
    route_channel: str | None = None,
    route_request_ref: str | None = None,
) -> tuple[dict, dict, dict]:
    try:
        counterparty = counterparty_repository.get(tenant_id, counterparty_id)
    except CounterpartyError as exc:
        raise HTTPException(status_code=404, detail="客商不存在") from exc
    try:
        assets = runtime_assets.resolve_routed_rating(
            tenant_id, template_key, counterparty_id, route_channel, route_request_ref,
        ) if route_channel and route_request_ref else runtime_assets.resolve_rating(tenant_id, template_key)
    except (TenantAssetError, TenantRolloutError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return counterparty, assets["model"]["config"], assets


def _prepare_governed_input(tenant_id: str, counterparty: dict, template_key: str, config: dict, enterprise_data: EnterpriseDataRepository, observations: EnterpriseIndicatorObservationRepository) -> tuple[dict, dict]:
    prepared, readiness = prepare_rating_input(counterparty, enterprise_data.build_profile(tenant_id, counterparty["id"]), template_key, config)
    if not readiness["ready_for_scoring"]:
        missing = ", ".join(readiness["required_missing"][:5])
        raise HTTPException(status_code=422, detail=f"治理数据未达到模型计算门槛，缺少：{missing}")
    return apply_effective_observations(prepared, readiness, observations.effective(tenant_id, counterparty["id"]))


@router.get("/indicator-pool")
def list_indicator_pool(
    q: str | None = None,
    category: str | None = None,
    use_case: str | None = None,
    principal: Principal = Depends(require_permissions("models:view")),
) -> dict:
    pool = get_indicator_pool()
    indicators = list_enterprise_risk_indicators(query=q, category=category, use_case=use_case)
    return {
        "version": pool["version"],
        "name": pool["name"],
        "description": pool["description"],
        "score_scale": pool["score_scale"],
        "summary": pool["summary"],
        "filters": {"q": q, "category": category, "use_case": use_case},
        "result_count": len(indicators),
        "indicators": indicators,
    }


@router.get("/models")
def list_models(
    repository: DemoRepository = Depends(get_demo_repository),
    governance: ModelGovernanceRepository = Depends(get_model_governance_repository),
    principal: Principal = Depends(require_permissions("models:view")),
) -> list[dict]:
    return [
        {"key": item["key"], "name": config["name"], "version": config["version"]}
        for item in repository.list_templates()
        if (config := governance.get_config(repository, item["key"]))
    ]


@router.get("/models/{template_key}")
def get_model(
    template_key: str,
    repository: DemoRepository = Depends(get_demo_repository),
    governance: ModelGovernanceRepository = Depends(get_model_governance_repository),
    principal: Principal = Depends(require_permissions("models:view")),
) -> dict:
    config = governance.get_config(repository, template_key)
    if not config:
        raise HTTPException(status_code=404, detail="模型模板不存在")
    return {
        "key": template_key,
        "name": config["name"],
        "version": config["version"],
        "status": config.get("status", "active"),
        "industry_template": config.get("industry_template", template_key),
        "weights": config.get("weights", {}),
        "thresholds": config.get("thresholds", {}),
        "strong_rules": config.get("strong_rules", []),
        "strategy_mapping": config.get("strategy_mapping", []),
        "editable_indicators": get_editable_indicators(config),
        "indicator_selection": build_model_indicator_details(config),
        "risk_screening_policy": get_risk_screening_policy(config),
        "scorecard_binding": deepcopy(config.get("scorecard_binding")),
        "change_reason": config.get("change_reason", "继承基础模型配置"),
    }


@router.post("/ratings/run")
def run_rating(
    request: RatingRequest,
    counterparty_repository: CounterpartyRepository = Depends(get_counterparty_repository),
    runtime_assets: TenantRuntimeAssetResolver = Depends(get_tenant_runtime_asset_resolver),
    run_repository: RatingRunRepository = Depends(get_rating_run_repository),
    enterprise_data: EnterpriseDataRepository = Depends(get_enterprise_data_repository),
    observations: EnterpriseIndicatorObservationRepository = Depends(get_enterprise_indicator_observation_repository),
    principal: Principal = Depends(require_permissions("ratings:run")),
) -> dict:
    counterparty, config, assets = _resolve_inputs(
        principal.tenant_id, request.counterparty_id, request.template_key,
        counterparty_repository, runtime_assets, "rating", f"rating:{uuid4()}",
    )
    rating_input, readiness = _prepare_governed_input(principal.tenant_id, counterparty, request.template_key, config, enterprise_data, observations)
    started_ns = perf_counter_ns()
    try:
        result = runtime_assets.execute_rating(rating_input, assets)
    except TenantAssetError as exc:
        runtime_assets.complete_route(assets, None, max(1, round((perf_counter_ns() - started_ns) / 1_000_000)), exc.code)
        runtime_assets.repository.session.commit()
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    if not result.get("ok"):
        runtime_assets.complete_route(assets, result, max(1, round((perf_counter_ns() - started_ns) / 1_000_000)), "RATING_INPUT_INVALID")
        runtime_assets.repository.session.commit()
        raise HTTPException(status_code=422, detail=result.get("error", "评级计算失败"))
    runtime_assets.complete_route(assets, result, max(1, round((perf_counter_ns() - started_ns) / 1_000_000)))
    result["input_readiness"] = readiness_summary(readiness)
    result["enterprise_risk_screening"] = evaluate_indicator_pool(rating_input, config)
    asset_snapshot = runtime_assets.public_snapshot(assets)
    run = run_repository.save_run(principal.tenant_id, rating_input, request.template_key, config, result, actor=principal.name, asset_snapshot=asset_snapshot)
    return {**result, "rating_run_id": run["id"], "model_snapshot_id": run["model_snapshot_id"], "result_hash": run["result_hash"], "asset_resolution": asset_snapshot, "assets_hash": run["assets_hash"]}


@router.get("/ratings/runs")
def list_rating_runs(
    counterparty_id: str | None = None,
    repository: RatingRunRepository = Depends(get_rating_run_repository),
    principal: Principal = Depends(require_permissions("ratings:view")),
) -> list[dict]:
    return repository.list(principal.tenant_id, counterparty_id)


@router.get("/ratings/runs/{run_id}")
def get_rating_run(
    run_id: str,
    repository: RatingRunRepository = Depends(get_rating_run_repository),
    principal: Principal = Depends(require_permissions("ratings:view")),
) -> dict:
    run = repository.get(principal.tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="评级运行记录不存在")
    return run


@router.get("/ratings/batches")
def list_portfolio_rating_batches(
    template_key: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    repository: PortfolioRatingBatchRepository = Depends(get_portfolio_rating_batch_repository),
    principal: Principal = Depends(require_permissions("ratings:view")),
) -> list[dict]:
    return repository.list(principal.tenant_id, template_key, limit)


@router.get("/ratings/batches/{batch_id}")
def get_portfolio_rating_batch(
    batch_id: str,
    repository: PortfolioRatingBatchRepository = Depends(get_portfolio_rating_batch_repository),
    principal: Principal = Depends(require_permissions("ratings:view")),
) -> dict:
    batch = repository.get(principal.tenant_id, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="组合评级批次不存在")
    return batch


@router.post("/ratings/batches", status_code=201)
def create_portfolio_rating_batch(
    request: PortfolioRatingBatchCreate,
    counterparty_repository: CounterpartyRepository = Depends(get_counterparty_repository),
    runtime_assets: TenantRuntimeAssetResolver = Depends(get_tenant_runtime_asset_resolver),
    run_repository: RatingRunRepository = Depends(get_rating_run_repository),
    batch_repository: PortfolioRatingBatchRepository = Depends(get_portfolio_rating_batch_repository),
    enterprise_data: EnterpriseDataRepository = Depends(get_enterprise_data_repository),
    observations: EnterpriseIndicatorObservationRepository = Depends(get_enterprise_indicator_observation_repository),
    principal: Principal = Depends(require_permissions("ratings:run")),
) -> dict:
    try:
        base_assets = runtime_assets.resolve_rating(principal.tenant_id, request.template_key)
    except TenantAssetError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    counterparties = [
        item for item in counterparty_repository.list_legacy(principal.tenant_id)
        if request.counterparty_type == "all" or item["counterparty_type"] == request.counterparty_type
    ]
    if not counterparties:
        raise HTTPException(status_code=422, detail="当前组合范围没有可评级客商")

    prepared: list[tuple[dict, dict, dict, dict]] = []
    precheck_skipped: list[dict] = []
    for counterparty in counterparties:
        try:
            assets = runtime_assets.resolve_routed_rating(
                principal.tenant_id, request.template_key, counterparty["id"], "portfolio_rating",
                f"{request.batch_key}:{counterparty['id']}",
            )
            config = assets["model"]["config"]
            rating_input, _ = _prepare_governed_input(
                principal.tenant_id, counterparty, request.template_key, config, enterprise_data, observations
            )
            prepared.append((counterparty, rating_input, assets, runtime_assets.public_snapshot(assets)))
        except (KeyError, TypeError, ValueError, HTTPException) as exc:
            detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
            precheck_skipped.append({"counterparty_id": counterparty["id"], "counterparty_name": counterparty["name"], "reason": detail or "评级输入预检失败"})

    request_hash = content_hash({
        "template_key": request.template_key,
        "base_model_version": base_assets["model"]["version"],
        "base_asset_resolution_hash": base_assets["resolution_hash"],
        "counterparty_type": request.counterparty_type,
        "inputs": [{"counterparty_id": item[0]["id"], "input_hash": content_hash(item[1]), "asset_resolution_hash": item[2]["resolution_hash"]} for item in prepared],
        "precheck_skipped": precheck_skipped,
    })
    existing = batch_repository.get_by_key(principal.tenant_id, request.batch_key)
    if existing:
        if existing["request_hash"] != request_hash:
            raise HTTPException(status_code=409, detail="批次编号已存在，但模型、范围或输入快照已变化")
        return {**existing, "idempotent": True}

    results: list[dict] = []
    skipped = list(precheck_skipped)
    model_snapshot_id = None
    try:
        for counterparty, rating_input, assets, asset_snapshot in prepared:
            started_ns = perf_counter_ns()
            try:
                result = runtime_assets.execute_rating(rating_input, assets)
                if not result.get("ok"):
                    runtime_assets.complete_route(assets, result, max(1, round((perf_counter_ns() - started_ns) / 1_000_000)), "RATING_INPUT_INVALID")
                    skipped.append({"counterparty_id": counterparty["id"], "counterparty_name": counterparty["name"], "reason": result.get("error", "当前模型不适用")})
                    continue
                runtime_assets.complete_route(assets, result, max(1, round((perf_counter_ns() - started_ns) / 1_000_000)))
                run = run_repository.save_run(principal.tenant_id, rating_input, assets["model"]["key"], assets["model"]["config"], result, actor=principal.name, commit=False, asset_snapshot=asset_snapshot)
                model_snapshot_id = model_snapshot_id or run["model_snapshot_id"]
                results.append({**build_portfolio_result(result, run["id"]), "routing": asset_snapshot.get("routing")})
            except (KeyError, TypeError, ValueError) as exc:
                runtime_assets.complete_route(assets, None, max(1, round((perf_counter_ns() - started_ns) / 1_000_000)), "RATING_EXECUTION_FAILED")
                skipped.append({"counterparty_id": counterparty["id"], "counterparty_name": counterparty["name"], "reason": str(exc) or "模型计算失败"})
        summary = build_portfolio_summary(results, skipped, len(counterparties))
        result_hash = content_hash({"summary": summary, "results": results, "skipped": skipped})
        return batch_repository.create(
            principal.tenant_id,
            {
                "batch_key": request.batch_key,
                "request_hash": request_hash,
                "template_key": request.template_key,
                "model_version": base_assets["model"]["version"],
                "model_snapshot_id": model_snapshot_id,
                "scope_type": request.counterparty_type,
                "status": "completed" if not skipped else "completed_with_exceptions",
                "candidate_count": len(counterparties),
                "success_count": len(results),
                "skipped_count": len(skipped),
                "summary": summary,
                "results": results,
                "skipped": skipped,
                "result_hash": result_hash,
                "asset_snapshot": {
                    "schema_version": "tenant-runtime-assets-batch-v1",
                    "capture_status": "frozen_per_counterparty",
                    "items": [{"counterparty_id": item[0]["id"], "assets": item[3]} for item in prepared],
                    "resolution_hash": content_hash([{"counterparty_id": item[0]["id"], "resolution_hash": item[2]["resolution_hash"]} for item in prepared]),
                },
                "assets_hash": content_hash({"items": [{"counterparty_id": item[0]["id"], "assets": item[3]} for item in prepared], "resolution_hash": content_hash([{"counterparty_id": item[0]["id"], "resolution_hash": item[2]["resolution_hash"]} for item in prepared]), "schema_version": "tenant-runtime-assets-batch-v1", "capture_status": "frozen_per_counterparty"}),
            },
            principal.subject,
            principal.name,
        )
    except ConcurrentUpdateError as exc:
        batch_repository.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        batch_repository.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/ratings/trace")
def rating_trace(
    request: RatingRequest,
    counterparty_repository: CounterpartyRepository = Depends(get_counterparty_repository),
    runtime_assets: TenantRuntimeAssetResolver = Depends(get_tenant_runtime_asset_resolver),
    enterprise_data: EnterpriseDataRepository = Depends(get_enterprise_data_repository),
    observations: EnterpriseIndicatorObservationRepository = Depends(get_enterprise_indicator_observation_repository),
    principal: Principal = Depends(require_permissions("ratings:view")),
) -> dict:
    counterparty, config, assets = _resolve_inputs(
        principal.tenant_id, request.counterparty_id, request.template_key,
        counterparty_repository, runtime_assets,
    )
    rating_input, readiness = _prepare_governed_input(principal.tenant_id, counterparty, request.template_key, config, enterprise_data, observations)
    trace = build_score_calculation_trace(rating_input, config)
    if not trace.get("ok"):
        raise HTTPException(status_code=422, detail=trace.get("error", "计算链生成失败"))
    return {
        **trace,
        "input_readiness": readiness_summary(readiness),
        "enterprise_risk_screening": evaluate_indicator_pool(rating_input, config),
        "asset_resolution": runtime_assets.public_snapshot(assets),
    }


@router.post("/models/impact")
def model_impact(
    request: ModelImpactRequest,
    counterparty_repository: CounterpartyRepository = Depends(get_counterparty_repository),
    runtime_assets: TenantRuntimeAssetResolver = Depends(get_tenant_runtime_asset_resolver),
    enterprise_data: EnterpriseDataRepository = Depends(get_enterprise_data_repository),
    observations: EnterpriseIndicatorObservationRepository = Depends(get_enterprise_indicator_observation_repository),
    principal: Principal = Depends(require_permissions("ratings:run")),
) -> dict:
    counterparty, config, _ = _resolve_inputs(
        principal.tenant_id, request.counterparty_id, request.template_key,
        counterparty_repository, runtime_assets,
    )
    rating_input, _ = _prepare_governed_input(principal.tenant_id, counterparty, request.template_key, config, enterprise_data, observations)
    indicator = next((item for item in get_editable_indicators(config) if item["path"] == request.field_path), None)
    if not indicator:
        raise HTTPException(status_code=422, detail="指标不在可模拟治理清单中")
    if request.new_value < indicator["min"] or request.new_value > indicator["max"]:
        raise HTTPException(status_code=422, detail=f"模拟值超出允许范围：{indicator['min']:g} 至 {indicator['max']:g}")
    try:
        impact = simulate_indicator_change(rating_input, config, request.field_path, request.new_value)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"指标路径或模拟值无效：{exc}") from exc
    if not impact.get("ok"):
        raise HTTPException(status_code=422, detail=impact.get("error", "敏感性分析失败"))
    return impact
