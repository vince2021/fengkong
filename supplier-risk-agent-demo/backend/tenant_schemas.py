"""Typed contracts for the platform tenant administration control plane."""
from __future__ import annotations

import ipaddress
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


RegistryIdentifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=2,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    ),
]
DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=255)]
ChangeReason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]
TenantRole = Literal[
    "client",
    "relationship_manager",
    "risk_manager",
    "model_admin",
    "approver",
    "auditor",
    "integration_admin",
    "operations",
    "admin",
]


class TenantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: RegistryIdentifier
    name: DisplayName
    deployment_mode: Literal["saas", "dedicated"] = "saas"
    data_region: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=64)] = "cn"
    reason: ChangeReason


class TenantStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["active", "suspended", "disabled"]
    expected_row_version: int = Field(ge=1)
    reason: ChangeReason


class TenantMembershipCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: RegistryIdentifier
    display_name: DisplayName
    roles: list[TenantRole] = Field(min_length=1, max_length=9)
    expires_at: datetime | None = None
    reason: ChangeReason

    @model_validator(mode="after")
    def validate_unique_roles(self):
        if len(self.roles) != len(set(self.roles)):
            raise ValueError("成员角色不允许重复")
        return self


class TenantMembershipUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: DisplayName | None = None
    roles: list[TenantRole] | None = Field(default=None, min_length=1, max_length=9)
    status: Literal["active", "suspended", "revoked"] | None = None
    expires_at: datetime | None = None
    clear_expiry: bool = False
    expected_row_version: int = Field(ge=1)
    reason: ChangeReason

    @model_validator(mode="after")
    def validate_change(self):
        if self.roles is not None and len(self.roles) != len(set(self.roles)):
            raise ValueError("成员角色不允许重复")
        if not any((self.display_name is not None, self.roles is not None, self.status is not None, self.expires_at is not None, self.clear_expiry)):
            raise ValueError("至少提供一项成员变更")
        if self.expires_at is not None and self.clear_expiry:
            raise ValueError("expires_at 与 clear_expiry 不能同时设置")
        return self


class ApiClientCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: RegistryIdentifier
    name: DisplayName
    key_id: RegistryIdentifier
    key_fingerprint: Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=255)]
    secret_reference: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=256)] | None = None
    qps_limit: int = Field(default=20, ge=1, le=100000)
    concurrent_job_limit: int = Field(default=3, ge=1, le=10000)
    daily_item_quota: int = Field(default=10000, ge=1, le=1000000000)
    allowed_cidrs: list[str] = Field(default_factory=list, max_length=100)
    expires_at: datetime | None = None
    reason: ChangeReason

    @field_validator("allowed_cidrs")
    @classmethod
    def validate_cidrs(cls, values: list[str]) -> list[str]:
        return _normalized_cidrs(values)


class ApiClientUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: DisplayName | None = None
    status: Literal["active", "disabled", "revoked"] | None = None
    key_id: RegistryIdentifier | None = None
    key_fingerprint: Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=255)] | None = None
    secret_reference: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=256)] | None = None
    clear_secret_reference: bool = False
    qps_limit: int | None = Field(default=None, ge=1, le=100000)
    concurrent_job_limit: int | None = Field(default=None, ge=1, le=10000)
    daily_item_quota: int | None = Field(default=None, ge=1, le=1000000000)
    allowed_cidrs: list[str] | None = Field(default=None, max_length=100)
    expires_at: datetime | None = None
    clear_expiry: bool = False
    expected_row_version: int = Field(ge=1)
    reason: ChangeReason

    @field_validator("allowed_cidrs")
    @classmethod
    def validate_cidrs(cls, values: list[str] | None) -> list[str] | None:
        return _normalized_cidrs(values) if values is not None else None

    @model_validator(mode="after")
    def validate_change(self):
        fields = (
            self.name,
            self.status,
            self.key_id,
            self.key_fingerprint,
            self.secret_reference,
            self.qps_limit,
            self.concurrent_job_limit,
            self.daily_item_quota,
            self.allowed_cidrs,
            self.expires_at,
        )
        if not any(value is not None for value in fields) and not self.clear_secret_reference and not self.clear_expiry:
            raise ValueError("至少提供一项客户端变更")
        if self.secret_reference is not None and self.clear_secret_reference:
            raise ValueError("secret_reference 与 clear_secret_reference 不能同时设置")
        if self.expires_at is not None and self.clear_expiry:
            raise ValueError("expires_at 与 clear_expiry 不能同时设置")
        return self


class TenantView(BaseModel):
    id: str
    name: str
    deployment_mode: str
    status: str
    data_region: str
    membership_count: int
    api_client_count: int
    row_version: int
    created_at: str | None
    updated_at: str | None


class TenantPage(BaseModel):
    items: list[TenantView]
    total: int
    limit: int
    offset: int


class TenantMembershipView(BaseModel):
    id: str
    tenant_id: str
    subject: str
    display_name: str
    roles: list[str]
    status: str
    expires_at: str | None
    row_version: int
    created_at: str | None
    updated_at: str | None


class ApiClientView(BaseModel):
    id: str
    tenant_id: str
    client_id: str
    name: str
    status: str
    key_id: str
    key_fingerprint: str
    secret_reference: str | None
    qps_limit: int
    concurrent_job_limit: int
    daily_item_quota: int
    allowed_cidrs: list[str]
    rotated_at: str | None
    expires_at: str | None
    last_used_at: str | None
    row_version: int
    created_at: str | None
    updated_at: str | None


def _normalized_cidrs(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        try:
            network = ipaddress.ip_network(value.strip(), strict=False)
        except ValueError as exc:
            raise ValueError(f"无效的 IP/CIDR：{value}") from exc
        canonical = str(network)
        if canonical not in normalized:
            normalized.append(canonical)
    return normalized
