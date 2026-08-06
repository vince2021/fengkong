from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints


class RatingRequest(BaseModel):
    counterparty_id: str
    template_key: str = "general"


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


class ModelReviewRequest(VersionedActionRequest):
    decision: Literal["publish", "reject"]
    comment: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=1000)]


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
