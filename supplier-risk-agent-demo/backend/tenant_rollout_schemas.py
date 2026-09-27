"""Contracts for tenant-scoped Champion/Challenger rollout governance."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=255)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=2000)]


class RolloutThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_challenger_failure_rate: float = Field(default=0.05, ge=0, le=1)
    max_latency_increase_ratio: float = Field(default=0.50, ge=0, le=10)
    max_score_psi: float = Field(default=0.25, ge=0, le=10)
    max_admission_distribution_shift: float = Field(default=0.15, ge=0, le=1)
    min_auc: float | None = Field(default=None, ge=0, le=1)
    min_ks: float | None = Field(default=None, ge=0, le=1)


class RolloutPolicyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    comparison_run_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=36)]
    routing_key_field: Literal["counterparty_id"] = "counterparty_id"
    traffic_basis_points: int = Field(default=1000, ge=1, le=9999)
    observation_window_minutes: int = Field(default=1440, ge=5, le=43200)
    min_sample_size: int = Field(default=100, ge=2, le=1000000)
    thresholds: RolloutThresholds = Field(default_factory=RolloutThresholds)
    starts_at: datetime
    ends_at: datetime
    reason: Reason

    @model_validator(mode="after")
    def validate_window(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("灰度结束时间必须晚于开始时间")
        return self


class RolloutVersionAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_row_version: int = Field(ge=1)
    reason: Reason


class RolloutReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_row_version: int = Field(ge=1)
    decision: Literal["approve", "reject"]
    comment: Reason


class RolloutStatusAction(RolloutVersionAction):
    action: Literal["activate", "pause", "resume", "rollback", "complete"]


class RolloutRestartAfterRelease(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_row_version: int = Field(ge=1)
    model_change_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=36)]
    reason: Reason


class RolloutIncidentAction(RolloutVersionAction):
    action: Literal["acknowledge", "request_resolution", "approve_resolution"]


class RolloutPolicyView(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    tenant_id: str
    name: str
    status: str
    effective_status: str
    champion: dict
    challenger: dict
    comparison: dict
    routing_key_field: str
    traffic_basis_points: int
    traffic_percent: float
    observation_window_minutes: int
    min_sample_size: int
    thresholds: dict
    config_hash: str
    assets_hash: str
    starts_at: str
    ends_at: str
    row_version: int


class RolloutEvaluationView(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    tenant_id: str
    policy_id: str
    trigger_type: str
    sample_count: int
    evidence_level: str
    metrics: dict
    gate: dict
    action: str
    evidence_hash: str


class OutcomeLabelCreate(BaseModel):
    """Observed fact only; prediction attributes are derived from frozen routing evidence."""

    model_config = ConfigDict(extra="forbid")

    source: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128)]
    label_definition_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=36)]
    external_label_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=128)]
    routing_decision_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=36)]
    counterparty_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128)]
    observed_event: bool
    observation_end: datetime
    loss_amount: float | None = Field(default=None, ge=0, le=1_000_000_000_000)
    exposure_amount: float | None = Field(default=None, gt=0, le=1_000_000_000_000)
    evidence_reference: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=1000)]


class OutcomeLabelVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_row_version: int = Field(ge=1)
    decision: Literal["verify", "reject"]
    note: Reason


class OutcomeLabelImportRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_label_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=128)]
    routing_decision_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=36)]
    counterparty_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128)]
    observed_event: bool
    observation_end: datetime
    loss_amount: float | None = Field(default=None, ge=0, le=1_000_000_000_000)
    exposure_amount: float | None = Field(default=None, gt=0, le=1_000_000_000_000)
    evidence_reference: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=1000)]


class OutcomeImportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    import_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=160)]
    source: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128)]
    label_definition_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=36)]
    expected_count: int = Field(ge=1, le=500)
    outcomes: list[OutcomeLabelImportRow] = Field(min_length=1, max_length=500)


class OutcomeLabelCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_row_version: int = Field(ge=1)
    external_label_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=128)]
    observed_event: bool
    observation_end: datetime
    loss_amount: float | None = Field(default=None, ge=0, le=1_000_000_000_000)
    exposure_amount: float | None = Field(default=None, gt=0, le=1_000_000_000_000)
    evidence_reference: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=1000)]
    reason: Reason


class SupervisedEvaluationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evaluation_as_of: datetime | None = None
    tenant_monitoring_run_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=36)] | None = None
    label_definition_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=36)] | None = None
    min_mature_samples: int = Field(default=30, ge=2, le=1_000_000)
    min_events: int = Field(default=5, ge=1, le=1_000_000)
    min_non_events: int = Field(default=5, ge=1, le=1_000_000)
    min_reliable_samples_per_arm: int = Field(default=30, ge=2, le=1_000_000)
    high_risk_threshold: float = Field(default=0.40, ge=0, le=1)
    bootstrap_resamples: int = Field(default=1000, ge=200, le=5000)


class TenantMonitoringRunCreate(BaseModel):
    """Tenant-native monitoring snapshot; never falls back to shared platform runs."""

    model_config = ConfigDict(extra="forbid")

    run_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=160)]
    model_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=64)]
    model_version: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    observed_from: datetime
    observed_to: datetime
    dataset_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=160)]
    evidence_level: Literal["supervised", "non_supervised"] = "non_supervised"
    status: Literal["completed", "failed", "cancelled"] = "completed"
    label_definition_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=36)] | None = None
    label_definition_version: int | None = Field(default=None, ge=1)
    label_definition_hash: Annotated[str, StringConstraints(strip_whitespace=True, min_length=64, max_length=64)] | None = None
    label_watermark: dict = Field(default_factory=dict)
    monitoring: dict = Field(default_factory=dict)


class TenantMonitoringGenerate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label_definition_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=36)]
    as_of: datetime | None = None


class TenantMonitoringRunSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_row_version: int = Field(ge=1)
    note: Reason


class TenantMonitoringRunReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_row_version: int = Field(ge=1)
    decision: Literal["approve", "reject"]
    comment: Reason


class TenantMonitoringRunRetraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_row_version: int = Field(ge=1)
    reason: Reason


class TenantMonitoringDiffCaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_run_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=36)]
    against_run_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=36)]
    reason: Reason
    severity: Literal["info", "warning", "critical"] | None = None
    assigned_role: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=64)] = "risk_manager"
    due_at: datetime | None = None


class TenantMonitoringDiffCaseAssign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_row_version: int = Field(ge=1)
    assigned_to: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128)] | None = None
    assigned_to_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128)] | None = None
    due_at: datetime | None = None
    reason: Reason


class TenantMonitoringDiffCaseRecompute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_row_version: int = Field(ge=1)
    reason: Reason


class TenantMonitoringDiffCaseDisposition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_row_version: int = Field(ge=1)
    disposition: Literal[
        "accepted_change", "data_issue", "calculation_issue", "model_drift",
        "policy_threshold_change_required", "superseded",
    ]
    conclusion: Reason


class SupervisedEvaluationSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_row_version: int = Field(ge=1)
    note: Reason


class SupervisedEvaluationReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_row_version: int = Field(ge=1)
    decision: Literal["approve", "reject"]
    governance_decision: Literal["retain_champion", "promote_candidate", "reject_candidate", "continue_observation"] | None = None
    comment: Reason

    @model_validator(mode="after")
    def validate_governance_decision(self):
        if self.decision == "approve" and self.governance_decision is None:
            raise ValueError("批准监督结论时必须选择治理意见")
        if self.decision == "reject" and self.governance_decision is not None:
            raise ValueError("驳回监督结论时不能设置治理意见")
        return self


class OutcomeLabelDefinitionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]+$")]
    name: Name
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]
    event_type: Literal["default", "delinquency", "loss", "recovery"]
    event_threshold: dict = Field(default_factory=dict)
    observation_window_days: int = Field(ge=1, le=3650)
    maturity_grace_days: int = Field(default=0, ge=0, le=365)
    source_priorities: list[dict] = Field(min_length=1, max_length=50)
    applicable_model_keys: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=64)]] = Field(min_length=1, max_length=50)
    require_loss_amount: bool = False
    require_exposure_amount: bool = False

    @model_validator(mode="after")
    def validate_sources(self):
        sources: list[str] = []
        priorities: list[int] = []
        for item in self.source_priorities:
            source = str(item.get("source") or "").strip()
            priority = item.get("priority")
            if len(source) < 2 or not isinstance(priority, int) or isinstance(priority, bool) or priority < 1:
                raise ValueError("来源优先级必须包含有效的 source 和正整数 priority")
            sources.append(source)
            priorities.append(priority)
        if len(set(sources)) != len(sources) or len(set(priorities)) != len(priorities):
            raise ValueError("来源名称和优先级不能重复")
        if len(set(self.applicable_model_keys)) != len(self.applicable_model_keys):
            raise ValueError("适用模型不能重复")
        return self


class OutcomeLabelDefinitionUpdate(OutcomeLabelDefinitionCreate):
    expected_row_version: int = Field(ge=1)


class OutcomeLabelDefinitionAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_row_version: int = Field(ge=1)
    note: Reason


class OutcomeLabelDefinitionReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_row_version: int = Field(ge=1)
    decision: Literal["approve", "reject"]
    comment: Reason


class SupervisedUpgradeDraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_evidence_hash: Annotated[str, StringConstraints(strip_whitespace=True, min_length=64, max_length=64)]
    change_reason: Reason
