from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class ApprovalCaseRecord(Base):
    __tablename__ = "approval_cases"

    case_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    counterparty_id: Mapped[str] = mapped_column(String(128), index=True)
    counterparty_name: Mapped[str] = mapped_column(String(255))
    current_stage: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), index=True)
    completed_stages: Mapped[list] = mapped_column(JSON, default=list)
    case_data: Mapped[dict] = mapped_column("data", JSON, default=dict)
    timeline: Mapped[list] = mapped_column(JSON, default=list)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    stage_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stage_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class AuditEventRecord(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_aggregate", "aggregate_type", "aggregate_id", "created_at"),
        UniqueConstraint("aggregate_type", "aggregate_id", "previous_hash", name="uq_audit_chain_parent"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    aggregate_type: Mapped[str] = mapped_column(String(64), index=True)
    aggregate_id: Mapped[str] = mapped_column(String(128), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    actor: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict] = mapped_column(JSON)
    previous_hash: Mapped[str] = mapped_column(String(64), default="")
    event_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class ModelSnapshotRecord(Base):
    __tablename__ = "model_snapshots"
    __table_args__ = (UniqueConstraint("template_key", "model_version", "config_hash", name="uq_model_snapshot"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    template_key: Mapped[str] = mapped_column(String(64), index=True)
    model_name: Mapped[str] = mapped_column(String(255))
    model_version: Mapped[str] = mapped_column(String(128), index=True)
    config_json: Mapped[dict] = mapped_column(JSON)
    config_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelChangeRecord(Base):
    __tablename__ = "model_changes"
    __table_args__ = (
        Index("ix_model_changes_template_status_created", "template_key", "status", "created_at"),
        UniqueConstraint("template_key", "candidate_version", name="uq_model_change_candidate_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    template_key: Mapped[str] = mapped_column(String(64), index=True)
    base_version: Mapped[str] = mapped_column(String(128))
    candidate_version: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    config_json: Mapped[dict] = mapped_column(JSON)
    validation_json: Mapped[dict] = mapped_column(JSON)
    impact_json: Mapped[dict] = mapped_column(JSON)
    change_reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(128), index=True)
    created_by_name: Mapped[str] = mapped_column(String(128))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class ModelReleaseRecord(Base):
    __tablename__ = "model_releases"
    __table_args__ = (
        Index("ix_model_releases_template_active", "template_key", "is_active", "published_at"),
        Index("uq_model_releases_one_active", "template_key", unique=True, sqlite_where=text("is_active = 1"), postgresql_where=text("is_active IS TRUE")),
        UniqueConstraint("template_key", "model_version", name="uq_model_release_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    template_key: Mapped[str] = mapped_column(String(64), index=True)
    model_version: Mapped[str] = mapped_column(String(128), index=True)
    config_json: Mapped[dict] = mapped_column(JSON)
    config_hash: Mapped[str] = mapped_column(String(64), index=True)
    source_change_id: Mapped[str | None] = mapped_column(ForeignKey("model_changes.id"), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    published_by: Mapped[str] = mapped_column(String(128))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class ModelOutcomeRecord(Base):
    __tablename__ = "model_outcomes"
    __table_args__ = (
        Index("ix_model_outcomes_template_period", "template_key", "population_period", "created_at"),
        UniqueConstraint("source", "external_observation_id", name="uq_model_outcome_source_external_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    external_observation_id: Mapped[str] = mapped_column(String(128), index=True)
    source: Mapped[str] = mapped_column(String(128), index=True)
    template_key: Mapped[str] = mapped_column(String(64), index=True)
    model_version: Mapped[str] = mapped_column(String(128), index=True)
    counterparty_id: Mapped[str] = mapped_column(String(128), index=True)
    population_period: Mapped[str] = mapped_column(String(16), index=True)
    predicted_score: Mapped[Decimal] = mapped_column(Numeric(8, 4))
    predicted_pd: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    observed_event: Mapped[bool] = mapped_column(Boolean, index=True)
    prediction_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    observation_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    evidence_reference: Mapped[str] = mapped_column(Text)
    verification_status: Mapped[str] = mapped_column(String(32), default="pending_verification", index=True)
    verified_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verification_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    __mapper_args__ = {"version_id_col": row_version}


class ModelOutcomeImportRecord(Base):
    __tablename__ = "model_outcome_imports"
    __table_args__ = (
        Index("ix_model_outcome_imports_template_period", "template_key", "population_period", "created_at"),
        UniqueConstraint("import_key", name="uq_model_outcome_import_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    import_key: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(128), index=True)
    template_key: Mapped[str] = mapped_column(String(64), index=True)
    population_period: Mapped[str] = mapped_column(String(6), index=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="processing", index=True)
    expected_count: Mapped[int] = mapped_column(Integer)
    received_count: Mapped[int] = mapped_column(Integer)
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    idempotent_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)
    results_json: Mapped[list] = mapped_column(JSON, default=list)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(128))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class ModelMonitoringIssueRecord(Base):
    __tablename__ = "model_monitoring_issues"
    __table_args__ = (
        Index("ix_monitoring_issues_template_status_due", "template_key", "status", "due_at"),
        UniqueConstraint("dedup_key", name="uq_monitoring_issue_dedup"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    template_key: Mapped[str] = mapped_column(String(64), index=True)
    model_version: Mapped[str] = mapped_column(String(128))
    dataset_id: Mapped[str] = mapped_column(String(128))
    evidence_level: Mapped[str] = mapped_column(String(32), index=True)
    metric_key: Mapped[str] = mapped_column(String(64), index=True)
    metric_label: Mapped[str] = mapped_column(String(128))
    metric_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    metric_status: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    dedup_key: Mapped[str] = mapped_column(String(512), unique=True)
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    remediation_plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    remediation_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    remediated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    revalidation_conclusion: Mapped[str | None] = mapped_column(Text, nullable=True)
    revalidated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    linked_change_id: Mapped[str | None] = mapped_column(ForeignKey("model_changes.id"), nullable=True, index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class ModelMonitoringRunRecord(Base):
    __tablename__ = "model_monitoring_runs"
    __table_args__ = (Index("ix_monitoring_runs_template_period", "template_key", "as_of_period", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_key: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    template_key: Mapped[str] = mapped_column(String(64), index=True)
    model_version: Mapped[str] = mapped_column(String(128), index=True)
    as_of_period: Mapped[str] = mapped_column(String(6), index=True)
    trigger_type: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    effective_source: Mapped[str] = mapped_column(String(32))
    evidence_level: Mapped[str] = mapped_column(String(32), index=True)
    dataset_id: Mapped[str] = mapped_column(String(128))
    readiness_json: Mapped[dict] = mapped_column(JSON, default=dict)
    monitoring_json: Mapped[dict] = mapped_column(JSON, default=dict)
    issue_ids: Mapped[list] = mapped_column(JSON, default=list)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor: Mapped[str] = mapped_column(String(128))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class ModelMonitoringScheduleRecord(Base):
    __tablename__ = "model_monitoring_schedules"
    __table_args__ = (UniqueConstraint("template_key", name="uq_model_monitoring_schedule_template"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    template_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    cadence: Mapped[str] = mapped_column(String(16), index=True)
    timezone_name: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_id: Mapped[str | None] = mapped_column(ForeignKey("model_monitoring_runs.id"), nullable=True, index=True)
    last_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(128))
    updated_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class ModelGovernanceNotificationRecord(Base):
    __tablename__ = "model_governance_notifications"
    __table_args__ = (
        Index("ix_governance_notifications_role_status_created", "recipient_role", "status", "created_at"),
        UniqueConstraint("dedup_key", name="uq_model_governance_notification_dedup"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    monitoring_run_id: Mapped[str] = mapped_column(ForeignKey("model_monitoring_runs.id"), index=True)
    monitoring_issue_id: Mapped[str | None] = mapped_column(ForeignKey("model_monitoring_issues.id"), nullable=True, index=True)
    template_key: Mapped[str] = mapped_column(String(64), index=True)
    recipient_role: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    dedup_key: Mapped[str] = mapped_column(String(512), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="unread", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    read_by: Mapped[str | None] = mapped_column(String(128), nullable=True)


class RatingRunRecord(Base):
    __tablename__ = "rating_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    counterparty_id: Mapped[str] = mapped_column(String(128), index=True)
    case_id: Mapped[str | None] = mapped_column(ForeignKey("approval_cases.case_id"), index=True, nullable=True)
    template_key: Mapped[str] = mapped_column(String(64), index=True)
    model_snapshot_id: Mapped[str] = mapped_column(ForeignKey("model_snapshots.id"), index=True)
    input_json: Mapped[dict] = mapped_column(JSON)
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    result_json: Mapped[dict] = mapped_column(JSON)
    result_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class PortfolioRatingBatchRecord(Base):
    __tablename__ = "portfolio_rating_batches"
    __table_args__ = (Index("ix_portfolio_batches_template_created", "template_key", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    batch_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    template_key: Mapped[str] = mapped_column(String(64), index=True)
    model_version: Mapped[str] = mapped_column(String(128), index=True)
    model_snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("model_snapshots.id"), nullable=True, index=True)
    scope_type: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    candidate_count: Mapped[int] = mapped_column(Integer)
    success_count: Mapped[int] = mapped_column(Integer)
    skipped_count: Mapped[int] = mapped_column(Integer)
    summary_json: Mapped[dict] = mapped_column(JSON)
    results_json: Mapped[list] = mapped_column(JSON)
    skipped_json: Mapped[list] = mapped_column(JSON)
    result_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_by: Mapped[str] = mapped_column(String(128), index=True)
    created_by_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class CreditReportRecord(Base):
    __tablename__ = "credit_reports"
    __table_args__ = (
        Index("ix_credit_reports_case_version", "case_id", "report_version"),
        UniqueConstraint("case_id", "snapshot_hash", name="uq_credit_report_case_snapshot"),
        UniqueConstraint("case_id", "report_version", name="uq_credit_report_case_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    report_no: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("approval_cases.case_id"), index=True)
    counterparty_id: Mapped[str] = mapped_column(String(128), index=True)
    report_version: Mapped[int] = mapped_column(Integer)
    report_type: Mapped[str] = mapped_column(String(32), default="credit_decision", index=True)
    status: Mapped[str] = mapped_column(String(32), default="sealed", index=True)
    snapshot_json: Mapped[dict] = mapped_column(JSON)
    snapshot_hash: Mapped[str] = mapped_column(String(64), index=True)
    object_key: Mapped[str] = mapped_column(String(512), unique=True)
    pdf_sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class DecisionVarianceRecord(Base):
    __tablename__ = "decision_variances"
    __table_args__ = (
        Index("ix_decision_variances_direction_materiality", "direction", "materiality", "decided_at"),
        UniqueConstraint("case_id", name="uq_decision_variance_case"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("approval_cases.case_id"), unique=True, index=True)
    counterparty_id: Mapped[str] = mapped_column(String(128), index=True)
    counterparty_name: Mapped[str] = mapped_column(String(255))
    rating_run_id: Mapped[str | None] = mapped_column(ForeignKey("rating_runs.id"), nullable=True, index=True)
    model_snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("model_snapshots.id"), nullable=True, index=True)
    direction: Mapped[str] = mapped_column(String(32), index=True)
    materiality: Mapped[str] = mapped_column(String(32), index=True)
    recommendation_json: Mapped[dict] = mapped_column(JSON)
    decision_json: Mapped[dict] = mapped_column(JSON)
    variance_json: Mapped[dict] = mapped_column(JSON)
    reason_category: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    reason_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    compensating_controls: Mapped[list] = mapped_column(JSON, default=list)
    decided_by: Mapped[str] = mapped_column(String(128), index=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class EnterpriseDataImportRecord(Base):
    __tablename__ = "enterprise_data_imports"
    __table_args__ = (
        Index("ix_enterprise_data_imports_counterparty_created", "counterparty_id", "created_at"),
        UniqueConstraint("import_key", name="uq_enterprise_data_import_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    import_key: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    counterparty_id: Mapped[str] = mapped_column(String(128), index=True)
    source_type: Mapped[str] = mapped_column(String(64), index=True)
    source_name: Mapped[str] = mapped_column(String(255))
    source_priority: Mapped[int] = mapped_column(Integer)
    schema_version: Mapped[str] = mapped_column(String(64))
    as_of_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    evidence_reference: Mapped[str] = mapped_column(Text)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    field_count: Mapped[int] = mapped_column(Integer)
    conflict_count: Mapped[int] = mapped_column(Integer)
    stale_count: Mapped[int] = mapped_column(Integer)
    invalid_count: Mapped[int] = mapped_column(Integer)
    quality_score: Mapped[Decimal] = mapped_column(Numeric(6, 4))
    quality_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class EnterpriseDataFieldRecord(Base):
    __tablename__ = "enterprise_data_fields"
    __table_args__ = (
        Index("ix_enterprise_data_fields_counterparty_path", "counterparty_id", "field_path", "observed_at"),
        UniqueConstraint("import_id", "field_path", name="uq_enterprise_data_field_import_path"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    import_id: Mapped[str] = mapped_column(ForeignKey("enterprise_data_imports.id"), index=True)
    counterparty_id: Mapped[str] = mapped_column(String(128), index=True)
    field_path: Mapped[str] = mapped_column(String(512), index=True)
    value_json: Mapped[object] = mapped_column(JSON)
    value_hash: Mapped[str] = mapped_column(String(64), index=True)
    value_type: Mapped[str] = mapped_column(String(32))
    source_type: Mapped[str] = mapped_column(String(64), index=True)
    source_name: Mapped[str] = mapped_column(String(255))
    source_priority: Mapped[int] = mapped_column(Integer)
    evidence_reference: Mapped[str] = mapped_column(Text)
    evidence_locator: Mapped[str | None] = mapped_column(String(512), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    freshness_days: Mapped[int] = mapped_column(Integer)
    freshness_status: Mapped[str] = mapped_column(String(16), index=True)
    validation_status: Mapped[str] = mapped_column(String(16), index=True)
    conflict_status: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class EnterpriseDataResolutionRecord(Base):
    __tablename__ = "enterprise_data_resolutions"
    __table_args__ = (
        Index("ix_enterprise_data_resolutions_counterparty_path", "counterparty_id", "field_path", "created_at"),
        Index(
            "uq_enterprise_data_pending_resolution",
            "counterparty_id",
            "field_path",
            unique=True,
            sqlite_where=text("status = 'pending_review'"),
            postgresql_where=text("status = 'pending_review'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    counterparty_id: Mapped[str] = mapped_column(String(128), index=True)
    field_path: Mapped[str] = mapped_column(String(512), index=True)
    selected_field_id: Mapped[str] = mapped_column(ForeignKey("enterprise_data_fields.id"), index=True)
    selected_value_json: Mapped[object] = mapped_column(JSON)
    selected_value_hash: Mapped[str] = mapped_column(String(64), index=True)
    candidate_snapshot_hash: Mapped[str] = mapped_column(String(64), index=True)
    candidate_count: Mapped[int] = mapped_column(Integer)
    reason_category: Mapped[str] = mapped_column(String(64), index=True)
    rationale: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending_review", index=True)
    created_by: Mapped[str] = mapped_column(String(128), index=True)
    created_by_name: Mapped[str] = mapped_column(String(128))
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    reviewed_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class EnterpriseIndicatorObservationRecord(Base):
    __tablename__ = "enterprise_indicator_observations"
    __table_args__ = (
        Index("ix_indicator_observations_counterparty_indicator", "counterparty_id", "indicator_id", "created_at"),
        Index(
            "uq_indicator_observations_pending",
            "counterparty_id",
            "indicator_id",
            unique=True,
            sqlite_where=text("status = 'pending_review'"),
            postgresql_where=text("status = 'pending_review'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    counterparty_id: Mapped[str] = mapped_column(String(128), index=True)
    indicator_id: Mapped[str] = mapped_column(String(128), index=True)
    indicator_name: Mapped[str] = mapped_column(String(255))
    values_json: Mapped[dict] = mapped_column(JSON)
    values_hash: Mapped[str] = mapped_column(String(64), index=True)
    evidence_document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"), nullable=True, index=True)
    evidence_reference: Mapped[str] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending_review", index=True)
    created_by: Mapped[str] = mapped_column(String(128), index=True)
    created_by_name: Mapped[str] = mapped_column(String(128))
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    reviewed_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class DocumentRecord(Base):
    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_counterparty_case", "counterparty_id", "case_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    counterparty_id: Mapped[str] = mapped_column(String(128), index=True)
    case_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    document_type: Mapped[str] = mapped_column(String(64), index=True)
    original_name: Mapped[str] = mapped_column(String(512))
    object_key: Mapped[str] = mapped_column(String(512), unique=True)
    content_type: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    uploaded_by: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), default="已上传", index=True)
    checklist_json: Mapped[list] = mapped_column(JSON, default=list)
    review_status: Mapped[str] = mapped_column(String(32), default="pending_review", index=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    reviewed_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    __mapper_args__ = {"version_id_col": row_version}


class DocumentCorrectionRecord(Base):
    __tablename__ = "document_corrections"
    __table_args__ = (
        Index("ix_document_corrections_scope_status", "counterparty_id", "case_id", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    counterparty_id: Mapped[str] = mapped_column(String(128), index=True)
    case_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    document_type: Mapped[str] = mapped_column(String(64), index=True)
    original_document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    current_document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    version_document_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    reason: Mapped[str] = mapped_column(Text)
    failed_check_keys_json: Mapped[list] = mapped_column(JSON, default=list)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    requested_by: Mapped[str] = mapped_column(String(128), index=True)
    requested_by_name: Mapped[str] = mapped_column(String(128))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resolved_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class NotificationRecord(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_role_status_created", "recipient_role", "status", "created_at"),
        UniqueConstraint("dedup_key", name="uq_notifications_dedup_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("approval_cases.case_id"), index=True)
    counterparty_id: Mapped[str] = mapped_column(String(128), index=True)
    recipient_role: Mapped[str] = mapped_column(String(64), index=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    level: Mapped[str] = mapped_column(String(32), index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    dedup_key: Mapped[str] = mapped_column(String(512), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="unread", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CreditFacilityRecord(Base):
    __tablename__ = "credit_facilities"
    __table_args__ = (
        Index("ix_credit_facilities_status_expiry", "status", "expires_at"),
        UniqueConstraint("case_id", name="uq_credit_facility_case"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("approval_cases.case_id"), index=True)
    counterparty_id: Mapped[str] = mapped_column(String(128), index=True)
    counterparty_name: Mapped[str] = mapped_column(String(255))
    approved_limit: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    used_limit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    payment_term_days: Mapped[int] = mapped_column(Integer)
    rating: Mapped[str] = mapped_column(String(32), index=True)
    access_strategy: Mapped[str] = mapped_column(String(64))
    monitoring_frequency: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_review_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class CreditUsageRecord(Base):
    __tablename__ = "credit_usage_transactions"
    __table_args__ = (Index("ix_credit_usage_facility_occurred", "facility_id", "occurred_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    facility_id: Mapped[str] = mapped_column(ForeignKey("credit_facilities.id"), index=True)
    transaction_ref: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    transaction_type: Mapped[str] = mapped_column(String(32), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    balance_after: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    actor: Mapped[str] = mapped_column(String(128))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FacilityAlertRecord(Base):
    __tablename__ = "facility_alerts"
    __table_args__ = (
        Index("ix_facility_alerts_status_severity_created", "status", "severity", "created_at"),
        UniqueConstraint("dedup_key", name="uq_facility_alert_dedup"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    facility_id: Mapped[str] = mapped_column(ForeignKey("credit_facilities.id"), index=True)
    alert_type: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    dedup_key: Mapped[str] = mapped_column(String(512), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    disposition_action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    disposition_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)

    __mapper_args__ = {"version_id_col": row_version}


class RiskEventRecord(Base):
    __tablename__ = "risk_events"
    __table_args__ = (
        Index("ix_risk_events_facility_occurred", "facility_id", "occurred_at"),
        Index("uq_risk_events_source_external_id", "source", "external_event_id", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    facility_id: Mapped[str] = mapped_column(ForeignKey("credit_facilities.id"), index=True)
    external_event_id: Mapped[str] = mapped_column(String(128), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    event_payload: Mapped[dict] = mapped_column("payload", JSON, default=dict)
    linked_alert_id: Mapped[str | None] = mapped_column(ForeignKey("facility_alerts.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
