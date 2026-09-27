"""Contracts for commercial product packages and tenant entitlement ledgers."""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from backend.tenant_asset_schemas import AssetCode, AssetType, AssetVersion, ChangeReason


PackageCode = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=255)]
ReviewComment = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=2000)]


class PackageAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_type: AssetType
    asset_code: AssetCode
    binding_mode: Literal["inherit_active", "pinned"] = "inherit_active"
    pinned_version: AssetVersion | None = None
    allow_tenant_override: bool = False

    @model_validator(mode="after")
    def validate_pin(self):
        if self.binding_mode == "pinned" and self.pinned_version is None:
            raise ValueError("固定版本资产必须指定 pinned_version")
        if self.binding_mode == "inherit_active" and self.pinned_version is not None:
            raise ValueError("跟随平台版本的资产不能指定 pinned_version")
        return self


class PackageQuotas(BaseModel):
    model_config = ConfigDict(extra="forbid")

    qps_limit: int = Field(default=20, ge=1, le=100000)
    concurrent_job_limit: int = Field(default=3, ge=1, le=10000)
    daily_item_quota: int = Field(default=10000, ge=1, le=1000000000)
    max_asset_bindings: int = Field(default=100, ge=1, le=100000)


class ProductPackageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: PackageCode
    name: DisplayName
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=2000)]
    environment_scopes: list[Literal["sandbox", "production"]] = Field(min_length=1, max_length=2)
    assets: list[PackageAsset] = Field(min_length=1, max_length=10000)
    quotas: PackageQuotas
    expiry_policy: Literal["block"] = "block"
    reason: ChangeReason

    @model_validator(mode="after")
    def validate_uniqueness(self):
        if len(self.environment_scopes) != len(set(self.environment_scopes)):
            raise ValueError("环境范围不允许重复")
        keys = [(item.asset_type, item.asset_code) for item in self.assets]
        if len(keys) != len(set(keys)):
            raise ValueError("产品包资产不允许重复")
        if len(self.assets) > self.quotas.max_asset_bindings:
            raise ValueError("产品包资产数量不能超过资产配额")
        return self


class VersionAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_row_version: int = Field(ge=1)
    reason: ChangeReason


class GovernanceReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_row_version: int = Field(ge=1)
    decision: Literal["approve", "reject"]
    comment: ReviewComment


class EntitlementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: PackageCode
    product_package_id: PackageCode
    starts_at: datetime
    expires_at: datetime
    quota_overrides: PackageQuotas | None = None
    reason: ChangeReason

    @model_validator(mode="after")
    def validate_window(self):
        if self.expires_at <= self.starts_at:
            raise ValueError("授权结束时间必须晚于开始时间")
        return self


class EntitlementStatusAction(VersionAction):
    action: Literal["activate", "suspend", "terminate"]


class EntitlementLifecycleScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=160)] | None = None


class EntitlementLifecycleIncidentAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_row_version: int = Field(ge=1)
    reason: ChangeReason


class EntitlementLifecycleRetry(EntitlementLifecycleIncidentAction):
    run_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=160)] | None = None


class UsageRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: PackageCode
    usage_date: date | None = None


class UsageStatementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: PackageCode
    billing_month: date


class ProductPackageView(BaseModel):
    id: str; code: str; version: int; name: str; description: str; status: str; is_active: bool
    environment_scopes: list[str]; assets: list[dict]; quotas: dict; expiry_policy: str; config_hash: str
    change_reason: str; created_by: str; created_by_name: str; submitted_at: str | None
    reviewed_by: str | None; reviewed_by_name: str | None; reviewed_at: str | None
    review_comment: str | None; published_at: str | None; row_version: int
    created_at: str | None; updated_at: str | None


class EntitlementView(BaseModel):
    id: str; tenant_id: str; product_package_id: str; package_code: str; package_version: int
    package_config_hash: str; package_snapshot: dict; effective_quotas: dict; initialized_assets: list[dict]
    activation_hash: str | None; status: str; effective_status: str; starts_at: str; expires_at: str
    change_reason: str; created_by: str; created_by_name: str; submitted_at: str | None
    reviewed_by: str | None; reviewed_by_name: str | None; reviewed_at: str | None
    review_comment: str | None; activated_at: str | None; suspended_at: str | None
    expired_at: str | None; terminated_at: str | None; row_version: int; created_at: str | None; updated_at: str | None


class EntitlementImpactPreview(BaseModel):
    tenant_id: str; package_code: str; package_version: int; package_config_hash: str
    effective_quotas: dict; assets_to_create: list[dict]; assets_to_update: list[dict]
    assets_to_suspend: list[dict]; clients_to_update: int; warnings: list[str]; preview_hash: str


class EntitlementLifecycleRunView(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str; run_key: str; trigger_type: str; status: str; scan_at: str
    activated_count: int; expired_count: int; superseded_count: int; failed_count: int
    results: list[dict]; evidence_hash: str; error_summary: str | None; incident_status: str
    row_version: int; started_at: str; completed_at: str | None; created_at: str | None


class TenantUsageDailyView(BaseModel):
    id: str; tenant_id: str; usage_date: str; usage: dict; source_watermark: dict
    evidence_hash: str; computed_at: str | None


class TenantUsageStatementView(BaseModel):
    id: str; tenant_id: str; billing_month: str; statement_version: int; status: str
    statement: dict; statement_hash: str; generated_by: str; generated_by_name: str; created_at: str | None
