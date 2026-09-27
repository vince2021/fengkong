"""Synchronous, version-pinned Decision API execution and evidence storage."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from time import perf_counter_ns
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.counterparty_repository import CounterpartyError, CounterpartyRepository
from backend.db_models import (
    DecisionExecutionRecord,
    DecisionPipelineDefinition,
    ModelReleaseRecord,
    TenantAssetBindingRecord,
)
from backend.repository import AuditRepository, DemoRepository, ModelGovernanceRepository, content_hash
from backend.schemas import DecisionExecuteRequest
from backend.security import Principal
from backend.tenant_asset_repository import TenantAssetError, TenantAssetRepository
from backend.tenant_runtime_assets import TenantRuntimeAssetResolver
from backend.tenant_rollout_repository import TenantRolloutError, TenantRolloutRepository
from rating.decision_pipeline import run_decision_pipeline_sandbox


class DecisionApiError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class DecisionExecutionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit = AuditRepository(session)

    def get_by_request_id(self, tenant_id: str, request_id: str) -> DecisionExecutionRecord | None:
        return self.session.scalars(
            select(DecisionExecutionRecord).where(
                DecisionExecutionRecord.tenant_id == tenant_id,
                DecisionExecutionRecord.request_id == request_id,
            )
        ).first()

    def save(self, payload: dict, principal: Principal) -> DecisionExecutionRecord:
        record = DecisionExecutionRecord(
            id=str(uuid4()),
            tenant_id=principal.tenant_id,
            client_id=principal.client_id,
            request_id=payload["request_id"],
            request_hash=payload["request_hash"],
            trace_id=payload["trace_id"],
            counterparty_id=payload["counterparty_id"],
            request_json=deepcopy(payload["request"]),
            normalized_input_json=deepcopy(payload["input"]),
            input_hash=payload["input_hash"],
            model_key=payload["model_key"],
            model_version=payload["model_version"],
            model_config_hash=payload["model_config_hash"],
            pipeline_code=payload["pipeline_code"],
            pipeline_version=payload["pipeline_version"],
            pipeline_hash=payload["pipeline_hash"],
            asset_snapshot_json=deepcopy(payload["assets"]),
            assets_hash=payload["assets_hash"],
            result_json=deepcopy(payload["result"]),
            result_hash=payload["result_hash"],
            trace_json=deepcopy(payload["trace"]),
            trace_hash=payload["trace_hash"],
            evidence_hash=payload["evidence_hash"],
            elapsed_ms=payload["elapsed_ms"],
            created_by=principal.subject,
            created_by_name=principal.name,
        )
        self.session.add(record)
        try:
            self.session.flush()
            self.audit.append(
                "decision_execution",
                f"{record.tenant_id}:{record.request_id}",
                "decision_execution_completed",
                principal.subject,
                {
                    "tenant_id": record.tenant_id,
                    "client_id": record.client_id,
                    "trace_id": record.trace_id,
                    "counterparty_id": record.counterparty_id,
                    "model_key": record.model_key,
                    "model_version": record.model_version,
                    "pipeline_code": record.pipeline_code,
                    "pipeline_version": record.pipeline_version,
                    "request_hash": record.request_hash,
                    "input_hash": record.input_hash,
                    "assets_hash": record.assets_hash,
                    "result_hash": record.result_hash,
                    "trace_hash": record.trace_hash,
                    "evidence_hash": record.evidence_hash,
                },
            )
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            existing = self.get_by_request_id(record.tenant_id, record.request_id)
            if existing and existing.request_hash == record.request_hash:
                return existing
            raise DecisionApiError(
                "IDEMPOTENCY_CONFLICT",
                "request_id 已被不同请求内容占用",
                409,
                {"tenant_id": record.tenant_id, "request_id": record.request_id},
            )
        self.session.refresh(record)
        return record


def execute_decision(
    request: DecisionExecuteRequest,
    session: Session,
    demo_repository: DemoRepository,
    counterparty_repository: CounterpartyRepository,
    governance: ModelGovernanceRepository,
    principal: Principal,
    frozen_assets: dict | None = None,
) -> tuple[dict, bool]:
    canonical_request = request.model_dump(mode="json", exclude_none=False)
    request_hash = content_hash(canonical_request)
    repository = DecisionExecutionRepository(session)
    existing = repository.get_by_request_id(principal.tenant_id, request.request_id)
    if existing:
        if existing.request_hash != request_hash:
            raise DecisionApiError(
                "IDEMPOTENCY_CONFLICT",
                "相同 request_id 的请求内容发生变化，请使用新的 request_id",
                409,
                {
                    "tenant_id": principal.tenant_id,
                    "request_id": request.request_id,
                    "original_request_hash": existing.request_hash,
                    "incoming_request_hash": request_hash,
                },
            )
        return serialize_execution(existing, idempotent=True), True

    trace_id = str(uuid4())
    started_at = datetime.now(timezone.utc)
    started_ns = perf_counter_ns()
    counterparty, input_source = _resolve_input(request, counterparty_repository, principal)
    assets = deepcopy(frozen_assets) if frozen_assets is not None else _resolve_assets(
        request, session, demo_repository, governance, principal.tenant_id, counterparty["id"]
    )
    input_hash = content_hash(counterparty)

    runtime = {"counterparty": deepcopy(counterparty), "config": deepcopy(assets["model"]["config"])}
    result = run_decision_pipeline_sandbox(
        assets["pipeline"]["definition"],
        {item["code"]: item["definition"] for item in assets["rule_sets"]},
        {item["code"]: item["definition"] for item in assets["rules"]},
        runtime,
    )
    if result is None:
        TenantRolloutRepository(session, demo_repository).complete_route(
            assets, None, max(1, round((perf_counter_ns() - started_ns) / 1_000_000)), "DECISION_EXECUTION_FAILED",
        )
        session.commit()
        raise DecisionApiError(
            "DECISION_EXECUTION_FAILED",
            "固定版本决策管线无法完成执行，请检查阶段与规则依赖",
            500,
            {"trace_id": trace_id},
        )
    if not result.get("ok"):
        TenantRolloutRepository(session, demo_repository).complete_route(
            assets, result, max(1, round((perf_counter_ns() - started_ns) / 1_000_000)), "DECISION_INPUT_INVALID",
        )
        session.commit()
        raise DecisionApiError(
            "DECISION_INPUT_INVALID",
            str(result.get("error") or "输入数据不满足模型计算要求"),
            422,
            {"trace_id": trace_id, "counterparty_id": counterparty["id"]},
        )

    completed_at = datetime.now(timezone.utc)
    elapsed_ms = max(1, round((perf_counter_ns() - started_ns) / 1_000_000))
    TenantRolloutRepository(session, demo_repository).complete_route(assets, result, elapsed_ms)
    result_hash = content_hash(result)
    assets_hash = content_hash(assets)
    trace = {
        "trace_id": trace_id,
        "status": "completed",
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "elapsed_ms": elapsed_ms,
        "request": {
            "tenant_id": principal.tenant_id,
            "client_id": principal.client_id,
            "request_id": request.request_id,
            "source_system": request.metadata.source_system,
            "scenario": request.metadata.scenario,
        },
        "input": {
            "source": input_source,
            "counterparty_id": counterparty["id"],
            "input_hash": input_hash,
        },
        "assets": _public_assets(assets),
        "pipeline": deepcopy(runtime.get("pipeline_trace", {})),
        "output": {
            "result_hash": result_hash,
            "rating": result.get("rating"),
            "access_strategy": result.get("access_strategy"),
            "final_admission": result.get("final_admission"),
        },
    }
    trace_hash = content_hash(trace)
    evidence_hash = content_hash(
        {
            "request_hash": request_hash,
            "input_hash": input_hash,
            "assets_hash": assets_hash,
            "result_hash": result_hash,
            "trace_hash": trace_hash,
        }
    )
    model = assets["model"]
    pipeline = assets["pipeline"]
    record = repository.save(
        {
            "request_id": request.request_id,
            "request_hash": request_hash,
            "trace_id": trace_id,
            "counterparty_id": counterparty["id"],
            "request": canonical_request,
            "input": counterparty,
            "input_hash": input_hash,
            "model_key": model["key"],
            "model_version": model["version"],
            "model_config_hash": model["runtime_config_hash"],
            "pipeline_code": pipeline["code"],
            "pipeline_version": int(pipeline["definition"]["version"]),
            "pipeline_hash": pipeline["config_hash"],
            "assets": assets,
            "assets_hash": assets_hash,
            "result": result,
            "result_hash": result_hash,
            "trace": trace,
            "trace_hash": trace_hash,
            "evidence_hash": evidence_hash,
            "elapsed_ms": elapsed_ms,
        },
        principal,
    )
    idempotent = record.trace_id != trace_id
    return serialize_execution(record, idempotent=idempotent), idempotent


def get_decision_contract(session: Session, demo_repository: DemoRepository, tenant_id: str) -> dict:
    repository = TenantAssetRepository(session)
    resolver = TenantRuntimeAssetResolver(repository, demo_repository)
    unavailable_assets: list[dict] = []

    model_keys = {str(item["key"]).strip() for item in demo_repository.list_templates()}
    model_keys.update(session.scalars(select(ModelReleaseRecord.template_key).distinct()).all())
    model_keys.update(
        session.scalars(
            select(TenantAssetBindingRecord.asset_code).where(
                TenantAssetBindingRecord.tenant_id == tenant_id,
                TenantAssetBindingRecord.asset_type == "model",
            )
        ).all()
    )
    models = []
    for model_key in sorted(model_keys):
        try:
            model = resolver.resolve_model(tenant_id, model_key)
        except TenantAssetError as exc:
            unavailable_assets.append(_contract_asset_error("model", model_key, exc))
            continue
        config = model["config"]
        public = resolver.public_asset(model) or {}
        version = {
            **public,
            "version": model["version"],
            "name": config.get("name", model_key),
            "config_hash": model["config_hash"],
            "runtime_config_hash": model["runtime_config_hash"],
            "pipeline_code": config.get("decision_pipeline_code"),
            "scorecard": resolver.public_asset(model.get("scorecard")),
        }
        models.append(
            {
                "key": model_key,
                "name": version["name"],
                "active_version": model["version"],
                "source_scope": model["source_scope"],
                "resolution_hash": model["resolution_hash"],
                "versions": [version],
            }
        )

    pipeline_codes = set(
        session.scalars(
            select(DecisionPipelineDefinition.code)
            .where(DecisionPipelineDefinition.status == "published")
            .distinct()
        ).all()
    )
    pipeline_codes.update(
        session.scalars(
            select(TenantAssetBindingRecord.asset_code).where(
                TenantAssetBindingRecord.tenant_id == tenant_id,
                TenantAssetBindingRecord.asset_type == "pipeline",
            )
        ).all()
    )
    pipelines = []
    for pipeline_code in sorted(pipeline_codes):
        try:
            resolved = repository.resolve(tenant_id, "pipeline", pipeline_code)
        except TenantAssetError as exc:
            unavailable_assets.append(_contract_asset_error("pipeline", pipeline_code, exc))
            continue
        definition = deepcopy(resolved["config"])
        stages = definition.get("stages_json") or []
        public = resolver.public_asset(resolver.runtime_asset(resolved, definition)) or {}
        pipelines.append(
            {
                **public,
                "code": resolved["asset_code"],
                "name": definition.get("name", resolved["asset_name"]),
                "version": public["version"],
                "is_active": True,
                "stages": stages,
                "rule_set_codes": [
                    str(stage.get("rule_set_code"))
                    for stage in stages
                    if isinstance(stage, dict) and stage.get("rule_set_code")
                ],
            }
        )
    return {
        "contract_version": "2026-09-15",
        "tenant_id": tenant_id,
        "endpoint": "POST /api/v1/decisions",
        "idempotency": "相同 request_id 与相同请求哈希返回原结果；请求内容变化返回 409 IDEMPOTENCY_CONFLICT。",
        "version_policy": "只允许使用当前租户目录解析版本；省略版本时由目录解析，显式版本不一致返回 ASSET_VERSION_NOT_ALLOWED。",
        "input_modes": ["counterparty_id", "input"],
        "error_codes": [
            "DECISION_REQUEST_INVALID",
            "DECISION_INPUT_INVALID",
            "ASSET_VERSION_NOT_FOUND",
            "ASSET_VERSION_NOT_ALLOWED",
            "IDEMPOTENCY_CONFLICT",
            "DECISION_NOT_FOUND",
            "DECISION_EXECUTION_FAILED",
        ],
        "models": models,
        "pipelines": pipelines,
        "unavailable_assets": unavailable_assets,
    }


def _contract_asset_error(asset_type: str, asset_code: str, error: TenantAssetError) -> dict:
    return {
        "asset_type": asset_type,
        "asset_code": asset_code,
        "code": error.code,
        "message": error.message,
    }


def get_sandbox_package(demo_repository: DemoRepository, contract: dict | None = None) -> dict:
    samples = demo_repository.list_counterparties()[:6]
    contract_models = (contract or {}).get("models") or []
    model = next((item for item in contract_models if item["key"] == "general"), None)
    if model is None and contract_models:
        model = contract_models[0]
    model_version = (model or {}).get("versions", [{}])[0]
    contract_pipelines = (contract or {}).get("pipelines") or []
    pipeline = next(
        (item for item in contract_pipelines if item["code"] == model_version.get("pipeline_code")),
        contract_pipelines[0] if contract_pipelines else None,
    )
    return {
        "environment": "sandbox",
        "production_credentials_exposed": False,
        "notice": "沙箱仅用于字段映射、版本锁定和联调验证，不连接客户生产密钥。",
        "samples": [
            {
                "counterparty_id": item["id"],
                "name": item["name"],
                "counterparty_type": item["counterparty_type"],
                "current_rating": item.get("current_rating"),
                "input": item,
            }
            for item in samples
        ],
        "request_example": {
            "request_id": "ERP-DECISION-20260903-001",
            "counterparty_id": samples[0]["id"] if samples else None,
            "input": None,
            "assets": {
                "model_key": (model or {}).get("key", "general"),
                "model_version": model_version.get("version", "MCR-20260711-001"),
                "pipeline_code": (pipeline or {}).get("code", "PIPELINE-GENERAL"),
                "pipeline_version": (pipeline or {}).get("version", 1),
                "rule_set_versions": {},
                "rule_versions": {},
            },
            "metadata": {"source_system": "ERP", "scenario": "supplier_admission"},
        },
    }


def serialize_execution(record: DecisionExecutionRecord, idempotent: bool = False) -> dict:
    return {
        "tenant_id": record.tenant_id,
        "client_id": record.client_id,
        "request_id": record.request_id,
        "trace_id": record.trace_id,
        "status": "completed",
        "idempotent": idempotent,
        "counterparty_id": record.counterparty_id,
        "decision": deepcopy(record.result_json),
        "assets": _public_assets(record.asset_snapshot_json),
        "trace": deepcopy(record.trace_json),
        "evidence": {
            "request_hash": record.request_hash,
            "input_hash": record.input_hash,
            "assets_hash": record.assets_hash,
            "result_hash": record.result_hash,
            "trace_hash": record.trace_hash,
            "evidence_hash": record.evidence_hash,
        },
        "elapsed_ms": record.elapsed_ms,
        "created_by": record.created_by,
        "created_by_name": record.created_by_name,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


def _resolve_input(
    request: DecisionExecuteRequest,
    counterparty_repository: CounterpartyRepository,
    principal: Principal,
) -> tuple[dict, str]:
    if request.counterparty_id:
        try:
            counterparty = counterparty_repository.get(principal.tenant_id, request.counterparty_id)
        except CounterpartyError as exc:
            raise DecisionApiError(
                "DECISION_INPUT_INVALID",
                "指定的租户客商不存在或不可用",
                422,
                {"counterparty_id": request.counterparty_id},
            ) from exc
        return counterparty, "platform_counterparty"

    counterparty = deepcopy(request.input or {})
    required = [key for key in ("id", "name", "counterparty_type") if not counterparty.get(key)]
    if required:
        raise DecisionApiError(
            "DECISION_INPUT_INVALID",
            "规范化企业输入缺少必填字段",
            422,
            {"missing_fields": required},
        )
    if counterparty["counterparty_type"] not in {"supplier", "customer"}:
        raise DecisionApiError(
            "DECISION_INPUT_INVALID",
            "counterparty_type 仅支持 supplier 或 customer",
            422,
            {"field": "counterparty_type"},
        )
    for section in ("external", "internal", "financial"):
        value = counterparty.setdefault(section, {})
        if not isinstance(value, dict):
            raise DecisionApiError(
                "DECISION_INPUT_INVALID",
                f"{section} 必须是 JSON 对象",
                422,
                {"field": section},
            )
    return counterparty, "inline_input"


def _resolve_assets(
    request: DecisionExecuteRequest,
    session: Session,
    demo_repository: DemoRepository,
    governance: ModelGovernanceRepository,
    tenant_id: str,
    routing_key: str,
) -> dict:
    del governance
    selection = request.assets
    try:
        return TenantRuntimeAssetResolver(
            TenantAssetRepository(session), demo_repository
        ).resolve_routed_graph(
            tenant_id, selection.model_key.strip(), routing_key, "decision_api", request.request_id,
            model_version=selection.model_version,
            pipeline_code=selection.pipeline_code,
            pipeline_version=selection.pipeline_version,
            rule_set_versions=selection.rule_set_versions,
            rule_versions=selection.rule_versions,
        )
    except (TenantAssetError, TenantRolloutError) as exc:
        raise DecisionApiError(exc.code, exc.message, exc.status_code, exc.details) from exc


def _public_assets(assets: dict) -> dict:
    return TenantRuntimeAssetResolver.public_snapshot(assets)
