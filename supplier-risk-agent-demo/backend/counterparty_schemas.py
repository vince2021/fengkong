"""Contracts for tenant-scoped counterparty master data."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


CounterpartyIdentifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    ),
]
CounterpartyName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=255)]
ImportIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=4, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"),
]
MappingTemplateIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"),
]
CreditCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_upper=True, min_length=8, max_length=64, pattern=r"^[0-9A-Z-]+$"),
]
ChangeReason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]


RESERVED_PROFILE_KEYS = {
    "id",
    "tenant_id",
    "counterparty_id",
    "credit_code",
    "name",
    "counterparty_type",
    "industry",
    "cooperation_status",
    "is_key_counterparty",
    "requested_limit",
    "current_limit",
    "current_payment_term_days",
    "current_rating",
    "current_segment",
    "external",
    "internal",
    "financial",
    "status",
    "source_type",
    "profile_hash",
    "row_version",
    "created_at",
    "updated_at",
    "archived_at",
    "archived_by",
    "archive_reason",
}


class CounterpartyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    counterparty_id: CounterpartyIdentifier
    credit_code: CreditCode
    name: CounterpartyName
    counterparty_type: Literal["supplier", "customer"]
    industry: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128)] = "general"
    cooperation_status: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=64)] = "pending"
    is_key_counterparty: bool = False
    requested_limit: float = Field(default=0, ge=0, le=1000000000000)
    current_limit: float = Field(default=0, ge=0, le=1000000000000)
    current_payment_term_days: int = Field(default=0, ge=0, le=3650)
    current_rating: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)] | None = None
    current_segment: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)] | None = None
    external: dict[str, Any] = Field(default_factory=dict, max_length=500)
    internal: dict[str, Any] = Field(default_factory=dict, max_length=500)
    financial: dict[str, Any] = Field(default_factory=dict, max_length=500)
    extensions: dict[str, Any] = Field(default_factory=dict, max_length=100)
    reason: ChangeReason

    @field_validator("extensions")
    @classmethod
    def validate_extensions(cls, value: dict[str, Any]) -> dict[str, Any]:
        conflicts = sorted(RESERVED_PROFILE_KEYS.intersection(value))
        if conflicts:
            raise ValueError(f"扩展字段与保留字段冲突：{', '.join(conflicts)}")
        return value


class CounterpartyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credit_code: CreditCode | None = None
    name: CounterpartyName | None = None
    counterparty_type: Literal["supplier", "customer"] | None = None
    industry: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128)] | None = None
    cooperation_status: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=64)] | None = None
    is_key_counterparty: bool | None = None
    requested_limit: float | None = Field(default=None, ge=0, le=1000000000000)
    current_limit: float | None = Field(default=None, ge=0, le=1000000000000)
    current_payment_term_days: int | None = Field(default=None, ge=0, le=3650)
    current_rating: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)] | None = None
    current_segment: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)] | None = None
    clear_current_rating: bool = False
    clear_current_segment: bool = False
    external: dict[str, Any] | None = Field(default=None, max_length=500)
    internal: dict[str, Any] | None = Field(default=None, max_length=500)
    financial: dict[str, Any] | None = Field(default=None, max_length=500)
    extensions: dict[str, Any] | None = Field(default=None, max_length=100)
    expected_row_version: int = Field(ge=1)
    reason: ChangeReason

    @field_validator("extensions")
    @classmethod
    def validate_extensions(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        conflicts = sorted(RESERVED_PROFILE_KEYS.intersection(value))
        if conflicts:
            raise ValueError(f"扩展字段与保留字段冲突：{', '.join(conflicts)}")
        return value

    @model_validator(mode="after")
    def validate_change(self):
        values = (
            self.credit_code,
            self.name,
            self.counterparty_type,
            self.industry,
            self.cooperation_status,
            self.is_key_counterparty,
            self.requested_limit,
            self.current_limit,
            self.current_payment_term_days,
            self.current_rating,
            self.current_segment,
            self.external,
            self.internal,
            self.financial,
            self.extensions,
        )
        if not any(value is not None for value in values) and not self.clear_current_rating and not self.clear_current_segment:
            raise ValueError("至少提供一项客商主数据变更")
        if self.current_rating is not None and self.clear_current_rating:
            raise ValueError("current_rating 与 clear_current_rating 不能同时设置")
        if self.current_segment is not None and self.clear_current_segment:
            raise ValueError("current_segment 与 clear_current_segment 不能同时设置")
        return self


class CounterpartyArchive(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_row_version: int = Field(ge=1)
    reason: ChangeReason


class CounterpartyView(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    tenant_id: str
    name: str
    credit_code: str
    counterparty_type: str
    industry: str
    cooperation_status: str
    is_key_counterparty: bool
    requested_limit: float
    current_limit: float
    current_payment_term_days: int
    current_rating: str | None
    current_segment: str | None
    external: dict[str, Any]
    internal: dict[str, Any]
    financial: dict[str, Any]
    status: str
    source_type: str
    profile_hash: str
    row_version: int
    archived_at: str | None
    archived_by: str | None
    archive_reason: str | None
    created_at: str | None
    updated_at: str | None


class CounterpartyPage(BaseModel):
    items: list[CounterpartyView]
    total: int
    limit: int
    offset: int


class CounterpartyHistoryEvent(BaseModel):
    id: str
    event_type: Literal["counterparty_created", "counterparty_updated", "counterparty_archived"]
    actor: str
    actor_name: str
    reason: str
    changed_fields: list[str]
    row_version: int | None
    previous_hash: str
    event_hash: str
    created_at: str | None


class CounterpartyImportPrecheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    import_key: ImportIdentifier
    file_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    file_format: Literal["json", "csv"]
    content: Annotated[str, StringConstraints(min_length=2, max_length=2 * 1024 * 1024)]
    duplicate_strategy: Literal["reject", "skip", "update"] = "reject"
    field_mapping: dict[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)],
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)],
    ] = Field(default_factory=dict, max_length=200)
    reason: ChangeReason

    @field_validator("field_mapping")
    @classmethod
    def validate_field_mapping(cls, value: dict[str, str]) -> dict[str, str]:
        allowed_core = {
            "id", "counterparty_id", "credit_code", "name", "counterparty_type", "industry",
            "cooperation_status", "is_key_counterparty", "requested_limit", "current_limit",
            "current_payment_term_days", "current_rating", "current_segment", "external", "internal",
            "financial", "extensions",
        }
        invalid = sorted(
            target for target in value.values()
            if target not in allowed_core and not target.startswith(("external.", "internal.", "financial.", "extensions."))
        )
        if invalid:
            raise ValueError(f"字段映射包含不支持的目标：{', '.join(invalid[:5])}")
        normalized_targets = ["counterparty_id" if target == "id" else target for target in value.values()]
        if len(normalized_targets) != len(set(normalized_targets)):
            raise ValueError("多个源字段不能映射到同一目标字段")
        return value


class CounterpartyImportCommit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_row_version: int = Field(ge=1)
    preview_hash: Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, pattern=r"^[0-9a-f]{64}$")]
    reason: ChangeReason


class CounterpartyImportView(BaseModel):
    id: str
    tenant_id: str
    import_key: str
    file_name: str
    file_format: str
    duplicate_strategy: str
    field_mapping: dict[str, str]
    source_hash: str
    request_hash: str
    preview_hash: str
    status: str
    total_count: int
    valid_count: int
    invalid_count: int
    create_count: int
    update_count: int
    skip_count: int
    committed_count: int
    row_receipts: list[dict[str, Any]]
    precheck_reason: str
    commit_reason: str | None
    created_by: str
    created_by_name: str
    committed_by: str | None
    committed_by_name: str | None
    committed_at: str | None
    row_version: int
    created_at: str | None
    updated_at: str | None
    idempotent: bool = False


class CounterpartyImportPage(BaseModel):
    items: list[CounterpartyImportView]
    total: int
    limit: int
    offset: int


class CounterpartyImportCorrectionDraft(BaseModel):
    source_batch_id: str
    source_import_key: str
    source_hash: str
    suggested_import_key: str
    file_name: str
    file_format: Literal["json", "csv"]
    content: str
    duplicate_strategy: Literal["reject", "skip", "update"]
    field_mapping: dict[str, str]


class CounterpartyImportMappingTemplateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_key: MappingTemplateIdentifier
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=255)]
    file_format: Literal["json", "csv"]
    mapping: dict[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)],
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)],
    ] = Field(default_factory=dict, max_length=200)
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]
    reason: ChangeReason

    @field_validator("mapping")
    @classmethod
    def validate_mapping(cls, value: dict[str, str]) -> dict[str, str]:
        return CounterpartyImportPrecheck.validate_field_mapping(value)


class CounterpartyImportMappingTemplateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=255)] | None = None
    file_format: Literal["json", "csv"] | None = None
    mapping: dict[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)],
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)],
    ] | None = Field(default=None, max_length=200)
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)] | None = None
    expected_row_version: int = Field(ge=1)
    reason: ChangeReason

    @field_validator("mapping")
    @classmethod
    def validate_mapping(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        return None if value is None else CounterpartyImportPrecheck.validate_field_mapping(value)

    @model_validator(mode="after")
    def validate_change(self):
        if self.name is None and self.file_format is None and self.mapping is None and self.description is None:
            raise ValueError("至少提供一项字段映射模板变更")
        return self


class CounterpartyImportMappingTemplateArchive(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_row_version: int = Field(ge=1)
    reason: ChangeReason


class CounterpartyImportMappingTemplateView(BaseModel):
    id: str
    tenant_id: str
    template_key: str
    name: str
    file_format: Literal["json", "csv"]
    mapping: dict[str, str]
    mapping_hash: str
    description: str
    status: Literal["active", "archived"]
    created_by: str
    updated_by: str
    row_version: int
    created_at: str | None
    updated_at: str | None
