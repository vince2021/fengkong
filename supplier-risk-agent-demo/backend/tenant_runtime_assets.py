"""Resolve executable model assets through the tenant catalog and freeze evidence."""
from __future__ import annotations

from copy import deepcopy
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from backend.db_models import ModelReleaseRecord
from backend.model_risk_policy_repository import ModelRiskPolicyError, ModelRiskPolicyRepository
from backend.repository import DemoRepository, _materialize_model_runtime_defaults, content_hash
from backend.tenant_asset_repository import TenantAssetError, TenantAssetRepository


class TenantRuntimeAssetResolver:
    """Build one executable asset graph using the catalog's resolution priority."""

    def __init__(self, repository: TenantAssetRepository, demo_repository: DemoRepository) -> None:
        self.repository = repository
        self.demo_repository = demo_repository

    def resolve_model(self, tenant_id: str, model_key: str, version: str | None = None, allow_historical: bool = False) -> dict:
        try:
            model = self.repository.resolve(tenant_id, "model", model_key, requested_version=version, allow_historical=allow_historical)
        except TenantAssetError as exc:
            if exc.code not in {"ASSET_NOT_FOUND", "ASSET_VERSION_NOT_FOUND"}:
                raise
            fallback = self.demo_repository.get_template(model_key)
            if fallback is None or (version is not None and str(fallback.get("version")) != str(version)):
                raise
            fallback = _materialize_model_runtime_defaults(fallback)
            model = self.repository._resolution(
                tenant_id=tenant_id,
                asset_type="model",
                asset_code=model_key,
                asset_name=str(fallback.get("name") or model_key),
                source_scope="implicit_platform_default",
                asset_id=str(uuid5(NAMESPACE_URL, f"hengxin:model:{model_key}:{fallback['version']}")),
                version=str(fallback["version"]),
                config_hash=content_hash(fallback),
                config=fallback,
                binding_id=None,
                override_id=None,
            )
        config = _materialize_model_runtime_defaults(deepcopy(model["config"]))
        config["version"] = model["version"]
        if not allow_historical:
            self._assert_in_service_model_risk(tenant_id, model)
        scorecard = None
        configured_binding = config.get("scorecard_binding")
        if isinstance(configured_binding, dict) and configured_binding.get("code"):
            resolved = self.repository.resolve(
                tenant_id,
                "scorecard",
                str(configured_binding["code"]),
                requested_version=str(configured_binding.get("version")) if allow_historical and configured_binding.get("version") is not None else None,
                allow_historical=allow_historical,
            )
            scorecard_config = deepcopy(resolved["config"])
            scorecard = self.runtime_asset(resolved, scorecard_config)
            config["scorecard_binding"] = {
                "scorecard_asset_id": resolved["asset_id"],
                "code": resolved["asset_code"],
                "version": resolved["version"],
                "config_hash": resolved["config_hash"],
                "config": scorecard_config,
                "source_scope": resolved["source_scope"],
                "binding_id": resolved.get("binding_id"),
                "override_id": resolved.get("override_id"),
                "resolution_hash": resolved["resolution_hash"],
            }
        return {
            **self.runtime_asset(model, config),
            "key": model["asset_code"],
            "config": config,
            "runtime_config_hash": content_hash(config),
            "scorecard": scorecard,
        }

    def _assert_in_service_model_risk(self, tenant_id: str, model: dict) -> None:
        """Block tenant runtime use only when a tenant policy governs this active release."""
        if model.get("source_scope") not in {"platform", "platform_pinned", "platform_inherited", "implicit_platform_default", "platform_execution_pin"}:
            return
        release = self.repository.session.scalar(select(ModelReleaseRecord).where(
            ModelReleaseRecord.id == model.get("asset_id"),
            ModelReleaseRecord.is_active.is_(True),
        ))
        if release is None or not release.source_change_id:
            return
        governance = ModelRiskPolicyRepository(self.repository.session)
        if governance.current_catalog(tenant_id)["source"] != "tenant_policy":
            return
        try:
            governance.in_service_release_status(tenant_id, release.id, required=True)
        except ModelRiskPolicyError as exc:
            raise TenantAssetError("MODEL_RISK_REACCEPTANCE_REQUIRED", exc.message, 409, {
                "tenant_id": tenant_id, "model_release_id": release.id,
            }) from exc

    def resolve_graph(
        self,
        tenant_id: str,
        model_key: str,
        model_version: str | None = None,
        pipeline_code: str | None = None,
        pipeline_version: int | str | None = None,
        rule_set_versions: dict[str, int | str] | None = None,
        rule_versions: dict[str, int | str] | None = None,
        allow_historical: bool = False,
    ) -> dict:
        model = self.resolve_model(tenant_id, model_key, model_version, allow_historical=allow_historical)
        return self._resolve_dependencies(
            tenant_id,
            model,
            pipeline_code=pipeline_code,
            pipeline_version=pipeline_version,
            rule_set_versions=rule_set_versions,
            rule_versions=rule_versions,
            allow_historical=allow_historical,
        )

    def resolve_config_graph(
        self,
        tenant_id: str,
        model_key: str,
        model_config: dict,
        model_version: str,
        *,
        source_scope: str,
        asset_id: str,
        pipeline_code: str | None = None,
        pipeline_version: int | str | None = None,
        allow_historical: bool = False,
    ) -> dict:
        """Resolve governed candidate dependencies without publishing the model first."""
        config = _materialize_model_runtime_defaults(deepcopy(model_config))
        config["version"] = model_version
        scorecard = None
        configured_binding = config.get("scorecard_binding")
        if isinstance(configured_binding, dict) and configured_binding.get("code"):
            resolved = self.repository.resolve(
                tenant_id,
                "scorecard",
                str(configured_binding["code"]),
                requested_version=(
                    str(configured_binding.get("version"))
                    if allow_historical and configured_binding.get("version") is not None
                    else None
                ),
                allow_historical=allow_historical,
            )
            scorecard_config = deepcopy(resolved["config"])
            scorecard = self.runtime_asset(resolved, scorecard_config)
            config["scorecard_binding"] = {
                "scorecard_asset_id": resolved["asset_id"],
                "code": resolved["asset_code"],
                "version": resolved["version"],
                "config_hash": resolved["config_hash"],
                "config": scorecard_config,
                "source_scope": resolved["source_scope"],
                "binding_id": resolved.get("binding_id"),
                "override_id": resolved.get("override_id"),
                "resolution_hash": resolved["resolution_hash"],
            }
        config_hash = content_hash(model_config)
        model = {
            "asset_type": "model",
            "key": model_key,
            "code": model_key,
            "version": model_version,
            "config_hash": config_hash,
            "runtime_config_hash": content_hash(config),
            "source_scope": source_scope,
            "asset_id": asset_id,
            "binding_id": None,
            "override_id": None,
            "config": config,
            "definition": config,
            "scorecard": scorecard,
        }
        model["resolution_hash"] = content_hash({
            "tenant_id": tenant_id,
            "asset_type": "model",
            "asset_code": model_key,
            "asset_id": asset_id,
            "version": model_version,
            "config_hash": config_hash,
            "runtime_config_hash": model["runtime_config_hash"],
            "source_scope": source_scope,
            "scorecard_resolution_hash": (scorecard or {}).get("resolution_hash"),
        })
        resolved_pipeline_code = str(
            pipeline_code or config.get("decision_pipeline_code") or ""
        ).strip().upper()
        if not resolved_pipeline_code or resolved_pipeline_code == "LEGACY-SCORECARD":
            payload = {
                "model": model,
                "scorecard": scorecard,
                "pipeline": None,
                "rule_sets": [],
                "rules": [],
                "degraded_reason": "legacy_runtime_assets_unavailable",
            }
            payload["resolution_hash"] = content_hash({
                "model": model["resolution_hash"],
                "scorecard": (scorecard or {}).get("resolution_hash"),
                "pipeline": None,
            })
            return payload
        return self._resolve_dependencies(
            tenant_id,
            model,
            pipeline_code=pipeline_code,
            pipeline_version=pipeline_version,
            allow_historical=allow_historical,
        )

    def _resolve_dependencies(
        self,
        tenant_id: str,
        model: dict,
        *,
        pipeline_code: str | None = None,
        pipeline_version: int | str | None = None,
        rule_set_versions: dict[str, int | str] | None = None,
        rule_versions: dict[str, int | str] | None = None,
        allow_historical: bool = False,
    ) -> dict:
        config = deepcopy(model["config"])
        resolved_pipeline_code = str(pipeline_code or config.get("decision_pipeline_code") or "").strip().upper()
        if not resolved_pipeline_code or resolved_pipeline_code == "LEGACY-SCORECARD":
            raise TenantAssetError("ASSET_VERSION_NOT_FOUND", "模型未配置可执行决策管线", 404)
        pipeline = self.repository.resolve(
            tenant_id,
            "pipeline",
            resolved_pipeline_code,
            requested_version=str(pipeline_version) if pipeline_version is not None else None,
            allow_historical=allow_historical,
        )
        pipeline_config = deepcopy(pipeline["config"])
        stages = pipeline_config.get("stages_json") or []
        requested_rule_sets = {str(k).strip().upper(): v for k, v in (rule_set_versions or {}).items()}
        requested_rules = {str(k).strip().upper(): v for k, v in (rule_versions or {}).items()}
        rule_set_codes = [
            str(stage.get("rule_set_code")).strip().upper()
            for stage in stages
            if isinstance(stage, dict) and stage.get("rule_set_code")
        ]
        unused_rule_sets = sorted(set(requested_rule_sets) - set(rule_set_codes))
        if unused_rule_sets:
            raise TenantAssetError("DECISION_INPUT_INVALID", "规则集版本覆盖不属于所选管线", 422, {"unused_rule_set_codes": unused_rule_sets})

        rule_sets: list[dict] = []
        rule_codes: list[str] = []
        for code in rule_set_codes:
            resolved = self.repository.resolve(
                tenant_id,
                "rule_set",
                code,
                requested_version=str(requested_rule_sets[code]) if code in requested_rule_sets else None,
                allow_historical=allow_historical,
            )
            definition = deepcopy(resolved["config"])
            rule_sets.append(self.runtime_asset(resolved, definition))
            rule_codes.extend(str(item).strip().upper() for item in definition.get("rule_codes", []))

        ordered_rule_codes = list(dict.fromkeys(rule_codes))
        unused_rules = sorted(set(requested_rules) - set(ordered_rule_codes))
        if unused_rules:
            raise TenantAssetError("DECISION_INPUT_INVALID", "规则版本覆盖不属于所选规则集", 422, {"unused_rule_codes": unused_rules})

        rules: list[dict] = []
        for code in ordered_rule_codes:
            resolved = self.repository.resolve(
                tenant_id,
                "rule",
                code,
                requested_version=str(requested_rules[code]) if code in requested_rules else None,
                allow_historical=allow_historical,
            )
            rules.append(self.runtime_asset(resolved, deepcopy(resolved["config"])))

        return {
            "model": model,
            "scorecard": deepcopy(model.get("scorecard")),
            "pipeline": {
                **self.runtime_asset(pipeline, pipeline_config),
                "code": pipeline["asset_code"],
                "definition": pipeline_config,
            },
            "rule_sets": rule_sets,
            "rules": rules,
            "resolution_hash": self._graph_hash(model, pipeline, rule_sets, rules),
        }

    def resolve_rating(self, tenant_id: str, model_key: str, model_version: str | None = None, allow_historical: bool = False) -> dict:
        model = self.resolve_model(tenant_id, model_key, model_version, allow_historical=allow_historical)
        pipeline_code = str(model["config"].get("decision_pipeline_code") or "").strip().upper()
        if pipeline_code and pipeline_code != "LEGACY-SCORECARD":
            try:
                return self.resolve_graph(tenant_id, model_key, model_version=model_version, allow_historical=allow_historical)
            except TenantAssetError as exc:
                if model["source_scope"] not in {"implicit_platform_default", "platform_execution_pin"} or exc.code != "ASSET_NOT_FOUND":
                    raise
        payload = {
            "model": model,
            "scorecard": deepcopy(model.get("scorecard")),
            "pipeline": None,
            "rule_sets": [],
            "rules": [],
            "degraded_reason": "legacy_runtime_assets_unavailable" if pipeline_code else None,
        }
        payload["resolution_hash"] = content_hash({
            "model": model["resolution_hash"],
            "scorecard": (model.get("scorecard") or {}).get("resolution_hash"),
            "pipeline": None,
        })
        return payload

    def resolve_routed_rating(
        self, tenant_id: str, model_key: str, routing_key: str, channel: str, request_ref: str,
    ) -> dict:
        from backend.tenant_rollout_repository import TenantRolloutRepository

        routed = TenantRolloutRepository(self.repository.session, self.demo_repository).route(
            tenant_id, model_key, routing_key, channel, request_ref,
        )
        return routed if routed is not None else self.resolve_rating(tenant_id, model_key)

    def resolve_routed_graph(
        self, tenant_id: str, model_key: str, routing_key: str, channel: str, request_ref: str,
        *, model_version: str | None = None, pipeline_code: str | None = None,
        pipeline_version: int | str | None = None, rule_set_versions: dict[str, int | str] | None = None,
        rule_versions: dict[str, int | str] | None = None,
    ) -> dict:
        from backend.tenant_rollout_repository import TenantRolloutRepository

        explicit = any((model_version is not None, pipeline_version is not None, rule_set_versions, rule_versions))
        routed = TenantRolloutRepository(self.repository.session, self.demo_repository).route(
            tenant_id, model_key, routing_key, channel, request_ref, explicit_selection=bool(explicit),
            requested_pipeline_code=pipeline_code,
        )
        if routed is not None:
            return routed
        return self.resolve_graph(
            tenant_id, model_key, model_version=model_version, pipeline_code=pipeline_code,
            pipeline_version=pipeline_version, rule_set_versions=rule_set_versions, rule_versions=rule_versions,
        )

    def complete_route(self, assets: dict, result: dict | None, elapsed_ms: int, error_code: str | None = None) -> dict | None:
        from backend.tenant_rollout_repository import TenantRolloutRepository

        return TenantRolloutRepository(self.repository.session, self.demo_repository).complete_route(
            assets, result, elapsed_ms, error_code,
        )

    @staticmethod
    def execute_rating(counterparty: dict, assets: dict) -> dict:
        pipeline = assets.get("pipeline")
        config = deepcopy(assets["model"]["config"])
        if pipeline is None:
            from rating.scorecard import rate_counterparty

            return rate_counterparty(counterparty, config)
        from rating.decision_pipeline import run_decision_pipeline_sandbox
        from rating.scorecard import _decorate_pipeline_result

        runtime = {"counterparty": deepcopy(counterparty), "config": config}
        result = run_decision_pipeline_sandbox(
            pipeline["definition"],
            {item["code"]: item["definition"] for item in assets["rule_sets"]},
            {item["code"]: item["definition"] for item in assets["rules"]},
            runtime,
        )
        if result is None:
            raise TenantAssetError("ASSET_DEPENDENCY_INVALID", "租户解析后的决策管线依赖无法执行", 409)
        return _decorate_pipeline_result(result, runtime)

    @staticmethod
    def public_asset(item: dict | None) -> dict | None:
        if item is None:
            return None
        result = {
            key: deepcopy(item.get(key))
            for key in (
                "asset_type", "key", "code", "version", "config_hash", "runtime_config_hash",
                "source_scope", "asset_id", "binding_id", "override_id", "resolution_hash",
            )
            if item.get(key) is not None
        }
        if item.get("asset_type") != "model" and str(result.get("version", "")).isdigit():
            result["version"] = int(result["version"])
        return result

    @staticmethod
    def public_snapshot(assets: dict) -> dict:
        public = TenantRuntimeAssetResolver.public_asset

        result = {
            "model": public(assets["model"]),
            "scorecard": public(assets.get("scorecard")),
            "pipeline": public(assets.get("pipeline")),
            "rule_sets": [public(item) for item in assets.get("rule_sets", [])],
            "rules": [public(item) for item in assets.get("rules", [])],
            "resolution_hash": assets.get("resolution_hash"),
            "degraded_reason": assets.get("degraded_reason"),
        }
        if assets.get("routing"):
            result["routing"] = deepcopy(assets["routing"])
        return result

    @staticmethod
    def runtime_asset(resolved: dict, config: dict) -> dict:
        return {
            "asset_type": resolved["asset_type"],
            "code": resolved["asset_code"],
            "version": resolved["version"],
            "config_hash": resolved["config_hash"],
            "source_scope": resolved["source_scope"],
            "asset_id": resolved["asset_id"],
            "binding_id": resolved.get("binding_id"),
            "override_id": resolved.get("override_id"),
            "resolution_hash": resolved["resolution_hash"],
            "config": config,
            "definition": config,
        }

    @staticmethod
    def _graph_hash(model: dict, pipeline: dict, rule_sets: list[dict], rules: list[dict]) -> str:
        return content_hash({
            "model": model["resolution_hash"],
            "scorecard": (model.get("scorecard") or {}).get("resolution_hash"),
            "pipeline": pipeline["resolution_hash"],
            "rule_sets": [item["resolution_hash"] for item in rule_sets],
            "rules": [item["resolution_hash"] for item in rules],
        })
