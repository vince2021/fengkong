"""Tenant-scoped catalog, subscriptions, override workflow, and asset resolution."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import os
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from backend.db_models import (
    DecisionPipelineDefinition,
    IndicatorDefinition,
    ModelReleaseRecord,
    RuleDefinition,
    RuleSetDefinition,
    ScorecardDefinition,
    TenantAssetBindingRecord,
    TenantAssetOverrideRecord,
    TenantEntitlementRecord,
)
from backend.repository import AuditRepository, content_hash

if TYPE_CHECKING:
    from backend.security import Principal


ASSET_TYPES = ("indicator", "scorecard", "model", "rule", "rule_set", "pipeline")


class TenantAssetError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class TenantAssetRepository:
    """Resolve a tenant asset without copying or mutating platform baselines."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit = AuditRepository(session)
        self._entitlement_cache: dict[str, dict] = {}

    def list_catalog(self, principal: "Principal", asset_type: str | None = None) -> dict:
        if asset_type is not None:
            self._ensure_type(asset_type)
            types = (asset_type,)
        else:
            types = ASSET_TYPES
        identities: set[tuple[str, str]] = set()
        for current_type in types:
            identities.update((current_type, code) for code in self._platform_codes(current_type))
        bindings = self.session.scalars(
            select(TenantAssetBindingRecord).where(
                TenantAssetBindingRecord.tenant_id == principal.tenant_id,
                TenantAssetBindingRecord.asset_type.in_(types),
            )
        ).all()
        identities.update((item.asset_type, item.asset_code) for item in bindings)
        binding_map = {(item.asset_type, item.asset_code): item for item in bindings}

        overrides = self.session.scalars(
            select(TenantAssetOverrideRecord)
            .where(
                TenantAssetOverrideRecord.tenant_id == principal.tenant_id,
                TenantAssetOverrideRecord.asset_type.in_(types),
            )
            .order_by(TenantAssetOverrideRecord.version.desc())
        ).all()
        override_map: dict[tuple[str, str], list[TenantAssetOverrideRecord]] = {}
        for item in overrides:
            override_map.setdefault((item.asset_type, item.asset_code), []).append(item)

        rows: list[dict] = []
        for current_type, code in sorted(identities, key=lambda item: (ASSET_TYPES.index(item[0]), item[1])):
            platform_assets = self._platform_versions(current_type, code)
            active = next((item for item in platform_assets if item["is_active"]), None)
            try:
                resolution = self.resolve(principal.tenant_id, current_type, code)
                resolution_error = None
                name = resolution["asset_name"]
            except TenantAssetError as exc:
                resolution = None
                resolution_error = {"code": exc.code, "message": exc.message}
                name = platform_assets[0]["name"] if platform_assets else code
            rows.append({
                "asset_type": current_type,
                "asset_code": code,
                "asset_name": name,
                "available_versions": [item["version"] for item in platform_assets],
                "active_platform_version": active["version"] if active else None,
                "binding": self._binding_view(binding_map[(current_type, code)]) if (current_type, code) in binding_map else None,
                "overrides": [self._override_view(item) for item in override_map.get((current_type, code), [])],
                "resolution": resolution,
                "resolution_error": resolution_error,
            })

        return {
            "tenant_id": principal.tenant_id,
            "entitlement": {
                key: value for key, value in self._entitlement_context(principal.tenant_id).items()
                if key != "record"
            },
            "summary": {
                "asset_count": len(rows),
                "explicit_binding_count": len(bindings),
                "pinned_count": sum(item.binding_mode == "pinned" for item in bindings),
                "suspended_count": sum(item.status == "suspended" for item in bindings),
                "active_override_count": sum(item.is_active for item in overrides),
                "pending_review_count": sum(item.status == "pending_review" for item in overrides),
                "implicit_default_count": sum(
                    row["resolution"] is not None and row["resolution"]["source_scope"] == "implicit_platform_default"
                    for row in rows
                ),
            },
            "items": rows,
        }

    def resolve(
        self,
        tenant_id: str,
        asset_type: str,
        asset_code: str,
        requested_version: str | None = None,
        allow_historical: bool = False,
    ) -> dict:
        asset_type = self._ensure_type(asset_type)
        asset_code = self._normalize_code(asset_type, asset_code)
        self._require_entitlement(tenant_id, asset_type, asset_code)
        binding = self._binding(tenant_id, asset_type, asset_code)
        if binding is not None and binding.status == "suspended":
            raise TenantAssetError("ASSET_BINDING_SUSPENDED", "该租户资产目录已暂停，不能解析运行版本", 409)

        if allow_historical and requested_version is not None and not str(requested_version).startswith("tenant-v"):
            historical = self._platform_asset(asset_type, asset_code, str(requested_version))
            if historical is not None:
                return self._resolution(
                    tenant_id=tenant_id,
                    asset_type=asset_type,
                    asset_code=asset_code,
                    asset_name=historical["name"],
                    source_scope="platform_execution_pin",
                    asset_id=historical["id"],
                    version=historical["version"],
                    config_hash=historical["config_hash"],
                    config=historical["config"],
                    binding_id=binding.id if binding else None,
                    override_id=None,
                )

        if binding is not None and binding.allow_tenant_override:
            override = self.session.scalars(
                select(TenantAssetOverrideRecord).where(
                    TenantAssetOverrideRecord.tenant_id == tenant_id,
                    TenantAssetOverrideRecord.asset_type == asset_type,
                    TenantAssetOverrideRecord.asset_code == asset_code,
                    TenantAssetOverrideRecord.status == "published",
                    TenantAssetOverrideRecord.is_active.is_(True),
                )
            ).first()
            if override is not None:
                resolved_version = f"tenant-v{override.version}"
                if requested_version is not None and str(requested_version) != resolved_version:
                    raise TenantAssetError(
                        "ASSET_VERSION_NOT_ALLOWED",
                        "租户覆盖目录只允许使用当前已发布覆盖版本，请移除平台版本指定",
                        409,
                        {"requested_version": requested_version, "resolved_version": resolved_version},
                    )
                if content_hash(override.config_json) != override.config_hash:
                    raise TenantAssetError("ASSET_INTEGRITY_FAILED", "租户覆盖版本配置哈希不一致", 409)
                return self._resolution(
                    tenant_id=tenant_id,
                    asset_type=asset_type,
                    asset_code=asset_code,
                    asset_name=self._asset_name(asset_type, asset_code),
                    source_scope="tenant_override",
                    asset_id=override.id,
                    version=resolved_version,
                    config_hash=override.config_hash,
                    config=override.config_json,
                    binding_id=binding.id,
                    override_id=override.id,
                )

        version = binding.pinned_version if binding is not None and binding.binding_mode == "pinned" else None
        platform = self._platform_asset(asset_type, asset_code, version)
        if platform is None:
            if version is not None:
                raise TenantAssetError(
                    "ASSET_VERSION_NOT_FOUND",
                    "目录固定的平台资产版本不存在或未发布",
                    404,
                    {"asset_type": asset_type, "asset_code": asset_code, "version": version},
                )
            raise TenantAssetError(
                "ASSET_NOT_FOUND",
                "平台当前没有可用的活动资产版本",
                404,
                {"asset_type": asset_type, "asset_code": asset_code},
            )
        if requested_version is not None and str(platform["version"]) != str(requested_version):
            requested = self._platform_asset(asset_type, asset_code, str(requested_version))
            if requested is None:
                raise TenantAssetError(
                    "ASSET_VERSION_NOT_FOUND",
                    "指定的平台资产版本不存在或未发布",
                    404,
                    {"asset_type": asset_type, "asset_code": asset_code, "version": requested_version},
                )
            raise TenantAssetError(
                "ASSET_VERSION_NOT_ALLOWED",
                "请求版本与当前租户目录解析版本不一致",
                409,
                {
                    "asset_type": asset_type,
                    "asset_code": asset_code,
                    "requested_version": requested_version,
                    "resolved_version": platform["version"],
                },
            )
        source_scope = (
            "platform_pinned"
            if binding is not None and binding.binding_mode == "pinned"
            else "platform_inherited"
            if binding is not None
            else "implicit_platform_default"
        )
        return self._resolution(
            tenant_id=tenant_id,
            asset_type=asset_type,
            asset_code=asset_code,
            asset_name=platform["name"],
            source_scope=source_scope,
            asset_id=platform["id"],
            version=platform["version"],
            config_hash=platform["config_hash"],
            config=platform["config"],
            binding_id=binding.id if binding else None,
            override_id=None,
        )

    def initialize_from_entitlement(
        self,
        tenant_id: str,
        assets: list[dict],
        principal: "Principal",
        reason: str,
    ) -> list[dict]:
        """Apply an approved package catalog inside the caller's transaction."""
        desired = {(item["asset_type"], self._normalize_code(item["asset_type"], item["asset_code"])): item for item in assets}
        existing = self.session.scalars(
            select(TenantAssetBindingRecord).where(TenantAssetBindingRecord.tenant_id == tenant_id)
        ).all()
        existing_map = {(item.asset_type, item.asset_code): item for item in existing}
        snapshots: list[dict] = []
        for key, item in desired.items():
            asset_type, asset_code = key
            self._ensure_type(asset_type)
            platform = self._require_platform_asset(asset_type, asset_code, item.get("pinned_version"))
            record = existing_map.get(key)
            before = self._binding_snapshot(record) if record else None
            if record is None:
                record = TenantAssetBindingRecord(
                    id=str(uuid4()), tenant_id=tenant_id, asset_type=asset_type, asset_code=asset_code,
                    created_by=principal.subject, created_by_name=principal.name,
                )
                self.session.add(record)
            record.binding_mode = item["binding_mode"]
            record.pinned_version = item.get("pinned_version")
            record.allow_tenant_override = bool(item.get("allow_tenant_override"))
            record.status = "active"
            record.resolved_scope = "platform_pinned" if item["binding_mode"] == "pinned" else "platform_inherited"
            record.resolved_asset_id = platform["id"]
            record.resolved_version = platform["version"]
            record.resolved_config_hash = platform["config_hash"]
            record.change_reason = reason
            record.updated_by = principal.subject
            record.updated_by_name = principal.name
            self.session.flush()
            snapshot = self._binding_snapshot(record)
            self._audit(
                "tenant_asset_binding", record.id,
                "tenant_asset_binding_entitled" if before is None else "tenant_asset_binding_entitlement_updated",
                principal, reason, before=before, after=snapshot, target_tenant_id=tenant_id,
            )
            snapshots.append(snapshot)
        for record in existing:
            if (record.asset_type, record.asset_code) in desired or record.status == "suspended":
                continue
            before = self._binding_snapshot(record)
            record.status = "suspended"
            record.resolved_scope = None
            record.resolved_asset_id = None
            record.resolved_version = None
            record.resolved_config_hash = None
            record.change_reason = reason
            record.updated_by = principal.subject
            record.updated_by_name = principal.name
            self.session.flush()
            self._audit(
                "tenant_asset_binding", record.id, "tenant_asset_binding_entitlement_suspended",
                principal, reason, before=before, after=self._binding_snapshot(record), target_tenant_id=tenant_id,
            )
        return snapshots

    def _require_entitlement(self, tenant_id: str, asset_type: str, asset_code: str) -> None:
        context = self._entitlement_context(tenant_id)
        active = context["record"]
        if active is None:
            if context["mode"] == "blocked":
                raise TenantAssetError(
                    "TENANT_ENTITLEMENT_REQUIRED",
                    "当前租户没有生效中的产品授权，不能解析运行资产",
                    403,
                    {"tenant_id": tenant_id, "compatibility_mode": False},
                )
            return
        runtime_environment = "production" if os.getenv("APP_ENV", "development").lower() == "production" else "sandbox"
        if runtime_environment not in active.package_snapshot_json.get("environment_scopes", []):
            raise TenantAssetError(
                "TENANT_ENVIRONMENT_NOT_ENTITLED",
                "当前产品授权不包含本运行环境",
                403,
                {"tenant_id": tenant_id, "runtime_environment": runtime_environment, "entitlement_id": active.id},
            )
        assets = active.package_snapshot_json.get("assets", [])
        if not any(item.get("asset_type") == asset_type and item.get("asset_code") == asset_code for item in assets):
            raise TenantAssetError(
                "ASSET_NOT_ENTITLED",
                "当前产品授权不包含该资产",
                403,
                {"tenant_id": tenant_id, "asset_type": asset_type, "asset_code": asset_code, "entitlement_id": active.id},
            )

    def _entitlement_context(self, tenant_id: str) -> dict:
        cached = self._entitlement_cache.get(tenant_id)
        if cached is not None:
            return cached
        now = datetime.now(timezone.utc)
        active = self.session.scalars(
            select(TenantEntitlementRecord).where(
                TenantEntitlementRecord.tenant_id == tenant_id,
                TenantEntitlementRecord.status == "active",
                TenantEntitlementRecord.starts_at <= now,
                TenantEntitlementRecord.expires_at > now,
            ).order_by(TenantEntitlementRecord.activated_at.desc())
        ).first()
        has_ledger = bool(self.session.scalar(
            select(func.count(TenantEntitlementRecord.id)).where(TenantEntitlementRecord.tenant_id == tenant_id)
        ) or 0)
        strict = os.getenv("TENANT_ENTITLEMENT_STRICT_MODE", "false").lower() in {"1", "true", "yes"}
        context = {
            "mode": "governed" if active else "blocked" if has_ledger or strict else "implicit_compatibility",
            "entitlement_id": active.id if active else None,
            "package_code": active.package_code if active else None,
            "package_version": active.package_version if active else None,
            "record": active,
        }
        self._entitlement_cache[tenant_id] = context
        return context

    def create_binding(self, payload: dict, principal: "Principal") -> dict:
        asset_type = self._ensure_type(payload["asset_type"])
        asset_code = self._normalize_code(asset_type, payload["asset_code"])
        if self._binding(principal.tenant_id, asset_type, asset_code) is not None:
            raise TenantAssetError("ASSET_BINDING_ALREADY_EXISTS", "该资产已在当前租户目录中", 409)
        self._require_platform_asset(asset_type, asset_code, payload.get("pinned_version"))
        record = TenantAssetBindingRecord(
            id=str(uuid4()),
            tenant_id=principal.tenant_id,
            asset_type=asset_type,
            asset_code=asset_code,
            binding_mode=payload["binding_mode"],
            pinned_version=payload.get("pinned_version"),
            allow_tenant_override=payload["allow_tenant_override"],
            status=payload["status"],
            change_reason=payload["reason"],
            created_by=principal.subject,
            created_by_name=principal.name,
            updated_by=principal.subject,
            updated_by_name=principal.name,
        )
        self.session.add(record)
        try:
            self.session.flush()
            self._refresh_snapshot(record)
            self._audit("tenant_asset_binding", record.id, "tenant_asset_binding_created", principal, payload["reason"], after=self._binding_snapshot(record))
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise TenantAssetError("ASSET_BINDING_ALREADY_EXISTS", "该资产已在当前租户目录中", 409) from exc
        self.session.refresh(record)
        return self._binding_view(record)

    def update_binding(self, binding_id: str, payload: dict, principal: "Principal") -> dict:
        record = self._tenant_binding(binding_id, principal.tenant_id)
        self._check_version(record.row_version, payload["expected_row_version"], "资产目录")
        before = self._binding_snapshot(record)
        mode = payload.get("binding_mode") or record.binding_mode
        if payload.get("clear_pinned_version"):
            pinned_version = None
        elif payload.get("pinned_version") is not None:
            pinned_version = payload["pinned_version"]
        else:
            pinned_version = record.pinned_version
        if mode == "inherit_active":
            if payload.get("pinned_version") is not None and not payload.get("clear_pinned_version"):
                raise TenantAssetError("ASSET_BINDING_PIN_INVALID", "跟随平台活动版本时不能保留固定版本", 422)
            pinned_version = None
        elif not pinned_version:
            raise TenantAssetError("ASSET_BINDING_PIN_REQUIRED", "固定版本订阅必须指定版本", 422)
        self._require_platform_asset(record.asset_type, record.asset_code, pinned_version if mode == "pinned" else None)
        record.binding_mode = mode
        record.pinned_version = pinned_version
        if payload.get("allow_tenant_override") is not None:
            record.allow_tenant_override = payload["allow_tenant_override"]
        if payload.get("status") is not None:
            record.status = payload["status"]
        record.change_reason = payload["reason"]
        record.updated_by = principal.subject
        record.updated_by_name = principal.name
        self._refresh_snapshot(record)
        if self._binding_snapshot(record) == before:
            raise TenantAssetError("ASSET_BINDING_UNCHANGED", "资产目录配置未发生变化", 422)
        self._commit(
            "tenant_asset_binding",
            record.id,
            "tenant_asset_binding_updated",
            principal,
            payload["reason"],
            before,
            lambda: self._binding_snapshot(record),
        )
        return self._binding_view(record)

    def create_override(self, payload: dict, principal: "Principal") -> dict:
        asset_type = self._ensure_type(payload["asset_type"])
        asset_code = self._normalize_code(asset_type, payload["asset_code"])
        binding = self._binding(principal.tenant_id, asset_type, asset_code)
        if binding is None or binding.status != "active" or not binding.allow_tenant_override:
            raise TenantAssetError("TENANT_OVERRIDE_NOT_ALLOWED", "请先建立有效目录并开启租户覆盖版本", 422)
        base_version = payload.get("base_version")
        if base_version is None and binding.binding_mode == "pinned":
            base_version = binding.pinned_version
        base = self._require_platform_asset(asset_type, asset_code, base_version)
        config = self._validate_override_config(asset_type, asset_code, payload["config"])
        latest_version = self.session.scalar(
            select(func.max(TenantAssetOverrideRecord.version)).where(
                TenantAssetOverrideRecord.tenant_id == principal.tenant_id,
                TenantAssetOverrideRecord.asset_type == asset_type,
                TenantAssetOverrideRecord.asset_code == asset_code,
            )
        ) or 0
        record = TenantAssetOverrideRecord(
            id=str(uuid4()),
            tenant_id=principal.tenant_id,
            asset_type=asset_type,
            asset_code=asset_code,
            version=int(latest_version) + 1,
            base_asset_id=base["id"],
            base_version=base["version"],
            base_config_hash=base["config_hash"],
            config_json=config,
            config_hash=content_hash(config),
            status="draft",
            is_active=False,
            change_reason=payload["reason"],
            created_by=principal.subject,
            created_by_name=principal.name,
        )
        self.session.add(record)
        try:
            self.session.flush()
            self._audit("tenant_asset_override", record.id, "tenant_asset_override_created", principal, payload["reason"], after=self._override_snapshot(record))
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise TenantAssetError("TENANT_OVERRIDE_VERSION_CONFLICT", "租户覆盖版本发生并发冲突，请刷新后重试", 409) from exc
        self.session.refresh(record)
        return self._override_view(record)

    def update_override(self, override_id: str, payload: dict, principal: "Principal") -> dict:
        record = self._tenant_override(override_id, principal.tenant_id)
        self._check_version(record.row_version, payload["expected_row_version"], "租户覆盖版本")
        if record.status not in {"draft", "rejected"}:
            raise TenantAssetError("TENANT_OVERRIDE_IMMUTABLE", "只有草稿或已驳回版本可以修改", 422)
        before = self._override_snapshot(record)
        config = self._validate_override_config(record.asset_type, record.asset_code, payload["config"])
        record.config_json = config
        record.config_hash = content_hash(config)
        record.status = "draft"
        record.change_reason = payload["reason"]
        record.submitted_at = None
        record.reviewed_by = None
        record.reviewed_by_name = None
        record.reviewed_at = None
        record.review_comment = None
        self._commit(
            "tenant_asset_override",
            record.id,
            "tenant_asset_override_updated",
            principal,
            payload["reason"],
            before,
            lambda: self._override_snapshot(record),
        )
        return self._override_view(record)

    def submit_override(self, override_id: str, payload: dict, principal: "Principal") -> dict:
        record = self._tenant_override(override_id, principal.tenant_id)
        self._check_version(record.row_version, payload["expected_row_version"], "租户覆盖版本")
        if record.status != "draft":
            raise TenantAssetError("TENANT_OVERRIDE_NOT_DRAFT", "只有草稿版本可以提交复核", 422)
        if record.created_by != principal.subject:
            raise TenantAssetError("TENANT_OVERRIDE_SUBMITTER_INVALID", "只能由草稿创建人提交复核", 403)
        before = self._override_snapshot(record)
        record.status = "pending_review"
        record.submitted_at = datetime.now(timezone.utc)
        self._commit(
            "tenant_asset_override",
            record.id,
            "tenant_asset_override_submitted",
            principal,
            payload["reason"],
            before,
            lambda: self._override_snapshot(record),
        )
        return self._override_view(record)

    def review_override(self, override_id: str, payload: dict, principal: "Principal") -> dict:
        record = self._tenant_override(override_id, principal.tenant_id)
        self._check_version(record.row_version, payload["expected_row_version"], "租户覆盖版本")
        if record.status != "pending_review":
            raise TenantAssetError("TENANT_OVERRIDE_NOT_PENDING", "该覆盖版本不在待复核状态", 422)
        if record.created_by == principal.subject:
            raise TenantAssetError("FOUR_EYE_REVIEW_REQUIRED", "提交人与复核人必须分离", 403)
        binding = self._binding(principal.tenant_id, record.asset_type, record.asset_code)
        if payload["decision"] == "approve" and (
            binding is None or binding.status != "active" or not binding.allow_tenant_override
        ):
            raise TenantAssetError("TENANT_OVERRIDE_NOT_ALLOWED", "目录已停用或未开启覆盖，不能批准版本", 422)
        base = self._platform_asset(record.asset_type, record.asset_code, record.base_version)
        if base is None or base["id"] != record.base_asset_id or base["config_hash"] != record.base_config_hash:
            raise TenantAssetError("TENANT_OVERRIDE_BASE_DRIFTED", "覆盖版本绑定的平台基线已丢失或完整性校验失败", 409)
        if content_hash(record.config_json) != record.config_hash:
            raise TenantAssetError("ASSET_INTEGRITY_FAILED", "租户覆盖版本配置哈希不一致", 409)

        before = self._override_snapshot(record)
        now = datetime.now(timezone.utc)
        record.reviewed_by = principal.subject
        record.reviewed_by_name = principal.name
        record.reviewed_at = now
        record.review_comment = payload["comment"]
        if payload["decision"] == "reject":
            record.status = "rejected"
            event_type = "tenant_asset_override_rejected"
        else:
            active_rows = self.session.scalars(
                select(TenantAssetOverrideRecord).where(
                    TenantAssetOverrideRecord.tenant_id == principal.tenant_id,
                    TenantAssetOverrideRecord.asset_type == record.asset_type,
                    TenantAssetOverrideRecord.asset_code == record.asset_code,
                    TenantAssetOverrideRecord.is_active.is_(True),
                )
            ).all()
            for active in active_rows:
                if active.id != record.id:
                    active.is_active = False
                    active.status = "retired"
            record.status = "published"
            record.is_active = True
            record.published_at = now
            event_type = "tenant_asset_override_published"
        self.session.flush()
        self._refresh_binding_snapshot(binding)
        self._commit(
            "tenant_asset_override",
            record.id,
            event_type,
            principal,
            payload["comment"],
            before,
            lambda: self._override_snapshot(record),
        )
        return self._override_view(record)

    def _platform_codes(self, asset_type: str) -> list[str]:
        model, code_field, _, has_status = self._asset_descriptor(asset_type)
        statement = select(code_field).distinct()
        if has_status:
            statement = statement.where(model.status == "published")
        return list(self.session.scalars(statement.order_by(code_field)).all())

    def _platform_versions(self, asset_type: str, asset_code: str) -> list[dict]:
        model, code_field, version_field, has_status = self._asset_descriptor(asset_type)
        statement = select(model).where(code_field == asset_code)
        if has_status:
            statement = statement.where(model.status == "published")
        rows = self.session.scalars(statement.order_by(version_field.desc())).all()
        return [self._serialize_platform_asset(asset_type, item) for item in rows]

    def _platform_asset(self, asset_type: str, asset_code: str, version: str | None) -> dict | None:
        model, code_field, version_field, has_status = self._asset_descriptor(asset_type)
        statement = select(model).where(code_field == asset_code)
        if has_status:
            statement = statement.where(model.status == "published")
        if version is None:
            statement = statement.where(model.is_active.is_(True)).order_by(version_field.desc())
        elif asset_type == "model":
            statement = statement.where(version_field == version)
        else:
            try:
                numeric_version = int(version)
            except (TypeError, ValueError):
                return None
            statement = statement.where(version_field == numeric_version)
        record = self.session.scalars(statement.limit(1)).first()
        return self._serialize_platform_asset(asset_type, record) if record is not None else None

    def _require_platform_asset(self, asset_type: str, asset_code: str, version: str | None) -> dict:
        asset = self._platform_asset(asset_type, asset_code, version)
        if asset is None:
            raise TenantAssetError(
                "ASSET_VERSION_NOT_FOUND" if version is not None else "ASSET_NOT_FOUND",
                "指定的平台资产版本不存在或未发布" if version is not None else "平台当前没有可用的活动资产版本",
                404,
                {"asset_type": asset_type, "asset_code": asset_code, "version": version},
            )
        return asset

    @staticmethod
    def _asset_descriptor(asset_type: str):
        descriptors = {
            "indicator": (IndicatorDefinition, IndicatorDefinition.code, IndicatorDefinition.version, True),
            "scorecard": (ScorecardDefinition, ScorecardDefinition.code, ScorecardDefinition.version, True),
            "model": (ModelReleaseRecord, ModelReleaseRecord.template_key, ModelReleaseRecord.model_version, False),
            "rule": (RuleDefinition, RuleDefinition.code, RuleDefinition.version, True),
            "rule_set": (RuleSetDefinition, RuleSetDefinition.code, RuleSetDefinition.version, True),
            "pipeline": (DecisionPipelineDefinition, DecisionPipelineDefinition.code, DecisionPipelineDefinition.version, True),
        }
        return descriptors[asset_type]

    def _serialize_platform_asset(self, asset_type: str, record) -> dict:
        if asset_type == "model":
            config = deepcopy(record.config_json)
            config_hash = record.config_hash
            code, name, version = record.template_key, str(record.config_json.get("name") or record.template_key), record.model_version
        elif asset_type == "scorecard":
            config = deepcopy(record.config_json)
            config_hash = record.config_hash
            code, name, version = record.code, record.name, str(record.version)
        elif asset_type == "indicator":
            config = {
                "code": record.code,
                "name": record.name,
                "category": record.category,
                "layer": record.layer,
                "data_type": record.data_type,
                "field_path": record.field_path,
                "expression": record.expression,
                "dependencies": deepcopy(record.dependencies),
                "scoring_json": deepcopy(record.scoring_json),
                "max_score": float(record.max_score),
                "default_weight": float(record.default_weight),
                "source_references": deepcopy(record.source_references),
                "seed_source": record.seed_source,
                "version": record.version,
            }
            config_hash = content_hash(config)
            code, name, version = record.code, record.name, str(record.version)
        elif asset_type == "rule":
            config = {
                "code": record.code,
                "name": record.name,
                "version": record.version,
                "rule_type": record.rule_type,
                "category": record.category,
                "enabled": record.enabled,
                "conditions_json": deepcopy(record.conditions_json),
                "condition_relation": record.condition_relation,
                "actions_json": deepcopy(record.actions_json),
                "priority": record.priority,
            }
            config_hash = content_hash(config)
            code, name, version = record.code, record.name, str(record.version)
        elif asset_type == "rule_set":
            config = {
                "code": record.code,
                "name": record.name,
                "version": record.version,
                "rule_codes": deepcopy(record.rule_codes),
                "evaluation_strategy": record.evaluation_strategy,
            }
            config_hash = content_hash(config)
            code, name, version = record.code, record.name, str(record.version)
        else:
            config = {"code": record.code, "name": record.name, "version": record.version, "stages_json": deepcopy(record.stages_json)}
            config_hash = content_hash(config)
            code, name, version = record.code, record.name, str(record.version)
        if asset_type in {"model", "scorecard"} and content_hash(config) != config_hash:
            raise TenantAssetError("ASSET_INTEGRITY_FAILED", f"平台{self._type_label(asset_type)}配置哈希不一致", 409)
        return {"id": record.id, "code": code, "name": name, "version": str(version), "config": config, "config_hash": config_hash, "is_active": bool(record.is_active)}

    @staticmethod
    def _validate_override_config(asset_type: str, asset_code: str, config: dict) -> dict:
        if not isinstance(config, dict) or not config:
            raise TenantAssetError("TENANT_OVERRIDE_CONFIG_INVALID", "租户覆盖配置必须是非空 JSON 对象", 422)
        copied = deepcopy(config)
        configured_code = copied.get("code")
        if configured_code is None and asset_type == "model":
            configured_code = copied.get("key") or copied.get("template_key")
        if configured_code is not None and TenantAssetRepository._normalize_code(asset_type, str(configured_code)) != asset_code:
            raise TenantAssetError("TENANT_OVERRIDE_IDENTITY_MISMATCH", "覆盖配置中的资产编码不能改变", 422)
        return copied

    @staticmethod
    def _resolution(**values) -> dict:
        result = {**values, "config": deepcopy(values["config"])}
        result["resolution_hash"] = content_hash({
            "tenant_id": result["tenant_id"],
            "asset_type": result["asset_type"],
            "asset_code": result["asset_code"],
            "source_scope": result["source_scope"],
            "asset_id": result["asset_id"],
            "version": result["version"],
            "config_hash": result["config_hash"],
            "binding_id": result["binding_id"],
            "override_id": result["override_id"],
        })
        return result

    def _refresh_snapshot(self, record: TenantAssetBindingRecord) -> None:
        if record.status == "suspended":
            record.resolved_scope = None
            record.resolved_asset_id = None
            record.resolved_version = None
            record.resolved_config_hash = None
            return
        resolution = self.resolve(record.tenant_id, record.asset_type, record.asset_code)
        record.resolved_scope = resolution["source_scope"]
        record.resolved_asset_id = resolution["asset_id"]
        record.resolved_version = resolution["version"]
        record.resolved_config_hash = resolution["config_hash"]

    def _refresh_binding_snapshot(self, record: TenantAssetBindingRecord | None) -> None:
        if record is None:
            return
        self._refresh_snapshot(record)
        self.session.flush()

    def _asset_name(self, asset_type: str, asset_code: str) -> str:
        active = self._platform_asset(asset_type, asset_code, None)
        if active is not None:
            return active["name"]
        versions = self._platform_versions(asset_type, asset_code)
        return versions[0]["name"] if versions else asset_code

    def _binding(self, tenant_id: str, asset_type: str, asset_code: str) -> TenantAssetBindingRecord | None:
        return self.session.scalars(select(TenantAssetBindingRecord).where(
            TenantAssetBindingRecord.tenant_id == tenant_id,
            TenantAssetBindingRecord.asset_type == asset_type,
            TenantAssetBindingRecord.asset_code == asset_code,
        )).first()

    def _tenant_binding(self, binding_id: str, tenant_id: str) -> TenantAssetBindingRecord:
        record = self.session.scalars(select(TenantAssetBindingRecord).where(
            TenantAssetBindingRecord.id == binding_id,
            TenantAssetBindingRecord.tenant_id == tenant_id,
        )).first()
        if record is None:
            raise TenantAssetError("ASSET_BINDING_NOT_FOUND", "当前租户下不存在该资产目录", 404)
        return record

    def _tenant_override(self, override_id: str, tenant_id: str) -> TenantAssetOverrideRecord:
        record = self.session.scalars(select(TenantAssetOverrideRecord).where(
            TenantAssetOverrideRecord.id == override_id,
            TenantAssetOverrideRecord.tenant_id == tenant_id,
        )).first()
        if record is None:
            raise TenantAssetError("TENANT_OVERRIDE_NOT_FOUND", "当前租户下不存在该覆盖版本", 404)
        return record

    @staticmethod
    def _binding_snapshot(record: TenantAssetBindingRecord) -> dict:
        return {
            "id": record.id,
            "tenant_id": record.tenant_id,
            "asset_type": record.asset_type,
            "asset_code": record.asset_code,
            "binding_mode": record.binding_mode,
            "pinned_version": record.pinned_version,
            "allow_tenant_override": record.allow_tenant_override,
            "status": record.status,
            "resolved_scope": record.resolved_scope,
            "resolved_asset_id": record.resolved_asset_id,
            "resolved_version": record.resolved_version,
            "resolved_config_hash": record.resolved_config_hash,
            "change_reason": record.change_reason,
            "created_by": record.created_by,
            "created_by_name": record.created_by_name,
            "updated_by": record.updated_by,
            "updated_by_name": record.updated_by_name,
            "row_version": record.row_version,
        }

    def _binding_view(self, record: TenantAssetBindingRecord) -> dict:
        return {**self._binding_snapshot(record), "created_at": _iso(record.created_at), "updated_at": _iso(record.updated_at)}

    @staticmethod
    def _override_snapshot(record: TenantAssetOverrideRecord) -> dict:
        return {
            "id": record.id,
            "tenant_id": record.tenant_id,
            "asset_type": record.asset_type,
            "asset_code": record.asset_code,
            "version": record.version,
            "base_asset_id": record.base_asset_id,
            "base_version": record.base_version,
            "base_config_hash": record.base_config_hash,
            "config_hash": record.config_hash,
            "status": record.status,
            "is_active": record.is_active,
            "change_reason": record.change_reason,
            "created_by": record.created_by,
            "created_by_name": record.created_by_name,
            "submitted_at": _iso(record.submitted_at),
            "reviewed_by": record.reviewed_by,
            "reviewed_by_name": record.reviewed_by_name,
            "reviewed_at": _iso(record.reviewed_at),
            "review_comment": record.review_comment,
            "published_at": _iso(record.published_at),
            "row_version": record.row_version,
        }

    def _override_view(self, record: TenantAssetOverrideRecord) -> dict:
        return {
            **self._override_snapshot(record),
            "config": deepcopy(record.config_json),
            "created_at": _iso(record.created_at),
            "updated_at": _iso(record.updated_at),
        }

    def _audit(self, aggregate_type: str, aggregate_id: str, event_type: str, principal: "Principal", reason: str, before: dict | None = None, after: dict | None = None, target_tenant_id: str | None = None) -> None:
        self.audit.append(aggregate_type, aggregate_id, event_type, principal.name, {
            "tenant_id": target_tenant_id or principal.tenant_id,
            "actor_tenant_id": principal.tenant_id,
            "actor_subject": principal.subject,
            "actor_client_id": principal.client_id,
            "reason": reason,
            "before": deepcopy(before),
            "after": deepcopy(after),
        })

    def _commit(self, aggregate_type: str, aggregate_id: str, event_type: str, principal: "Principal", reason: str, before: dict, after_factory) -> None:
        try:
            self.session.flush()
            self._audit(aggregate_type, aggregate_id, event_type, principal, reason, before, after_factory())
            self.session.commit()
        except (IntegrityError, StaleDataError) as exc:
            self.session.rollback()
            raise TenantAssetError("ROW_VERSION_CONFLICT", "资产已被其他用户更新，请刷新后重试", 409) from exc

    @staticmethod
    def _check_version(current: int, expected: int, subject: str) -> None:
        if current != expected:
            raise TenantAssetError("ROW_VERSION_CONFLICT", f"{subject}版本已变化，当前版本为 {current}", 409)

    @staticmethod
    def _ensure_type(asset_type: str) -> str:
        if asset_type not in ASSET_TYPES:
            raise TenantAssetError("ASSET_TYPE_INVALID", "不支持的资产类型", 422)
        return asset_type

    @staticmethod
    def _normalize_code(asset_type: str, asset_code: str) -> str:
        value = asset_code.strip()
        return value.lower() if asset_type in {"indicator", "model"} else value.upper()

    @staticmethod
    def _type_label(asset_type: str) -> str:
        return {"indicator": "指标", "scorecard": "评分卡", "model": "模型", "rule": "规则", "rule_set": "规则集", "pipeline": "决策管线"}[asset_type]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
