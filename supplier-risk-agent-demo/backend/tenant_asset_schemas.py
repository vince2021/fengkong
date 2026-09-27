"""Typed contracts for tenant asset subscriptions and governed overrides."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


AssetType = Literal["indicator", "scorecard", "model", "rule", "rule_set", "pipeline"]
AssetCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=2, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"),
]
AssetVersion = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
ChangeReason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]
ReviewComment = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=2000)]


class TenantAssetBindingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_type: AssetType
    asset_code: AssetCode
    binding_mode: Literal["inherit_active", "pinned"] = "inherit_active"
    pinned_version: AssetVersion | None = None
    allow_tenant_override: bool = False
    status: Literal["active", "suspended"] = "active"
    reason: ChangeReason

    @model_validator(mode="after")
    def validate_pin(self):
        if self.binding_mode == "pinned" and self.pinned_version is None:
            raise ValueError("固定版本订阅必须指定 pinned_version")
        if self.binding_mode == "inherit_active" and self.pinned_version is not None:
            raise ValueError("跟随平台活动版本时不能指定 pinned_version")
        return self


class TenantAssetBindingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    binding_mode: Literal["inherit_active", "pinned"] | None = None
    pinned_version: AssetVersion | None = None
    clear_pinned_version: bool = False
    allow_tenant_override: bool | None = None
    status: Literal["active", "suspended"] | None = None
    expected_row_version: int = Field(ge=1)
    reason: ChangeReason

    @model_validator(mode="after")
    def validate_change(self):
        if self.pinned_version is not None and self.clear_pinned_version:
            raise ValueError("pinned_version 与 clear_pinned_version 不能同时设置")
        if not any(
            value is not None
            for value in (self.binding_mode, self.pinned_version, self.allow_tenant_override, self.status)
        ) and not self.clear_pinned_version:
            raise ValueError("至少提供一项目录变更")
        return self


class TenantAssetOverrideCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_type: AssetType
    asset_code: AssetCode
    base_version: AssetVersion | None = None
    config: dict
    reason: ChangeReason


class TenantAssetOverrideUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: dict
    expected_row_version: int = Field(ge=1)
    reason: ChangeReason


class TenantAssetVersionAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_row_version: int = Field(ge=1)
    reason: ChangeReason


class TenantAssetOverrideReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_row_version: int = Field(ge=1)
    decision: Literal["approve", "reject"]
    comment: ReviewComment


class TenantAssetBindingView(BaseModel):
    id: str
    tenant_id: str
    asset_type: str
    asset_code: str
    binding_mode: str
    pinned_version: str | None
    allow_tenant_override: bool
    status: str
    resolved_scope: str | None
    resolved_asset_id: str | None
    resolved_version: str | None
    resolved_config_hash: str | None
    change_reason: str
    created_by: str
    created_by_name: str
    updated_by: str
    updated_by_name: str
    row_version: int
    created_at: str | None
    updated_at: str | None


class TenantAssetOverrideView(BaseModel):
    id: str
    tenant_id: str
    asset_type: str
    asset_code: str
    version: int
    base_asset_id: str
    base_version: str
    base_config_hash: str
    config: dict
    config_hash: str
    status: str
    is_active: bool
    change_reason: str
    created_by: str
    created_by_name: str
    submitted_at: str | None
    reviewed_by: str | None
    reviewed_by_name: str | None
    reviewed_at: str | None
    review_comment: str | None
    published_at: str | None
    row_version: int
    created_at: str | None
    updated_at: str | None


class TenantAssetResolution(BaseModel):
    tenant_id: str
    asset_type: str
    asset_code: str
    asset_name: str
    source_scope: str
    asset_id: str
    version: str
    config_hash: str
    config: dict
    binding_id: str | None
    override_id: str | None
    resolution_hash: str


class TenantAssetCatalogItem(BaseModel):
    asset_type: str
    asset_code: str
    asset_name: str
    available_versions: list[str]
    active_platform_version: str | None
    binding: TenantAssetBindingView | None
    overrides: list[TenantAssetOverrideView]
    resolution: TenantAssetResolution | None
    resolution_error: dict | None


class TenantAssetCatalog(BaseModel):
    tenant_id: str
    summary: dict
    items: list[TenantAssetCatalogItem]
