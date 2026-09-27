from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


class RatingRequest(BaseModel):
    counterparty_id: str
    template_key: str = "general"


DecisionIdentifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=4,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    ),
]

TenantAssetVersion = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=9,
        max_length=128,
        pattern=r"^tenant-v[1-9][0-9]*$",
    ),
]
PlatformAssetVersion = Annotated[int, Field(ge=1)]
RuntimeAssetVersion = PlatformAssetVersion | TenantAssetVersion


class DecisionAssetSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=64)] = "general"
    model_version: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)] | None = None
    pipeline_code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128)] | None = None
    pipeline_version: RuntimeAssetVersion | None = None
    rule_set_versions: dict[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)], RuntimeAssetVersion] = Field(default_factory=dict, max_length=50)
    rule_versions: dict[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)], RuntimeAssetVersion] = Field(default_factory=dict, max_length=500)


class DecisionRequestMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    source_system: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)] = "sandbox"
    scenario: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)] = "enterprise_credit"


class DecisionExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: DecisionIdentifier
    counterparty_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)] | None = None
    input: dict[str, Any] | None = None
    assets: DecisionAssetSelection = Field(default_factory=DecisionAssetSelection)
    metadata: DecisionRequestMetadata = Field(default_factory=DecisionRequestMetadata)

    @model_validator(mode="after")
    def validate_input_source(self):
        if (self.counterparty_id is None) == (self.input is None):
            raise ValueError("counterparty_id 与 input 必须且只能提供一个")
        return self


class DecisionJobCallback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["none", "sandbox"] = "none"
    endpoint_url: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""
    secret_reference: Annotated[str, StringConstraints(strip_whitespace=True, max_length=256)] = ""
    simulate_status_sequence: list[int] = Field(default_factory=lambda: [200], min_length=1, max_length=10)
    max_attempts: int = Field(default=3, ge=1, le=10)

    @model_validator(mode="after")
    def validate_callback(self):
        if self.mode == "sandbox":
            if not self.endpoint_url.startswith("sandbox://"):
                raise ValueError("沙箱回调地址必须使用 sandbox:// 协议")
            if not self.secret_reference:
                raise ValueError("沙箱回调必须提供 secret_reference")
        if any(status < 100 or status > 599 for status in self.simulate_status_sequence):
            raise ValueError("模拟状态码必须在 100 到 599 之间")
        return self


class DecisionJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_key: DecisionIdentifier
    requests: list[DecisionExecuteRequest] = Field(min_length=1, max_length=100)
    callback: DecisionJobCallback = Field(default_factory=DecisionJobCallback)

    @model_validator(mode="after")
    def validate_unique_request_ids(self):
        request_ids = [item.request_id for item in self.requests]
        if len(request_ids) != len(set(request_ids)):
            raise ValueError("同一批次内 request_id 不允许重复")
        return self


class DecisionFieldMappingItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_field: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)]
    target_path: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)]
    enum_mapping: dict[str, str] = Field(default_factory=dict, max_length=200)
    multiplier: float = Field(default=1, ge=-1_000_000, le=1_000_000)
    default_value: Any | None = None
    required: bool = False


class DecisionFieldMappingPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: dict[str, Any]
    mappings: list[DecisionFieldMappingItem] = Field(min_length=1, max_length=500)


class ModelImpactRequest(RatingRequest):
    field_path: str
    new_value: float | int


class PortfolioRatingBatchCreate(BaseModel):
    batch_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=128)]
    template_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=64)] = "general"
    counterparty_type: Literal["all", "supplier", "customer"] = "all"


class ModelIndicatorSelection(BaseModel):
    indicator_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=4, max_length=64)]
    weight: float = Field(default=1, gt=0, le=100)
    enabled: bool = True


class ScorecardBin(BaseModel):
    kind: Literal["range", "category", "missing"]
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    score: float
    woe: float | None = None
    lower: float | None = None
    upper: float | None = None
    lower_inclusive: bool = True
    upper_inclusive: bool = False
    values: list[str] | None = Field(default=None, max_length=200)


class ScorecardIndicatorBinding(BaseModel):
    indicator_code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    indicator_version: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    indicator_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)]
    field_path: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]
    data_type: Literal["numeric", "categorical", "boolean"]
    weight: float = Field(gt=0, le=1000)
    bins: list[ScorecardBin] = Field(min_length=2, max_length=200)


class ScorecardDefinitionPayload(BaseModel):
    code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128, pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")]
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=256)]
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=2000)]
    score_scale: dict[str, float | bool]
    indicators: list[ScorecardIndicatorBinding] = Field(min_length=1, max_length=250)


class ScorecardChangeCreate(BaseModel):
    definition: ScorecardDefinitionPayload
    change_reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]


class ScorecardChangeUpdate(BaseModel):
    expected_row_version: int = Field(ge=1)
    definition: ScorecardDefinitionPayload
    change_reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]


class ScorecardChangeReview(BaseModel):
    expected_row_version: int = Field(ge=1)
    decision: Literal["publish", "reject"]
    comment: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]


class ScorecardDevelopmentExclusionRule(BaseModel):
    field_path: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]
    operator: Literal["equals", "not_equals", "in", "is_missing", "not_missing"]
    value: Any = None
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=256)]


class ScorecardValidationThresholds(BaseModel):
    require_validation_snapshot: bool = True
    require_oot_snapshot: bool = True
    require_probability_evidence: bool = False
    require_sensitive_attribute_evidence: bool = False
    min_auc: float = Field(default=0.6, ge=0, le=1)
    min_ks: float = Field(default=0.2, ge=0, le=1)
    max_brier: float = Field(default=0.25, ge=0, le=1)
    max_score_psi: float = Field(default=0.25, ge=0, le=10)
    min_segment_coverage: float = Field(default=0.8, ge=0, le=1)
    max_event_rate_gap: float = Field(default=0.2, ge=0, le=1)
    max_average_score_gap: float = Field(default=15, ge=0, le=100)
    max_auc_gap: float = Field(default=0.15, ge=0, le=1)
    max_ks_gap: float = Field(default=0.15, ge=0, le=1)
    max_false_positive_rate_gap: float = Field(default=0.15, ge=0, le=1)
    max_false_negative_rate_gap: float = Field(default=0.15, ge=0, le=1)


class ScorecardValidationPolicyPayload(BaseModel):
    code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")]
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=256)]
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=2000)]
    applicable_scorecard_codes: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128)]] = Field(default_factory=list, max_length=100)
    is_default: bool = False
    thresholds: ScorecardValidationThresholds


class ScorecardValidationPolicyCreate(BaseModel):
    policy: ScorecardValidationPolicyPayload
    change_reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]


class ScorecardValidationPolicyUpdate(ScorecardValidationPolicyCreate):
    expected_row_version: int = Field(ge=1)


class ScorecardMonitoringSlaRule(BaseModel):
    response_hours: int = Field(ge=1, le=720)
    due_soon_ratio: float = Field(default=0.25, ge=0.05, le=0.9)
    escalation_after_hours: int = Field(default=4, ge=1, le=168)


class ScorecardMonitoringSlaPolicyPayload(BaseModel):
    code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")]
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=256)]
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=2000)]
    applicable_scorecard_codes: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128)]] = Field(default_factory=list, max_length=100)
    applicable_event_types: list[Literal["gate_failed", "consecutive_deterioration", "evidence_integrity_failed", "policy_integrity_failed", "scheduled_run_failed"]] = Field(default_factory=list, max_length=5)
    is_default: bool = False
    severity_rules: dict[Literal["critical", "warning"], ScorecardMonitoringSlaRule]


class ScorecardMonitoringSlaPolicyCreate(BaseModel):
    policy: ScorecardMonitoringSlaPolicyPayload
    change_reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]


class ScorecardMonitoringSlaPolicyUpdate(ScorecardMonitoringSlaPolicyCreate):
    expected_row_version: int = Field(ge=1)


class ScorecardDevelopmentRunCreate(BaseModel):
    scorecard_asset_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=36)]
    validation_policy_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=36)] | None = None
    dataset_snapshot_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=36)]
    validation_snapshot_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=36)] | None = None
    oot_snapshot_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=36)] | None = None
    subject_id_field: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)] = "id"
    predicted_probability_field: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)] | None = None
    segment_fields: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]] = Field(default_factory=list, max_length=10)
    sensitive_attribute_fields: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]] = Field(default_factory=list, max_length=10)
    min_segment_sample_count: int = Field(default=30, ge=2, le=5000)
    classification_threshold: float = Field(default=0.5, ge=0, le=1)
    validation_thresholds: ScorecardValidationThresholds = Field(default_factory=ScorecardValidationThresholds)
    positive_labels: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]] = Field(min_length=1, max_length=20)
    observation_start: date | None = None
    observation_end: date | None = None
    performance_window_days: int = Field(default=180, ge=1, le=3650)
    maturity_days: int = Field(default=90, ge=0, le=3650)
    min_sample_count: int = Field(default=100, ge=1, le=5000)
    min_event_count: int = Field(default=20, ge=1, le=5000)
    min_non_event_count: int = Field(default=20, ge=1, le=5000)
    exclusion_rules: list[ScorecardDevelopmentExclusionRule] = Field(default_factory=list, max_length=50)


class CreditCalibrationCandidate(BaseModel):
    score_threshold_shift: float = Field(default=0, ge=-5, le=5)
    limit_multiplier_scale: float = Field(default=1, ge=0.1, le=2)
    revenue_limit_scale: float = Field(default=1, ge=0.1, le=2)
    order_amount_scale: float = Field(default=1, ge=0.1, le=2)
    payment_term_scale: float = Field(default=1, ge=0.5, le=1.5)
    overdue_rate_high: float = Field(default=0.15, ge=0, le=1)
    limit_utilization_high: float = Field(default=0.9, ge=0, le=1)
    invoice_match_rate_low: float = Field(default=0.85, ge=0, le=1)
    delivery_fulfillment_rate_low: float = Field(default=0.9, ge=0, le=1)


class CreditCalibrationAnalyze(BaseModel):
    dataset_snapshot_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=36)]
    template_key: Literal["corporate_credit_v2"] = "corporate_credit_v2"
    positive_labels: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]] = Field(default_factory=lambda: ["bad", "default", "reject"], min_length=1, max_length=20)
    sample_limit: int = Field(default=500, ge=1, le=1000)
    candidate: CreditCalibrationCandidate = Field(default_factory=CreditCalibrationCandidate)


class CreditCalibrationModelChangeCreate(CreditCalibrationAnalyze):
    candidate_version: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=128)]
    change_reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]
    expected_evidence_hash: Annotated[str, StringConstraints(strip_whitespace=True, min_length=64, max_length=64)]


class CreditCalibrationPlanCreate(BaseModel):
    code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=256)]
    template_key: Literal["corporate_credit_v2"] = "corporate_credit_v2"
    candidate: CreditCalibrationCandidate = Field(default_factory=CreditCalibrationCandidate)
    positive_labels: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]] = Field(default_factory=lambda: ["bad", "default", "reject"], min_length=1, max_length=20)
    sample_limit: int = Field(default=500, ge=1, le=1000)
    business_basis: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=2000)]


class CreditCalibrationPlanUpdate(CreditCalibrationPlanCreate):
    expected_row_version: int = Field(ge=1)


class CreditCalibrationPlanRun(BaseModel):
    expected_row_version: int = Field(ge=1)
    dataset_snapshot_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=36)]


class CreditCalibrationPlanReview(BaseModel):
    expected_row_version: int = Field(ge=1)
    decision: Literal["approve", "reject"]
    comment: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]


class CreditCalibrationPlanModelChange(BaseModel):
    expected_row_version: int = Field(ge=1)
    run_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=36)]
    candidate_version: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=128)]
    change_reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]


class CreditCalibrationComparisonRequest(BaseModel):
    plan_ids: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=36)]] = Field(min_length=2, max_length=5)


class ScorecardDevelopmentRunReview(BaseModel):
    expected_row_version: int = Field(ge=1)
    decision: Literal["approve", "reject"]
    comment: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]


class ScorecardMonitoringRunConfig(BaseModel):
    subject_id_field: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)] = "id"
    predicted_probability_field: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)] | None = None
    segment_fields: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]] = Field(default_factory=list, max_length=10)
    sensitive_attribute_fields: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]] = Field(default_factory=list, max_length=10)
    min_segment_sample_count: int = Field(default=30, ge=2, le=5000)
    classification_threshold: float = Field(default=0.5, ge=0, le=1)
    positive_labels: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]] = Field(min_length=1, max_length=20)
    performance_window_days: int = Field(default=180, ge=1, le=3650)
    maturity_days: int = Field(default=90, ge=0, le=3650)
    min_sample_count: int = Field(default=100, ge=1, le=5000)
    min_event_count: int = Field(default=20, ge=1, le=5000)
    min_non_event_count: int = Field(default=20, ge=1, le=5000)
    exclusion_rules: list[ScorecardDevelopmentExclusionRule] = Field(default_factory=list, max_length=50)


class ScorecardMonitoringPlanPayload(BaseModel):
    code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128, pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")]
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=256)]
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=2000)]
    scorecard_asset_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=36)]
    validation_policy_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=36)]
    training_dataset_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=36)]
    validation_dataset_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=36)] | None = None
    oot_dataset_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=36)] | None = None
    run_config: ScorecardMonitoringRunConfig
    cadence: Literal["monthly", "quarterly"] = "monthly"
    timezone_name: Literal["Asia/Shanghai", "UTC"] = "Asia/Shanghai"
    enabled: bool = True
    next_run_at: datetime
    owner: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128)]


class ScorecardMonitoringPlanCreate(BaseModel):
    plan: ScorecardMonitoringPlanPayload


class ScorecardMonitoringPlanUpdate(ScorecardMonitoringPlanCreate):
    expected_row_version: int = Field(ge=1)


class ScorecardMonitoringPlanRunRequest(BaseModel):
    expected_row_version: int = Field(ge=1)


class ScorecardMonitoringTickRequest(BaseModel):
    as_of: datetime | None = None
    max_plans: int = Field(default=50, ge=1, le=200)
    run_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")] | None = None
    trigger_type: Literal["manual", "scheduler"] = "manual"


class ScorecardMonitoringSchedulerRetryRequest(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]
    max_plans: int = Field(default=50, ge=1, le=200)


class ScorecardMonitoringEventAction(BaseModel):
    expected_row_version: int = Field(ge=1)
    action: Literal["assign", "acknowledge", "remediate", "submit_revalidation", "review_revalidation"]
    assignee: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128)] | None = None
    remediation_plan: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=2000)] | None = None
    remediation_result: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=2000)] | None = None
    revalidation_run_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=36)] | None = None
    decision: Literal["pass", "fail"] | None = None
    conclusion: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=2000)] | None = None


class ScorecardMonitoringEventFilters(BaseModel):
    status: Literal["open", "acknowledged", "in_remediation", "pending_revalidation", "closed"] | None = None
    severity: Literal["critical", "warning"] | None = None
    event_type: Literal["gate_failed", "consecutive_deterioration", "evidence_integrity_failed", "policy_integrity_failed", "scheduled_run_failed"] | None = None
    assignee: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)] | None = None
    plan_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=36)] | None = None
    scorecard_code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)] | None = None
    sla_status: Literal["normal", "due_soon", "overdue", "escalated"] | None = None


class ScorecardMonitoringBulkAssignItem(BaseModel):
    event_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=36)]
    expected_row_version: int = Field(ge=1)


class ScorecardMonitoringBulkAssignRequest(BaseModel):
    items: list[ScorecardMonitoringBulkAssignItem] = Field(min_length=1, max_length=100)
    assignee: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128)]
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]


class ScorecardMonitoringSavedViewPayload(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128)]
    filters: ScorecardMonitoringEventFilters
    is_default: bool = False


class ScorecardMonitoringSavedViewUpdate(ScorecardMonitoringSavedViewPayload):
    expected_row_version: int = Field(ge=1)


class RiskScreeningPolicyAction(BaseModel):
    rating_notch_down: int = Field(default=0, ge=0, le=3)
    limit_cap_ratio: float = Field(default=1, ge=0, le=1)
    term_cap_days: int = Field(default=3650, ge=0, le=3650)
    access_strategy: Literal["正常准入", "优先准入", "审慎准入", "人工复核", "限制准入", "禁入"]
    monitoring_frequency: Literal["年度", "半年度", "季度", "月度", "周度", "实时监控"]


class RiskScreeningPolicyRule(BaseModel):
    id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=64)]
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128)]
    enabled: bool = True
    metric: Literal["normalized_score", "completeness", "critical_indicator_count", "missing_count"]
    operator: Literal["<", "<=", ">", ">=", "=="]
    value: float
    action: RiskScreeningPolicyAction


class RiskScreeningPolicy(BaseModel):
    enabled: bool = True
    aggregation: Literal["most_restrictive"] = "most_restrictive"
    rules: list[RiskScreeningPolicyRule] = Field(min_length=1, max_length=50)


class ModelChangeCreate(BaseModel):
    template_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=64)]
    candidate_version: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=128)]
    change_reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]
    weights: dict[str, float]
    thresholds: dict[str, float]
    strong_rules: list[dict[str, Any]]
    strategy_mapping: list[dict[str, Any]] | None = None
    indicator_selection: list[ModelIndicatorSelection] | None = Field(default=None, max_length=250)
    risk_screening_policy: RiskScreeningPolicy | None = None
    scorecard_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=36)] | None = None
    scorecard_validation_run_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=36)] | None = None


class VersionedActionRequest(BaseModel):
    expected_row_version: int = Field(ge=1)


class ModelChangeUpdate(VersionedActionRequest):
    change_reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]
    weights: dict[str, float]
    thresholds: dict[str, float]
    strong_rules: list[dict[str, Any]]
    strategy_mapping: list[dict[str, Any]] | None = None
    indicator_selection: list[ModelIndicatorSelection] | None = Field(default=None, max_length=250)
    risk_screening_policy: RiskScreeningPolicy | None = None
    scorecard_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=36)] | None = None
    scorecard_validation_run_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=36)] | None = None


class ModelReviewRequest(VersionedActionRequest):
    decision: Literal["publish", "reject"]
    comment: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=1000)]


class SupervisedValidationAttachment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attachment_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=36, max_length=36)] | None = None
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=255)]
    reference: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=1000)]
    sha256: Annotated[str, StringConstraints(strip_whitespace=True, min_length=64, max_length=64)]


class SupervisedValidationReview(VersionedActionRequest):
    model_config = ConfigDict(extra="forbid")

    expected_binding_hash: Annotated[str, StringConstraints(strip_whitespace=True, min_length=64, max_length=64)]
    decision: Literal["approve", "reject"]
    risk_level: Literal["low", "medium", "high"]
    opinion: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=2000)]
    report_template_version: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)] = "supervised-model-validation-v2"
    attachments: list[SupervisedValidationAttachment] = Field(default_factory=list, max_length=20)


class ModelValidationIssuanceAction(VersionedActionRequest):
    model_config = ConfigDict(extra="forbid")

    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=1000)]


class ModelValidationAttachmentScan(VersionedActionRequest):
    model_config = ConfigDict(extra="forbid")

    scan_status: Literal["pending", "passed", "rejected"]
    scan_engine: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128)]
    result_reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=1000)]


class ModelRiskPolicyLevelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=32)]
    level: Literal["low", "medium", "high"]
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=64)]
    basis: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)]] = Field(min_length=1, max_length=10)
    acceptance_roles: list[Literal["model_owner", "risk_manager", "model_risk_committee"]] = Field(min_length=1, max_length=3)
    review_days: int = Field(ge=30, le=730)
    regulatory_mapping: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128)]] = Field(default_factory=list, max_length=20)
    required_evidence: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128)]] = Field(min_length=1, max_length=20)


class ModelRiskPolicyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=255)]
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=2000)]
    levels: list[ModelRiskPolicyLevelConfig] = Field(min_length=3, max_length=3)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]


class ModelRiskPolicyReview(VersionedActionRequest):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["publish", "reject"]
    comment: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]


class ModelRiskPolicySubmit(VersionedActionRequest):
    model_config = ConfigDict(extra="forbid")

    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]


class ModelRiskAcceptanceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rationale: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=2000)]


class ModelRiskAcceptanceSign(VersionedActionRequest):
    model_config = ConfigDict(extra="forbid")

    acceptance_role: Literal["model_owner", "risk_manager", "model_risk_committee"]
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]


class ModelRiskAcceptanceRevoke(VersionedActionRequest):
    model_config = ConfigDict(extra="forbid")

    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=1000)]


class ModelRiskReacceptanceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rationale: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=2000)]
    observed_from: date
    observed_to: date
    evidence_reference: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=512)]
    evidence_summary: Annotated[str, StringConstraints(strip_whitespace=True, min_length=20, max_length=4000)]
    monitoring_run_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=36)] | None = None
    monitoring_evidence_hash: Annotated[str, StringConstraints(strip_whitespace=True, min_length=64, max_length=64)] | None = None
    label_evidence_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=128)] | None = None
    supervised_evaluation_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=36, max_length=36)] | None = None
    supervised_evidence_hash: Annotated[str, StringConstraints(strip_whitespace=True, min_length=64, max_length=64)] | None = None

    @model_validator(mode="after")
    def check_observation_window(self) -> "ModelRiskReacceptanceCreate":
        if self.observed_to < self.observed_from:
            raise ValueError("运行观察结束日期不能早于开始日期")
        if (self.observed_to - self.observed_from).days > 730:
            raise ValueError("运行观察窗口不能超过 730 天")
        return self


class ModelRiskReacceptanceSign(VersionedActionRequest):
    model_config = ConfigDict(extra="forbid")

    acceptance_role: Literal["model_owner", "risk_manager", "model_risk_committee"]
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]


class ModelRiskReacceptanceRevoke(VersionedActionRequest):
    model_config = ConfigDict(extra="forbid")

    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=1000)]


class ModelRiskReviewSavedViewCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    filters: dict = Field(default_factory=dict)
    is_default: bool = False


class ModelRiskReviewSavedViewUpdate(ModelRiskReviewSavedViewCreate, VersionedActionRequest):
    pass


class ModelRiskReviewBulkAssignmentItem(BaseModel):
    item_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=192)]
    expected_assignment_version: int = Field(default=0, ge=0)
    expected_source_version: int | None = Field(default=None, ge=1)


class ModelRiskReviewBulkAssignment(BaseModel):
    items: list[ModelRiskReviewBulkAssignmentItem] = Field(min_length=1, max_length=50)
    assignee: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)] | None = None
    assignee_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)] | None = None
    assigned_role: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=64)]
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]


class ModelRiskReviewDelegationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_subject: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    delegate_subject: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    assigned_role: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=64)]
    starts_at: datetime
    ends_at: datetime
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]


class ModelRiskReviewDelegationRevoke(VersionedActionRequest):
    model_config = ConfigDict(extra="forbid")

    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]


class TenantNotificationChannelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128)]
    delivery_mode: Literal["sandbox", "live"] = "sandbox"
    endpoint_url: Annotated[str, StringConstraints(strip_whitespace=True, min_length=6, max_length=2000)]
    secret_reference: Annotated[str, StringConstraints(strip_whitespace=True, min_length=7, max_length=256)]
    subscribed_categories: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]] = Field(min_length=1, max_length=50)
    recipient_roles: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]] = Field(default_factory=list, max_length=20)
    minimum_severity: Literal["info", "warning", "critical"] = "warning"
    max_attempts: int = Field(default=3, ge=1, le=10)
    timeout_seconds: int = Field(default=5, ge=1, le=30)
    require_receipt: bool = True
    sandbox_status_sequence: list[int] = Field(default_factory=lambda: [200], min_length=1, max_length=10)
    status: Literal["active", "disabled"] = "active"


class TenantNotificationChannelCreate(TenantNotificationChannelConfig):
    pass


class TenantNotificationChannelUpdate(TenantNotificationChannelConfig, VersionedActionRequest):
    pass


class TenantNotificationDispatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=100, ge=1, le=500)


class TenantNotificationDeliveryAction(VersionedActionRequest):
    model_config = ConfigDict(extra="forbid")


class ModelRollbackRequest(BaseModel):
    comment: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=1000)]


class DocumentCheckResult(BaseModel):
    key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=64)]
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128)]
    status: Literal["pass", "fail", "not_applicable"]
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ""


class DocumentReviewRequest(VersionedActionRequest):
    decision: Literal["verify", "needs_supplement", "reject"]
    comment: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]
    checks: list[DocumentCheckResult] = Field(min_length=5, max_length=10)


class DocumentCaseLinkRequest(VersionedActionRequest):
    case_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=128)]


class RenewalDocumentCarryoverRequest(BaseModel):
    case_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=128)]
    template_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=64)] = "general"
    expected_case_row_version: int = Field(ge=1)


class DocumentCorrectionActionRequest(VersionedActionRequest):
    action: Literal["remind", "reassign", "extend"]
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]
    assigned_role: Literal["client", "relationship_manager", "risk_manager", "approver"] | None = None
    extension_hours: int | None = Field(default=None, ge=1, le=72)


class PersonalTaskAssignmentRequest(VersionedActionRequest):
    action: Literal["claim", "renew", "release"]


class SupervisorTaskReleaseRequest(VersionedActionRequest):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]


class SupervisorTaskReminderRequest(VersionedActionRequest):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]


class SlaScanRetryRequest(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]


class SlaScanLeaseReleaseRequest(BaseModel):
    expected_execution_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]


class ModelOutcomeCreate(BaseModel):
    external_observation_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=128)]
    source: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128)]
    template_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=64)]
    model_version: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    counterparty_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128)]
    population_period: Annotated[str, StringConstraints(pattern=r"^\d{4}Q[1-4]$", max_length=6)]
    predicted_score: float = Field(ge=0, le=100)
    predicted_pd: float = Field(ge=0, le=1)
    observed_event: bool
    prediction_at: datetime
    observation_end: datetime
    evidence_reference: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=1000)]


class ModelOutcomeVerificationRequest(VersionedActionRequest):
    decision: Literal["verify", "reject"]
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]


class ModelOutcomeBatchCreate(BaseModel):
    outcomes: list[ModelOutcomeCreate] = Field(min_length=1, max_length=500)


class ModelOutcomeImportCreate(BaseModel):
    import_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=256)]
    source: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128)]
    template_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=64)]
    population_period: Annotated[str, StringConstraints(pattern=r"^\d{4}Q[1-4]$", max_length=6)]
    expected_count: int = Field(ge=1, le=500)
    outcomes: list[ModelOutcomeCreate] = Field(min_length=1, max_length=500)


class ModelMonitoringRunRequest(BaseModel):
    run_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=256)]
    template_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=64)]
    as_of_period: Annotated[str, StringConstraints(pattern=r"^\d{4}Q[1-4]$", max_length=6)]
    trigger_type: Literal["manual", "scheduled"] = "manual"


class ModelMonitoringScheduleCreate(BaseModel):
    template_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=64)]
    cadence: Literal["monthly", "quarterly"]
    timezone_name: Literal["Asia/Shanghai", "UTC"] = "Asia/Shanghai"
    enabled: bool = True
    next_run_at: datetime


class ModelMonitoringScheduleUpdate(VersionedActionRequest):
    cadence: Literal["monthly", "quarterly"]
    timezone_name: Literal["Asia/Shanghai", "UTC"] = "Asia/Shanghai"
    enabled: bool = True
    next_run_at: datetime


class MonitoringSchedulerTickRequest(BaseModel):
    as_of: datetime | None = None


class MonitoringIssueLinkChangeRequest(VersionedActionRequest):
    change_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=36)]


class MonitoringRemediationRequest(VersionedActionRequest):
    owner: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128)]
    plan: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=2000)]
    due_days: int = Field(ge=1, le=180)


class MonitoringRevalidationSubmitRequest(VersionedActionRequest):
    result: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=2000)]


class MonitoringRevalidationReviewRequest(VersionedActionRequest):
    decision: Literal["pass", "fail"]
    conclusion: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=2000)]


class CreditUsageRequest(BaseModel):
    transaction_ref: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=128)]
    transaction_type: Literal["drawdown", "repayment"]
    amount: float = Field(gt=0)
    expected_row_version: int = Field(ge=1)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=1000)]


class PostCreditReviewRequest(BaseModel):
    expected_row_version: int = Field(ge=1)
    rating: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]
    next_review_days: int = Field(ge=1, le=365)
    conclusion: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=1000)]


class RiskEventCreate(BaseModel):
    external_event_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=128)]
    event_type: Literal["payment_overdue", "litigation", "business_abnormal", "negative_public_opinion", "financial_deterioration", "ownership_change", "other"]
    source: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=64)]
    severity: Literal["warning", "critical"]
    occurred_at: datetime
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=255)]
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=2000)]
    payload: dict[str, Any] = Field(default_factory=dict)


class FacilityControlRequest(BaseModel):
    expected_row_version: int = Field(ge=1)
    action: Literal["freeze", "unfreeze", "reduce_limit", "close"]
    target_limit: float | None = Field(default=None, ge=0)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=1000)]


class FacilityControlConditionCompleteRequest(BaseModel):
    expected_row_version: int = Field(ge=1)
    conclusion: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]


class FacilityControlExtensionCreateRequest(BaseModel):
    expected_condition_version: int = Field(ge=1)
    extension_days: int = Field(ge=1, le=30)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=1000)]


class FacilityControlExtensionReviewRequest(BaseModel):
    expected_extension_version: int = Field(ge=1)
    expected_condition_version: int = Field(ge=1)
    decision: Literal["approve", "reject"]
    comment: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]


class FacilityRenewalRequest(BaseModel):
    expected_row_version: int = Field(ge=1)
    requested_limit: float = Field(gt=0)
    requested_term_days: int = Field(ge=0, le=365)
    renewal_reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=1000)]


class AlertDispositionRequest(BaseModel):
    expected_alert_version: int = Field(ge=1)
    expected_facility_version: int = Field(ge=1)
    action: Literal["monitor", "freeze", "reduce_limit", "close"]
    target_limit: float | None = Field(default=None, ge=0)
    conclusion: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=1000)]


class ApprovalCaseCreate(BaseModel):
    counterparty_id: str


class CreditReportCreate(BaseModel):
    case_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=128)]


class EnterpriseFieldEvidence(BaseModel):
    reference: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=1000)] | None = None
    locator: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)] | None = None


class EnterpriseDataImportCreate(BaseModel):
    import_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=256)]
    counterparty_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128)]
    source_type: Literal["internal_erp", "official_registry", "audited_financial", "external_risk", "credit_report", "management_submission"]
    source_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=255)]
    schema_version: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=64)] = "enterprise-data-v1"
    as_of_date: date
    evidence_reference: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=2000)]
    payload: dict[str, Any]
    field_evidence: dict[str, EnterpriseFieldEvidence] = Field(default_factory=dict)


class EnterpriseDataResolutionCreate(BaseModel):
    counterparty_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128)]
    field_path: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]
    selected_field_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=64)]
    reason_category: Literal["source_confirmation", "document_verification", "system_of_record", "manual_investigation"]
    rationale: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=2000)]


class EnterpriseDataResolutionReview(BaseModel):
    expected_row_version: int = Field(ge=1)
    decision: Literal["approve", "reject"]
    comment: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=2000)]


class EnterpriseIndicatorObservationCreate(BaseModel):
    counterparty_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128)]
    indicator_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=4, max_length=128)]
    values: dict[str, Any] = Field(min_length=1, max_length=4)
    evidence_document_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=64)] | None = None
    evidence_reference: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=2000)]
    as_of_date: date


class EnterpriseIndicatorObservationReview(BaseModel):
    expected_row_version: int = Field(ge=1)
    decision: Literal["verify", "reject"]
    comment: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=2000)]


class ApprovalAdvanceRequest(BaseModel):
    payload: dict[str, Any]
    expected_row_version: int = Field(ge=1)


class ApprovalAutomateRequest(BaseModel):
    expected_row_version: int = Field(ge=1)
    template_key: str | None = None


class RenewalRiskReviewRequest(BaseModel):
    expected_row_version: int = Field(ge=1)
    conclusion: Literal["cleared", "controls_required", "decline_recommended"]
    review_note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=2000)]
    control_measures: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=300)]] = Field(default_factory=list, max_length=8)


class ApprovalActionRequest(BaseModel):
    action: Literal["return_for_supplement", "reject", "withdraw", "comment"]
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=1000)]
    expected_row_version: int = Field(ge=1)
    required_document_types: list[str] = Field(default_factory=list, max_length=5)


class ApprovalSignoffRequest(BaseModel):
    slot_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=64)]
    decision: Literal["approve", "reject"]
    comment: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]
    expected_row_version: int = Field(ge=1)


class AuthorityPolicySlot(BaseModel):
    key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=64)]
    role: Literal["risk_manager", "approver"]
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128)]


class AuthorityPolicyTier(BaseModel):
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=64)]
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=500)]
    slots: list[AuthorityPolicySlot] = Field(min_length=1, max_length=6)


class AuthorityPolicyConfig(BaseModel):
    standard_limit: float = Field(gt=0, le=10_000_000_000)
    enhanced_limit: float = Field(gt=0, le=10_000_000_000)
    low_risk_ratings: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=16)]] = Field(min_length=1, max_length=20)
    high_risk_ratings: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=16)]] = Field(min_length=1, max_length=20)
    restricted_strategies: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]] = Field(default_factory=list, max_length=20)
    prohibited_strategies: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]] = Field(min_length=1, max_length=20)
    tiers: dict[Literal["standard", "enhanced", "committee"], AuthorityPolicyTier]


class AuthorityPolicyImpactRequest(BaseModel):
    policy_version: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=128)]
    config: AuthorityPolicyConfig


class AuthorityPolicyScenarioItem(BaseModel):
    key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=32, pattern=r"^[a-z0-9_-]+$")]
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=32)]
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=200)]
    config: AuthorityPolicyConfig


class AuthorityPolicyScenarioCompareRequest(BaseModel):
    scenarios: list[AuthorityPolicyScenarioItem] = Field(min_length=2, max_length=5)


class AuthorityPolicyRestoreDraftRequest(BaseModel):
    source_policy_ref: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=128)]
    policy_version: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=128)]
    change_reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]


class AuthorityPolicyCreate(BaseModel):
    policy_version: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=128)]
    change_reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]
    config: AuthorityPolicyConfig


class AuthorityPolicyUpdate(VersionedActionRequest):
    change_reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]
    config: AuthorityPolicyConfig


class AuthorityPolicyReview(VersionedActionRequest):
    decision: Literal["publish", "reject"]
    comment: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]
    effective_at: datetime | None = None


class AuthorityPolicyScheduleCancel(VersionedActionRequest):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]


class AuthorityPolicyEvidenceAnchorRevoke(VersionedActionRequest):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=1000)]


class AuthorityPolicyEvidenceAnchorReplace(VersionedActionRequest):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=1000)]


class AuthorityPolicyActivationScanRequest(BaseModel):
    run_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")] | None = None
    trigger_type: Literal["manual", "scheduler"] = "manual"


class AuthorityPolicyActivationIncidentAction(VersionedActionRequest):
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]


class AuthorityPolicyActivationRetry(AuthorityPolicyActivationIncidentAction):
    run_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")] | None = None


class ApiError(BaseModel):
    detail: str


# --- Rule Center Schemas ---

RuleCenterCode = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
]


class RuleConditionItem(BaseModel):
    expression: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]
    operator: Literal["bool", "==", "!=", ">", ">=", "<", "<="] = "bool"
    value: Any = None
    label: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=256)
    ] = ""


class RuleActionItem(BaseModel):
    type: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
    ]
    value: Any


class RuleCreate(BaseModel):
    code: RuleCenterCode
    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
    ]
    rule_type: Literal["strong_rule", "risk_screening", "admission"] = "strong_rule"
    category: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
    ] | None = None
    enabled: bool = True
    conditions_json: list[RuleConditionItem] = Field(
        default_factory=list, min_length=1, max_length=100
    )
    condition_relation: Literal["all", "any"] = "all"
    actions_json: list[RuleActionItem] = Field(
        default_factory=list, min_length=1, max_length=100
    )
    priority: int = Field(default=999, ge=0, le=1_000_000)


class RuleUpdate(BaseModel):
    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
    ] | None = None
    rule_type: Literal["strong_rule", "risk_screening", "admission"] | None = None
    category: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
    ] | None = None
    enabled: bool | None = None
    conditions_json: list[RuleConditionItem] | None = Field(
        default=None, min_length=1, max_length=100
    )
    condition_relation: Literal["all", "any"] | None = None
    actions_json: list[RuleActionItem] | None = Field(
        default=None, min_length=1, max_length=100
    )
    priority: int | None = Field(default=None, ge=0, le=1_000_000)


class RuleSetCreate(BaseModel):
    code: RuleCenterCode
    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
    ]
    rule_codes: list[RuleCenterCode] = Field(min_length=1, max_length=500)
    evaluation_strategy: Literal[
        "first_hit", "all_hits", "most_restrictive"
    ] = "most_restrictive"


class PipelineStageItem(BaseModel):
    stage_type: Literal[
        "scoring",
        "strong_rules",
        "risk_screening",
        "strategy_mapping",
        "admission",
    ]
    rule_set_code: RuleCenterCode | None = None


class PipelineCreate(BaseModel):
    code: RuleCenterCode
    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
    ]
    stages_json: list[PipelineStageItem] = Field(min_length=1, max_length=50)


class RuleTestRequest(BaseModel):
    context: dict[str, Any] = Field(default_factory=dict)


class PipelineSimulateRequest(BaseModel):
    counterparty: dict[str, Any] = Field(min_length=1)
    config: dict[str, Any] = Field(min_length=1)


class RuleCenterChangeCreate(BaseModel):
    asset_type: Literal["rule", "rule_set", "pipeline"]
    definition: dict[str, Any]
    change_reason: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)
    ]


class RuleCenterChangeUpdate(VersionedActionRequest):
    definition: dict[str, Any]
    change_reason: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)
    ]


class RuleCenterChangeReview(VersionedActionRequest):
    decision: Literal["publish", "reject"]
    comment: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)
    ]
    effective_at: datetime | None = None


class RuleCenterActivationScan(BaseModel):
    as_of: datetime | None = None


class RuleCenterRestoreDraft(BaseModel):
    asset_type: Literal["rule", "rule_set", "pipeline"]
    code: RuleCenterCode
    version: int = Field(ge=1)
    change_reason: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)
    ]


class RuleCenterPackagePreview(BaseModel):
    change_ids: list[str] = Field(min_length=1, max_length=100)


class RuleCenterPackageCreate(RuleCenterPackagePreview):
    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
    ]
    change_reason: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)
    ]


class RuleCenterPackageReview(VersionedActionRequest):
    decision: Literal["publish", "reject"]
    comment: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)
    ]


class RuleCenterReplayDatasetCreate(BaseModel):
    code: RuleCenterCode
    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
    ]
    description: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=5, max_length=2000)
    ]


class RuleCenterReplaySnapshotImport(BaseModel):
    source_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
    ]
    schema_version: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
    ] = "1.0"
    as_of_date: date
    evidence_reference: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=3, max_length=2000)
    ]
    data_classification: Literal["deidentified", "synthetic"]
    field_mapping: dict[str, str] = Field(default_factory=dict)
    label_field: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)] | None = None
    observed_at_field: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)] | None = None
    records: list[dict[str, Any]] = Field(min_length=1, max_length=5000)


class RuleCenterReplayCreate(BaseModel):
    dataset_snapshot_id: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=36)
    ]
    model_key: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
    ]
    pipeline_code: RuleCenterCode | None = None
    sample_limit: int = Field(default=100, ge=1, le=500)
    min_sample_count: int = Field(default=10, ge=1, le=500)
    max_decision_change_rate: float = Field(default=0.5, ge=0, le=1)
    max_execution_failure_rate: float = Field(default=0, ge=0, le=1)


class RuleCenterReplayComparisonCreate(BaseModel):
    dataset_snapshot_id: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=36)
    ]
    champion_model_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    challenger_model_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    challenger_change_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=36)] | None = None
    champion_pipeline_code: RuleCenterCode | None = None
    challenger_pipeline_code: RuleCenterCode | None = None
    segment_field: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)] = "counterparty_type"
    positive_labels: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]] = Field(default_factory=lambda: ["bad", "default", "reject"], min_length=1, max_length=20)
    positive_admissions: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]] = Field(default_factory=lambda: ["reject"], min_length=1, max_length=20)
    sample_limit: int = Field(default=500, ge=1, le=500)
    max_execution_failure_rate: float = Field(default=0, ge=0, le=1)
    max_psi: float = Field(default=0.25, ge=0, le=100)
    max_rating_change_rate: float = Field(default=0.25, ge=0, le=1)
    max_admission_change_rate: float = Field(default=0.15, ge=0, le=1)
    max_absolute_average_score_delta: float = Field(default=10, ge=0, le=100)
    max_segment_absolute_score_delta: float = Field(default=15, ge=0, le=100)
    max_ks_drop: float = Field(default=0.05, ge=0, le=1)
    require_labeled_evidence: bool = False


class ModelChangeComparisonEvidenceRun(VersionedActionRequest):
    dataset_snapshot_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=36)]
    champion_pipeline_code: RuleCenterCode | None = None
    challenger_pipeline_code: RuleCenterCode | None = None
    segment_field: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)] = "counterparty_type"
    positive_labels: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]] = Field(default_factory=lambda: ["bad", "default", "reject"], min_length=1, max_length=20)
    positive_admissions: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]] = Field(default_factory=lambda: ["reject"], min_length=1, max_length=20)
    sample_limit: int = Field(default=500, ge=1, le=500)
    max_execution_failure_rate: float = Field(default=0, ge=0, le=1)
    max_psi: float = Field(default=0.25, ge=0, le=100)
    max_rating_change_rate: float = Field(default=0.25, ge=0, le=1)
    max_admission_change_rate: float = Field(default=0.15, ge=0, le=1)
    max_absolute_average_score_delta: float = Field(default=10, ge=0, le=100)
    max_segment_absolute_score_delta: float = Field(default=15, ge=0, le=100)
    max_ks_drop: float = Field(default=0.05, ge=0, le=1)
    require_labeled_evidence: bool = False
    evidence_valid_days: int = Field(default=30, ge=1, le=180)


class RuleCenterReplayComparisonExceptionCreate(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=2000)]
    business_impact: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=2000)]
    compensating_controls: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=3000)]
    valid_until: date


class RuleCenterReplayComparisonExceptionReview(VersionedActionRequest):
    decision: Literal["approve", "reject"]
    comment: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]
