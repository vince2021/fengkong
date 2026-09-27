from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class TenantRecord(Base):
    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint("deployment_mode IN ('saas', 'dedicated')", name="ck_tenant_deployment_mode"),
        CheckConstraint("status IN ('active', 'suspended', 'disabled')", name="ck_tenant_status"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    deployment_mode: Mapped[str] = mapped_column(String(32), default="saas", index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    data_region: Mapped[str] = mapped_column(String(64), default="cn")
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class TenantMembershipRecord(Base):
    __tablename__ = "tenant_memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "subject", name="uq_tenant_membership_subject"),
        CheckConstraint("status IN ('active', 'suspended', 'revoked')", name="ck_tenant_membership_status"),
        Index("ix_tenant_membership_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    subject: Mapped[str] = mapped_column(String(128), index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    roles_json: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class ApiClientRecord(Base):
    __tablename__ = "api_clients"
    __table_args__ = (
        UniqueConstraint("tenant_id", "client_id", name="uq_api_client_tenant_client"),
        CheckConstraint("status IN ('active', 'disabled', 'revoked')", name="ck_api_client_status"),
        CheckConstraint("qps_limit > 0", name="ck_api_client_qps_positive"),
        CheckConstraint("concurrent_job_limit > 0", name="ck_api_client_concurrency_positive"),
        CheckConstraint("daily_item_quota > 0", name="ck_api_client_daily_quota_positive"),
        Index("ix_api_client_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    key_id: Mapped[str] = mapped_column(String(128))
    key_fingerprint: Mapped[str] = mapped_column(String(255))
    secret_reference: Mapped[str | None] = mapped_column(String(256), nullable=True)
    rotated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    qps_limit: Mapped[int] = mapped_column(Integer, default=20)
    concurrent_job_limit: Mapped[int] = mapped_column(Integer, default=3)
    daily_item_quota: Mapped[int] = mapped_column(Integer, default=10000)
    allowed_cidrs_json: Mapped[list] = mapped_column(JSON, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class ProductPackageRecord(Base):
    __tablename__ = "product_packages"
    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_product_package_code_version"),
        CheckConstraint(
            "status IN ('draft', 'pending_review', 'published', 'rejected', 'retired')",
            name="ck_product_package_status",
        ),
        CheckConstraint("expiry_policy = 'block'", name="ck_product_package_expiry_policy"),
        Index("ix_product_package_code_status", "code", "status", "version"),
        Index(
            "uq_product_package_one_active",
            "code",
            unique=True,
            sqlite_where=text("is_active = 1"),
            postgresql_where=text("is_active IS TRUE"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    environment_scopes_json: Mapped[list] = mapped_column(JSON, default=list)
    asset_catalog_json: Mapped[list] = mapped_column(JSON, default=list)
    quotas_json: Mapped[dict] = mapped_column(JSON, default=dict)
    expiry_policy: Mapped[str] = mapped_column(String(32), default="block")
    config_hash: Mapped[str] = mapped_column(String(64), index=True)
    change_reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(128))
    created_by_name: Mapped[str] = mapped_column(String(128))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class TenantEntitlementRecord(Base):
    __tablename__ = "tenant_entitlements"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'pending_review', 'scheduled', 'active', 'suspended', 'expired', 'terminated')",
            name="ck_tenant_entitlement_status",
        ),
        CheckConstraint("expires_at > starts_at", name="ck_tenant_entitlement_window"),
        Index("ix_tenant_entitlement_tenant_status", "tenant_id", "status", "starts_at", "expires_at"),
        Index(
            "uq_tenant_entitlement_one_active",
            "tenant_id",
            unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    product_package_id: Mapped[str] = mapped_column(ForeignKey("product_packages.id", ondelete="RESTRICT"), index=True)
    package_code: Mapped[str] = mapped_column(String(128), index=True)
    package_version: Mapped[int] = mapped_column(Integer)
    package_config_hash: Mapped[str] = mapped_column(String(64))
    package_snapshot_json: Mapped[dict] = mapped_column(JSON)
    effective_quotas_json: Mapped[dict] = mapped_column(JSON)
    initialized_assets_json: Mapped[list] = mapped_column(JSON, default=list)
    activation_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    change_reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(128))
    created_by_name: Mapped[str] = mapped_column(String(128))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    terminated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class TenantUsageDailyRecord(Base):
    """Reproducible daily commercial-metering ledger derived from sealed business records."""

    __tablename__ = "tenant_usage_daily_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "usage_date", name="uq_tenant_usage_daily_tenant_date"),
        Index("ix_tenant_usage_daily_tenant_date", "tenant_id", "usage_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    usage_date: Mapped[date] = mapped_column(Date, index=True)
    usage_json: Mapped[dict] = mapped_column(JSON, default=dict)
    source_watermark_json: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_hash: Mapped[str] = mapped_column(String(64), index=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class TenantUsageStatementRecord(Base):
    """Immutable monthly reconciliation evidence snapshot; this is not a tax invoice."""

    __tablename__ = "tenant_usage_statements"
    __table_args__ = (
        UniqueConstraint("tenant_id", "billing_month", "statement_version", name="uq_tenant_usage_statement_version"),
        CheckConstraint("status = 'generated'", name="ck_tenant_usage_statement_status"),
        Index("ix_tenant_usage_statement_tenant_month", "tenant_id", "billing_month", "statement_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    billing_month: Mapped[date] = mapped_column(Date, index=True)
    statement_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="generated")
    statement_json: Mapped[dict] = mapped_column(JSON, default=dict)
    statement_hash: Mapped[str] = mapped_column(String(64), index=True)
    generated_by: Mapped[str] = mapped_column(String(128))
    generated_by_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class TenantEntitlementLifecycleRunRecord(Base):
    __tablename__ = "tenant_entitlement_lifecycle_runs"
    __table_args__ = (
        CheckConstraint(
            "trigger_type IN ('scheduler', 'manual', 'retry')",
            name="ck_tenant_entitlement_lifecycle_trigger",
        ),
        CheckConstraint(
            "status IN ('no_due', 'completed', 'partial', 'failed')",
            name="ck_tenant_entitlement_lifecycle_status",
        ),
        CheckConstraint(
            "incident_status IN ('not_applicable', 'open', 'acknowledged', 'resolved')",
            name="ck_tenant_entitlement_lifecycle_incident",
        ),
        UniqueConstraint("run_key", name="uq_tenant_entitlement_lifecycle_run_key"),
        Index("ix_tenant_entitlement_lifecycle_status_created", "status", "created_at"),
        Index("ix_tenant_entitlement_lifecycle_incident_created", "incident_status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_key: Mapped[str] = mapped_column(String(160), index=True)
    trigger_type: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    scan_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    activated_count: Mapped[int] = mapped_column(Integer, default=0)
    expired_count: Mapped[int] = mapped_column(Integer, default=0)
    superseded_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    results_json: Mapped[list] = mapped_column(JSON, default=list)
    evidence_hash: Mapped[str] = mapped_column(String(64), index=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    incident_status: Mapped[str] = mapped_column(String(32), default="not_applicable", index=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    acknowledged_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledgement_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resolved_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_of_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("tenant_entitlement_lifecycle_runs.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    resolved_by_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("tenant_entitlement_lifecycle_runs.id", ondelete="RESTRICT"), nullable=True
    )
    actor_subject: Mapped[str] = mapped_column(String(128))
    actor_name: Mapped[str] = mapped_column(String(128))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    __mapper_args__ = {"version_id_col": row_version}


class TenantRolloutPolicyRecord(Base):
    __tablename__ = "tenant_rollout_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_tenant_rollout_policy_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "comparison_run_id"],
            ["rule_center_replay_comparison_runs.tenant_id", "rule_center_replay_comparison_runs.id"],
            ondelete="RESTRICT",
            name="fk_tenant_rollout_policy_tenant_comparison",
        ),
        CheckConstraint(
            "status IN ('draft', 'pending_review', 'scheduled', 'active', 'paused', 'rolled_back', 'completed', 'rejected')",
            name="ck_tenant_rollout_policy_status",
        ),
        CheckConstraint("traffic_basis_points BETWEEN 1 AND 9999", name="ck_tenant_rollout_policy_traffic"),
        CheckConstraint("ends_at > starts_at", name="ck_tenant_rollout_policy_window"),
        Index("ix_tenant_rollout_policy_tenant_status", "tenant_id", "status", "starts_at", "ends_at"),
        Index(
            "uq_tenant_rollout_one_active_model",
            "tenant_id", "champion_model_key",
            unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    comparison_run_id: Mapped[str] = mapped_column(String(36), index=True)
    comparison_evidence_hash: Mapped[str] = mapped_column(String(64), index=True)
    comparison_assets_hash: Mapped[str] = mapped_column(String(64), index=True)
    champion_model_key: Mapped[str] = mapped_column(String(64), index=True)
    champion_model_version: Mapped[str] = mapped_column(String(128))
    champion_pipeline_code: Mapped[str] = mapped_column(String(128))
    champion_pipeline_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    challenger_model_key: Mapped[str] = mapped_column(String(64), index=True)
    challenger_model_version: Mapped[str] = mapped_column(String(128))
    challenger_pipeline_code: Mapped[str] = mapped_column(String(128))
    challenger_pipeline_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    routing_key_field: Mapped[str] = mapped_column(String(128), default="counterparty_id")
    traffic_basis_points: Mapped[int] = mapped_column(Integer)
    observation_window_minutes: Mapped[int] = mapped_column(Integer)
    min_sample_size: Mapped[int] = mapped_column(Integer)
    thresholds_json: Mapped[dict] = mapped_column(JSON)
    config_json: Mapped[dict] = mapped_column(JSON)
    config_hash: Mapped[str] = mapped_column(String(64), index=True)
    arm_snapshot_json: Mapped[dict] = mapped_column(JSON)
    assets_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    change_reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(128))
    created_by_name: Mapped[str] = mapped_column(String(128))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    incident_status: Mapped[str] = mapped_column(String(32), default="not_applicable", index=True)
    incident_evaluation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledgement_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution_requested_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resolution_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class TenantRoutingDecisionRecord(Base):
    __tablename__ = "tenant_routing_decisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "policy_id"],
            ["tenant_rollout_policies.tenant_id", "tenant_rollout_policies.id"],
            ondelete="RESTRICT",
            name="fk_tenant_routing_decision_tenant_policy",
        ),
        UniqueConstraint("tenant_id", "channel", "request_ref", name="uq_tenant_routing_decision_request"),
        CheckConstraint("selected_arm IN ('champion', 'challenger')", name="ck_tenant_routing_decision_arm"),
        CheckConstraint("status IN ('selected', 'completed', 'failed')", name="ck_tenant_routing_decision_status"),
        CheckConstraint("bucket BETWEEN 0 AND 9999", name="ck_tenant_routing_decision_bucket"),
        Index("ix_tenant_routing_policy_arm_created", "tenant_id", "policy_id", "selected_arm", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    policy_id: Mapped[str] = mapped_column(String(36), index=True)
    policy_config_hash: Mapped[str] = mapped_column(String(64), index=True)
    policy_assets_hash: Mapped[str] = mapped_column(String(64))
    channel: Mapped[str] = mapped_column(String(32), index=True)
    request_ref: Mapped[str] = mapped_column(String(256), index=True)
    routing_key_hash: Mapped[str] = mapped_column(String(64), index=True)
    bucket: Mapped[int] = mapped_column(Integer)
    selected_arm: Mapped[str] = mapped_column(String(16), index=True)
    selected_assets_json: Mapped[dict] = mapped_column(JSON)
    selected_assets_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default="selected", index=True)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    rating: Mapped[str | None] = mapped_column(String(32), nullable=True)
    admission: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    result_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class TenantRolloutEvaluationRecord(Base):
    __tablename__ = "tenant_rollout_evaluations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "policy_id"],
            ["tenant_rollout_policies.tenant_id", "tenant_rollout_policies.id"],
            ondelete="RESTRICT",
            name="fk_tenant_rollout_evaluation_tenant_policy",
        ),
        Index("ix_tenant_rollout_evaluation_policy_created", "tenant_id", "policy_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    policy_id: Mapped[str] = mapped_column(String(36), index=True)
    trigger_type: Mapped[str] = mapped_column(String(32))
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sample_count: Mapped[int] = mapped_column(Integer)
    evidence_level: Mapped[str] = mapped_column(String(32))
    metrics_json: Mapped[dict] = mapped_column(JSON)
    gate_json: Mapped[dict] = mapped_column(JSON)
    action: Mapped[str] = mapped_column(String(32))
    evidence_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_by: Mapped[str] = mapped_column(String(128))
    created_by_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class TenantOutcomeLabelDefinitionRecord(Base):
    __tablename__ = "tenant_outcome_label_definitions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", "version", name="uq_tenant_outcome_label_definition_version"),
        CheckConstraint(
            "event_type IN ('default', 'delinquency', 'loss', 'recovery')",
            name="ck_tenant_outcome_label_definition_event_type",
        ),
        CheckConstraint(
            "status IN ('draft', 'pending_review', 'published', 'rejected', 'retired')",
            name="ck_tenant_outcome_label_definition_status",
        ),
        CheckConstraint("observation_window_days > 0", name="ck_tenant_outcome_label_definition_window"),
        CheckConstraint("maturity_grace_days >= 0", name="ck_tenant_outcome_label_definition_grace"),
        Index("ix_tenant_outcome_label_definition_tenant_status", "tenant_id", "status", "code"),
        Index(
            "uq_tenant_outcome_label_definition_active",
            "tenant_id",
            "code",
            unique=True,
            sqlite_where=text("status = 'published' AND is_active = 1"),
            postgresql_where=text("status = 'published' AND is_active = true"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(String(32))
    event_threshold_json: Mapped[dict] = mapped_column(JSON, default=dict)
    observation_window_days: Mapped[int] = mapped_column(Integer)
    maturity_grace_days: Mapped[int] = mapped_column(Integer, default=0)
    source_priorities_json: Mapped[list] = mapped_column(JSON, default=list)
    applicable_model_keys_json: Mapped[list] = mapped_column(JSON, default=list)
    require_loss_amount: Mapped[bool] = mapped_column(Boolean, default=False)
    require_exposure_amount: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    config_hash: Mapped[str] = mapped_column(String(64), index=True)
    submitted_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    submitted_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(128))
    created_by_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class TenantOutcomeImportBatchRecord(Base):
    __tablename__ = "tenant_outcome_import_batches"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "policy_id"],
            ["tenant_rollout_policies.tenant_id", "tenant_rollout_policies.id"],
            ondelete="RESTRICT",
            name="fk_tenant_outcome_import_tenant_policy",
        ),
        UniqueConstraint("tenant_id", "import_key", name="uq_tenant_outcome_import_key"),
        CheckConstraint(
            "status IN ('processing', 'completed', 'completed_with_exceptions', 'failed')",
            name="ck_tenant_outcome_import_status",
        ),
        Index("ix_tenant_outcome_import_policy_created", "tenant_id", "policy_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    policy_id: Mapped[str] = mapped_column(String(36), index=True)
    import_key: Mapped[str] = mapped_column(String(160), index=True)
    source: Mapped[str] = mapped_column(String(128))
    label_definition: Mapped[str] = mapped_column(String(128))
    label_definition_id: Mapped[str | None] = mapped_column(ForeignKey("tenant_outcome_label_definitions.id", ondelete="RESTRICT"), nullable=True, index=True)
    label_definition_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    label_definition_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    expected_count: Mapped[int] = mapped_column(Integer)
    received_count: Mapped[int] = mapped_column(Integer)
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    idempotent_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)
    corrected_count: Mapped[int] = mapped_column(Integer, default=0)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    results_json: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), index=True)
    evidence_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_by: Mapped[str] = mapped_column(String(128))
    created_by_name: Mapped[str] = mapped_column(String(128))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class TenantOutcomeLabelRecord(Base):
    __tablename__ = "tenant_outcome_labels"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "policy_id"],
            ["tenant_rollout_policies.tenant_id", "tenant_rollout_policies.id"],
            ondelete="RESTRICT",
            name="fk_tenant_outcome_label_tenant_policy",
        ),
        UniqueConstraint("tenant_id", "source", "external_label_id", name="uq_tenant_outcome_label_external"),
        CheckConstraint("link_status IN ('route_only', 'decision_execution')", name="ck_tenant_outcome_label_link_status"),
        CheckConstraint("record_status IN ('active', 'superseded')", name="ck_tenant_outcome_label_record_status"),
        CheckConstraint(
            "verification_status IN ('pending_verification', 'verified', 'rejected')",
            name="ck_tenant_outcome_label_verification",
        ),
        CheckConstraint("predicted_score BETWEEN 0 AND 100", name="ck_tenant_outcome_label_score"),
        CheckConstraint("risk_score BETWEEN 0 AND 1", name="ck_tenant_outcome_label_risk_score"),
        Index("ix_tenant_outcome_label_policy_status", "tenant_id", "policy_id", "verification_status", "observation_end"),
        Index(
            "uq_tenant_outcome_label_active_definition",
            "tenant_id",
            "routing_decision_id",
            "label_definition",
            unique=True,
            sqlite_where=text("record_status = 'active'"),
            postgresql_where=text("record_status = 'active'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    policy_id: Mapped[str] = mapped_column(String(36), index=True)
    routing_decision_id: Mapped[str] = mapped_column(ForeignKey("tenant_routing_decisions.id", ondelete="RESTRICT"), index=True)
    decision_execution_id: Mapped[str | None] = mapped_column(ForeignKey("decision_executions.id", ondelete="RESTRICT"), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(128), index=True)
    external_label_id: Mapped[str] = mapped_column(String(128), index=True)
    counterparty_id: Mapped[str] = mapped_column(String(128), index=True)
    label_definition: Mapped[str] = mapped_column(String(128))
    label_definition_id: Mapped[str | None] = mapped_column(ForeignKey("tenant_outcome_label_definitions.id", ondelete="RESTRICT"), nullable=True, index=True)
    label_definition_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    label_definition_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    observed_event: Mapped[bool] = mapped_column(Boolean, index=True)
    observation_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    loss_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    exposure_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    evidence_reference: Mapped[str] = mapped_column(Text)
    link_status: Mapped[str] = mapped_column(String(32), index=True)
    selected_arm: Mapped[str] = mapped_column(String(16), index=True)
    model_key: Mapped[str] = mapped_column(String(64), index=True)
    model_version: Mapped[str] = mapped_column(String(128), index=True)
    predicted_score: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    risk_score: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    rating: Mapped[str | None] = mapped_column(String(32), nullable=True)
    admission: Mapped[str | None] = mapped_column(String(64), nullable=True)
    routing_evidence_hash: Mapped[str] = mapped_column(String(64))
    execution_evidence_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    selected_assets_hash: Mapped[str] = mapped_column(String(64))
    label_payload_hash: Mapped[str] = mapped_column(String(64))
    evidence_hash: Mapped[str] = mapped_column(String(64), index=True)
    evidence_schema_version: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    canonical_evidence_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    import_batch_id: Mapped[str | None] = mapped_column(ForeignKey("tenant_outcome_import_batches.id", ondelete="RESTRICT"), nullable=True, index=True)
    record_status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    supersedes_label_id: Mapped[str | None] = mapped_column(ForeignKey("tenant_outcome_labels.id", ondelete="RESTRICT"), nullable=True, index=True)
    superseded_by_label_id: Mapped[str | None] = mapped_column(ForeignKey("tenant_outcome_labels.id", ondelete="RESTRICT"), nullable=True, index=True)
    correction_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verification_status: Mapped[str] = mapped_column(String(32), default="pending_verification", index=True)
    verified_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    verified_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verification_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(128))
    created_by_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    __mapper_args__ = {"version_id_col": row_version}


class TenantMonitoringRunRecord(Base):
    """Immutable evidence payload with a governed tenant-scoped publication envelope."""

    __tablename__ = "tenant_monitoring_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "policy_id"],
            ["tenant_rollout_policies.tenant_id", "tenant_rollout_policies.id"],
            ondelete="RESTRICT",
            name="fk_tenant_monitoring_run_tenant_policy",
        ),
        CheckConstraint("status IN ('completed', 'failed', 'cancelled')", name="ck_tenant_monitoring_run_status"),
        CheckConstraint("evidence_level IN ('supervised', 'non_supervised')", name="ck_tenant_monitoring_run_evidence_level"),
        CheckConstraint("governance_status IN ('draft', 'pending_review', 'published', 'rejected', 'retracted')", name="ck_tenant_monitoring_run_governance_status"),
        Index("ix_tenant_monitoring_run_policy_window", "tenant_id", "policy_id", "observed_to", "created_at"),
        UniqueConstraint("tenant_id", "run_key", name="uq_tenant_monitoring_run_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    policy_id: Mapped[str] = mapped_column(String(36), index=True)
    run_key: Mapped[str] = mapped_column(String(160), index=True)
    model_key: Mapped[str] = mapped_column(String(64), index=True)
    model_version: Mapped[str] = mapped_column(String(128), index=True)
    observed_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    observed_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    dataset_id: Mapped[str] = mapped_column(String(160))
    evidence_level: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    governance_status: Mapped[str] = mapped_column(String(32), default="published", index=True)
    label_definition_id: Mapped[str | None] = mapped_column(ForeignKey("tenant_outcome_label_definitions.id", ondelete="RESTRICT"), nullable=True, index=True)
    label_definition_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    label_definition_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    label_watermark_json: Mapped[dict] = mapped_column(JSON, default=dict)
    monitoring_json: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_hash: Mapped[str] = mapped_column(String(64), index=True)
    submitted_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    submitted_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    retracted_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    retracted_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    retracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retraction_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(128))
    created_by_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    __mapper_args__ = {"version_id_col": row_version}


class TenantMonitoringDiffCaseRecord(Base):
    """Governed investigation of a material difference between monitoring snapshots."""

    __tablename__ = "tenant_monitoring_diff_cases"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "policy_id"],
            ["tenant_rollout_policies.tenant_id", "tenant_rollout_policies.id"],
            ondelete="RESTRICT",
            name="fk_tenant_monitoring_diff_case_policy",
        ),
        CheckConstraint(
            "status IN ('open', 'assigned', 'recomputing', 'pending_disposition', 'resolved', 'rejected')",
            name="ck_tenant_monitoring_diff_case_status",
        ),
        CheckConstraint("severity IN ('info', 'warning', 'critical')", name="ck_tenant_monitoring_diff_case_severity"),
        CheckConstraint(
            "recompute_status IN ('not_started', 'running', 'completed', 'failed')",
            name="ck_tenant_monitoring_diff_case_recompute_status",
        ),
        CheckConstraint(
            "disposition IS NULL OR disposition IN ('accepted_change', 'data_issue', 'calculation_issue', "
            "'model_drift', 'policy_threshold_change_required', 'superseded')",
            name="ck_tenant_monitoring_diff_case_disposition",
        ),
        UniqueConstraint("tenant_id", "diff_hash", name="uq_tenant_monitoring_diff_case_hash"),
        Index("ix_tenant_monitoring_diff_case_queue", "tenant_id", "policy_id", "status", "due_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    policy_id: Mapped[str] = mapped_column(String(36), index=True)
    base_run_id: Mapped[str] = mapped_column(ForeignKey("tenant_monitoring_runs.id", ondelete="RESTRICT"), index=True)
    against_run_id: Mapped[str] = mapped_column(ForeignKey("tenant_monitoring_runs.id", ondelete="RESTRICT"), index=True)
    base_evidence_hash: Mapped[str] = mapped_column(String(64))
    against_evidence_hash: Mapped[str] = mapped_column(String(64))
    diff_hash: Mapped[str] = mapped_column(String(64), index=True)
    comparison_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    severity: Mapped[str] = mapped_column(String(32), default="warning", index=True)
    reason: Mapped[str] = mapped_column(Text)
    assigned_role: Mapped[str] = mapped_column(String(64), default="risk_manager")
    assigned_to: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    assigned_to_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    recompute_status: Mapped[str] = mapped_column(String(32), default="not_started", index=True)
    recomputed_run_id: Mapped[str | None] = mapped_column(ForeignKey("tenant_monitoring_runs.id", ondelete="RESTRICT"), nullable=True, index=True)
    recomputed_diff_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recomputed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    recomputed_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    recomputed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recompute_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    disposition: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    conclusion: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resolved_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(128))
    created_by_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class ModelRiskReviewAssignmentRecord(Base):
    """Tenant-scoped operational ownership overlay for the live review projection."""

    __tablename__ = "model_risk_review_assignments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "item_id", name="uq_model_risk_review_assignment_item"),
        Index("ix_model_risk_review_assignment_tenant_owner", "tenant_id", "assigned_to"),
        Index("ix_model_risk_review_assignment_tenant_role", "tenant_id", "assigned_role"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[str] = mapped_column(String(192), index=True)
    source: Mapped[str] = mapped_column(String(64), index=True)
    assigned_role: Mapped[str] = mapped_column(String(64), nullable=False)
    assigned_to: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    assigned_to_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    assigned_by: Mapped[str] = mapped_column(String(128))
    assigned_by_name: Mapped[str] = mapped_column(String(255))
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class ModelRiskReviewDelegationRecord(Base):
    """Time-bounded delegation for review responsibilities within one tenant."""

    __tablename__ = "model_risk_review_delegations"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'revoked')", name="ck_model_risk_review_delegation_status"),
        CheckConstraint("principal_subject <> delegate_subject", name="ck_model_risk_review_delegation_distinct_members"),
        CheckConstraint("ends_at > starts_at", name="ck_model_risk_review_delegation_window"),
        Index(
            "ix_model_risk_review_delegation_principal_window",
            "tenant_id", "principal_subject", "assigned_role", "status", "starts_at", "ends_at",
        ),
        Index(
            "ix_model_risk_review_delegation_delegate_window",
            "tenant_id", "delegate_subject", "status", "starts_at", "ends_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    principal_subject: Mapped[str] = mapped_column(String(128), index=True)
    principal_name: Mapped[str] = mapped_column(String(255))
    delegate_subject: Mapped[str] = mapped_column(String(128), index=True)
    delegate_name: Mapped[str] = mapped_column(String(255))
    assigned_role: Mapped[str] = mapped_column(String(64), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(128))
    created_by_name: Mapped[str] = mapped_column(String(255))
    revoked_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    revoked_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class ModelRiskReviewSavedViewRecord(Base):
    """Personal, tenant-scoped filters for the model-risk operations workbench."""

    __tablename__ = "model_risk_review_saved_views"
    __table_args__ = (
        UniqueConstraint("tenant_id", "owner_subject", "name", name="uq_model_risk_review_view_owner_name"),
        Index(
            "uq_model_risk_review_view_owner_default",
            "tenant_id", "owner_subject", unique=True,
            sqlite_where=text("is_default = 1"),
            postgresql_where=text("is_default = true"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    owner_subject: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(128))
    filters_json: Mapped[dict] = mapped_column(JSON, default=dict)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class ModelRiskReviewSlaSnapshotRecord(Base):
    """Immutable daily aggregate used only for trend history, never as queue truth."""

    __tablename__ = "model_risk_review_sla_snapshots"
    __table_args__ = (
        UniqueConstraint("tenant_id", "snapshot_date", "template_key", name="uq_model_risk_review_sla_snapshot_bucket"),
        Index("ix_model_risk_review_sla_snapshot_tenant_date", "tenant_id", "snapshot_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    template_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    counts_json: Mapped[dict] = mapped_column(JSON, default=dict)
    source_counts_json: Mapped[dict] = mapped_column(JSON, default=dict)
    owner_counts_json: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TenantSupervisedEvaluationRecord(Base):
    __tablename__ = "tenant_supervised_evaluations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "policy_id"],
            ["tenant_rollout_policies.tenant_id", "tenant_rollout_policies.id"],
            ondelete="RESTRICT",
            name="fk_tenant_supervised_evaluation_tenant_policy",
        ),
        CheckConstraint(
            "evidence_level IN ('supervised', 'insufficient_maturity', 'insufficient_labels')",
            name="ck_tenant_supervised_evaluation_level",
        ),
        CheckConstraint(
            "status IN ('draft', 'pending_review', 'approved', 'rejected')",
            name="ck_tenant_supervised_evaluation_status",
        ),
        CheckConstraint(
            "governance_decision IS NULL OR governance_decision IN ('retain_champion', 'promote_candidate', 'reject_candidate', 'continue_observation')",
            name="ck_tenant_supervised_evaluation_decision",
        ),
        Index("ix_tenant_supervised_evaluation_policy_created", "tenant_id", "policy_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    policy_id: Mapped[str] = mapped_column(String(36), index=True)
    evaluation_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    config_json: Mapped[dict] = mapped_column(JSON)
    coverage_json: Mapped[dict] = mapped_column(JSON)
    metrics_json: Mapped[dict] = mapped_column(JSON)
    evidence_level: Mapped[str] = mapped_column(String(32), index=True)
    label_watermark_json: Mapped[dict] = mapped_column(JSON)
    label_definition_id: Mapped[str | None] = mapped_column(ForeignKey("tenant_outcome_label_definitions.id", ondelete="RESTRICT"), nullable=True, index=True)
    label_definition_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    label_definition_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    tenant_monitoring_run_id: Mapped[str | None] = mapped_column(ForeignKey("tenant_monitoring_runs.id", ondelete="RESTRICT"), nullable=True, index=True)
    tenant_monitoring_evidence_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    evidence_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    governance_decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    submitted_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    submitted_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(128))
    created_by_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    __mapper_args__ = {"version_id_col": row_version}


class TenantSupervisedUpgradeDecisionRecord(Base):
    __tablename__ = "tenant_supervised_upgrade_decisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "policy_id"],
            ["tenant_rollout_policies.tenant_id", "tenant_rollout_policies.id"],
            ondelete="RESTRICT",
            name="fk_tenant_supervised_upgrade_tenant_policy",
        ),
        UniqueConstraint("tenant_id", "evaluation_id", name="uq_tenant_supervised_upgrade_evaluation"),
        UniqueConstraint("model_change_id", name="uq_tenant_supervised_upgrade_model_change"),
        CheckConstraint("status IN ('ready', 'draft_created')", name="ck_tenant_supervised_upgrade_status"),
        CheckConstraint("decision = 'promote_candidate'", name="ck_tenant_supervised_upgrade_decision"),
        Index("ix_tenant_supervised_upgrade_policy_created", "tenant_id", "policy_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    policy_id: Mapped[str] = mapped_column(String(36), index=True)
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("tenant_supervised_evaluations.id", ondelete="RESTRICT"), index=True)
    decision: Mapped[str] = mapped_column(String(32), default="promote_candidate")
    status: Mapped[str] = mapped_column(String(32), default="ready", index=True)
    evidence_hash: Mapped[str] = mapped_column(String(64), index=True)
    model_change_id: Mapped[str | None] = mapped_column(ForeignKey("model_changes.id", ondelete="RESTRICT"), nullable=True, index=True)
    candidate_version: Mapped[str] = mapped_column(String(128))
    created_by: Mapped[str] = mapped_column(String(128))
    created_by_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class TenantRolloutScanRecord(Base):
    __tablename__ = "tenant_rollout_scans"
    __table_args__ = (
        UniqueConstraint("run_key", name="uq_tenant_rollout_scan_key"),
        CheckConstraint("status IN ('no_due', 'completed', 'partial', 'failed')", name="ck_tenant_rollout_scan_status"),
        Index("ix_tenant_rollout_scan_scope_created", "tenant_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_key: Mapped[str] = mapped_column(String(160), index=True)
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=True)
    trigger_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    scan_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    results_json: Mapped[list] = mapped_column(JSON, default=list)
    evidence_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TenantAssetBindingRecord(Base):
    __tablename__ = "tenant_asset_bindings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "asset_type", "asset_code", name="uq_tenant_asset_binding"),
        CheckConstraint(
            "asset_type IN ('indicator', 'scorecard', 'model', 'rule', 'rule_set', 'pipeline')",
            name="ck_tenant_asset_binding_type",
        ),
        CheckConstraint(
            "binding_mode IN ('inherit_active', 'pinned')",
            name="ck_tenant_asset_binding_mode",
        ),
        CheckConstraint("status IN ('active', 'suspended')", name="ck_tenant_asset_binding_status"),
        CheckConstraint(
            "(binding_mode = 'pinned' AND pinned_version IS NOT NULL) "
            "OR (binding_mode = 'inherit_active' AND pinned_version IS NULL)",
            name="ck_tenant_asset_binding_pin",
        ),
        Index("ix_tenant_asset_binding_tenant_status", "tenant_id", "status", "asset_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    asset_type: Mapped[str] = mapped_column(String(32), index=True)
    asset_code: Mapped[str] = mapped_column(String(128), index=True)
    binding_mode: Mapped[str] = mapped_column(String(32), default="inherit_active")
    pinned_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    allow_tenant_override: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    resolved_scope: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resolved_asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    resolved_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resolved_config_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    change_reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(128))
    created_by_name: Mapped[str] = mapped_column(String(128))
    updated_by: Mapped[str] = mapped_column(String(128))
    updated_by_name: Mapped[str] = mapped_column(String(128))
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class TenantAssetOverrideRecord(Base):
    __tablename__ = "tenant_asset_overrides"
    __table_args__ = (
        UniqueConstraint("tenant_id", "asset_type", "asset_code", "version", name="uq_tenant_asset_override_version"),
        CheckConstraint(
            "asset_type IN ('indicator', 'scorecard', 'model', 'rule', 'rule_set', 'pipeline')",
            name="ck_tenant_asset_override_type",
        ),
        CheckConstraint(
            "status IN ('draft', 'pending_review', 'published', 'rejected', 'retired')",
            name="ck_tenant_asset_override_status",
        ),
        Index("ix_tenant_asset_override_tenant_status", "tenant_id", "status", "asset_type"),
        Index(
            "uq_tenant_asset_override_one_active",
            "tenant_id",
            "asset_type",
            "asset_code",
            unique=True,
            sqlite_where=text("is_active = 1"),
            postgresql_where=text("is_active IS TRUE"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    asset_type: Mapped[str] = mapped_column(String(32), index=True)
    asset_code: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[int] = mapped_column(Integer)
    base_asset_id: Mapped[str] = mapped_column(String(36))
    base_version: Mapped[str] = mapped_column(String(128))
    base_config_hash: Mapped[str] = mapped_column(String(64))
    config_json: Mapped[dict] = mapped_column(JSON)
    config_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    change_reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(128))
    created_by_name: Mapped[str] = mapped_column(String(128))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class CounterpartyRecord(Base):
    __tablename__ = "counterparties"
    __table_args__ = (
        UniqueConstraint("tenant_id", "counterparty_id", name="uq_counterparty_tenant_business_id"),
        UniqueConstraint("tenant_id", "credit_code", name="uq_counterparty_tenant_credit_code"),
        CheckConstraint("counterparty_type IN ('supplier', 'customer')", name="ck_counterparty_type"),
        CheckConstraint("status IN ('active', 'archived')", name="ck_counterparty_status"),
        CheckConstraint("requested_limit >= 0", name="ck_counterparty_requested_limit_nonnegative"),
        CheckConstraint("current_limit >= 0", name="ck_counterparty_current_limit_nonnegative"),
        CheckConstraint("current_payment_term_days >= 0", name="ck_counterparty_payment_term_nonnegative"),
        Index("ix_counterparty_tenant_status_updated", "tenant_id", "status", "updated_at"),
        Index("ix_counterparty_tenant_type_name", "tenant_id", "counterparty_type", "name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), index=True)
    counterparty_id: Mapped[str] = mapped_column(String(128), index=True)
    credit_code: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    counterparty_type: Mapped[str] = mapped_column(String(32), index=True)
    industry: Mapped[str] = mapped_column(String(128), index=True)
    cooperation_status: Mapped[str] = mapped_column(String(64), default="pending", index=True)
    is_key_counterparty: Mapped[bool] = mapped_column(Boolean, default=False)
    requested_limit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    current_limit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    current_payment_term_days: Mapped[int] = mapped_column(Integer, default=0)
    current_rating: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    current_segment: Mapped[str | None] = mapped_column(String(128), nullable=True)
    external_json: Mapped[dict] = mapped_column(JSON, default=dict)
    internal_json: Mapped[dict] = mapped_column(JSON, default=dict)
    financial_json: Mapped[dict] = mapped_column(JSON, default=dict)
    extensions_json: Mapped[dict] = mapped_column(JSON, default=dict)
    profile_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    source_type: Mapped[str] = mapped_column(String(32), default="manual", index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    archive_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(128))
    updated_by: Mapped[str] = mapped_column(String(128))
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class CounterpartyImportBatchRecord(Base):
    __tablename__ = "counterparty_import_batches"
    __table_args__ = (
        UniqueConstraint("tenant_id", "import_key", name="uq_counterparty_import_tenant_key"),
        CheckConstraint("file_format IN ('json', 'csv')", name="ck_counterparty_import_file_format"),
        CheckConstraint("duplicate_strategy IN ('reject', 'skip', 'update')", name="ck_counterparty_import_duplicate_strategy"),
        CheckConstraint("status IN ('prechecked', 'blocked', 'committed')", name="ck_counterparty_import_status"),
        CheckConstraint("total_count >= 0", name="ck_counterparty_import_total_nonnegative"),
        CheckConstraint("valid_count >= 0 AND invalid_count >= 0", name="ck_counterparty_import_validation_counts_nonnegative"),
        Index("ix_counterparty_import_tenant_status_created", "tenant_id", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), index=True)
    import_key: Mapped[str] = mapped_column(String(128), index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    file_format: Mapped[str] = mapped_column(String(16), index=True)
    duplicate_strategy: Mapped[str] = mapped_column(String(16), index=True)
    field_mapping_json: Mapped[dict] = mapped_column(JSON, default=dict)
    source_content: Mapped[str] = mapped_column(Text)
    source_hash: Mapped[str] = mapped_column(String(64), index=True)
    request_hash: Mapped[str] = mapped_column(String(64), index=True)
    preview_hash: Mapped[str] = mapped_column(String(64), index=True)
    normalized_rows_json: Mapped[list] = mapped_column(JSON, default=list)
    row_receipts_json: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), index=True)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    valid_count: Mapped[int] = mapped_column(Integer, default=0)
    invalid_count: Mapped[int] = mapped_column(Integer, default=0)
    create_count: Mapped[int] = mapped_column(Integer, default=0)
    update_count: Mapped[int] = mapped_column(Integer, default=0)
    skip_count: Mapped[int] = mapped_column(Integer, default=0)
    committed_count: Mapped[int] = mapped_column(Integer, default=0)
    precheck_reason: Mapped[str] = mapped_column(Text)
    commit_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(128), index=True)
    created_by_name: Mapped[str] = mapped_column(String(128))
    committed_by: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    committed_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class CounterpartyImportMappingTemplateRecord(Base):
    __tablename__ = "counterparty_import_mapping_templates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "template_key", name="uq_counterparty_import_mapping_tenant_key"),
        CheckConstraint("file_format IN ('json', 'csv')", name="ck_counterparty_import_mapping_file_format"),
        CheckConstraint("status IN ('active', 'archived')", name="ck_counterparty_import_mapping_status"),
        Index("ix_counterparty_import_mapping_tenant_status_updated", "tenant_id", "status", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), index=True)
    template_key: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(255))
    file_format: Mapped[str] = mapped_column(String(16), index=True)
    mapping_json: Mapped[dict] = mapped_column(JSON, default=dict)
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    created_by: Mapped[str] = mapped_column(String(128), index=True)
    updated_by: Mapped[str] = mapped_column(String(128), index=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class ApprovalCaseRecord(Base):
    __tablename__ = "approval_cases"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "counterparty_id"],
            ["counterparties.tenant_id", "counterparties.counterparty_id"],
            name="fk_approval_case_tenant_counterparty",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "case_id", name="uq_approval_case_tenant_id"),
        Index("ix_approval_cases_tenant_counterparty_created", "tenant_id", "counterparty_id", "created_at"),
        Index("ix_approval_cases_tenant_status_created", "tenant_id", "status", "created_at"),
        Index(
            "uq_approval_cases_open_renewal",
            "source_facility_id",
            unique=True,
            sqlite_where=text("source_facility_id IS NOT NULL AND status IN ('处理中', '待补件')"),
            postgresql_where=text("source_facility_id IS NOT NULL AND status IN ('处理中', '待补件')"),
        ),
    )

    case_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    counterparty_id: Mapped[str] = mapped_column(String(128), index=True)
    counterparty_name: Mapped[str] = mapped_column(String(255))
    application_type: Mapped[str] = mapped_column(String(32), default="new_credit", index=True)
    source_facility_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    current_stage: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), index=True)
    completed_stages: Mapped[list] = mapped_column(JSON, default=list)
    case_data: Mapped[dict] = mapped_column("data", JSON, default=dict)
    timeline: Mapped[list] = mapped_column(JSON, default=list)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    stage_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stage_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    assigned_to: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    assigned_to_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assignment_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class AuditEventRecord(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(
            "(scope_type = 'platform' AND tenant_id = 'tenant-platform-internal') "
            "OR (scope_type = 'tenant' AND tenant_id <> 'tenant-platform-internal')",
            name="ck_audit_scope_tenant",
        ),
        Index("ix_audit_tenant_aggregate", "tenant_id", "aggregate_type", "aggregate_id", "created_at"),
        UniqueConstraint(
            "tenant_id",
            "aggregate_type",
            "aggregate_id",
            "previous_hash",
            name="uq_audit_tenant_chain_parent",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), index=True)
    scope_type: Mapped[str] = mapped_column(String(16))
    aggregate_type: Mapped[str] = mapped_column(String(64), index=True)
    aggregate_id: Mapped[str] = mapped_column(String(128), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    actor: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict] = mapped_column(JSON)
    previous_hash: Mapped[str] = mapped_column(String(64), default="")
    event_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class SlaScanLeaseRecord(Base):
    __tablename__ = "sla_scan_leases"

    lease_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    execution_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    run_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    actor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    trigger_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    acquired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


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
        Index(
            "uq_rule_center_change_one_scheduled",
            "entity_type",
            "template_key",
            unique=True,
            sqlite_where=text(
                "status = 'scheduled' AND entity_type IN ('rule', 'rule_set', 'pipeline')"
            ),
            postgresql_where=text(
                "status = 'scheduled' AND entity_type IN ('rule', 'rule_set', 'pipeline')"
            ),
        ),
        UniqueConstraint(
            "entity_type",
            "template_key",
            "candidate_version",
            name="uq_model_change_candidate_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    template_key: Mapped[str] = mapped_column(String(64), index=True)
    base_version: Mapped[str] = mapped_column(String(128))
    candidate_version: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    config_json: Mapped[dict] = mapped_column(JSON)
    validation_json: Mapped[dict] = mapped_column(JSON)
    impact_json: Mapped[dict] = mapped_column(JSON)
    comparison_evidence_json: Mapped[dict] = mapped_column(JSON, default=dict)
    supervised_validation_evidence_json: Mapped[dict] = mapped_column(JSON, default=dict)
    supervised_validation_binding_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    scorecard_validation_run_id: Mapped[str | None] = mapped_column(ForeignKey("scorecard_development_runs.id", ondelete="RESTRICT"), nullable=True, index=True)
    scorecard_validation_evidence_json: Mapped[dict] = mapped_column(JSON, default=dict)
    scorecard_validation_binding_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    calibration_snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("rule_center_replay_dataset_snapshots.id", ondelete="RESTRICT"), nullable=True, index=True)
    calibration_evidence_json: Mapped[dict] = mapped_column(JSON, default=dict)
    calibration_evidence_binding_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    change_reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(128), index=True)
    created_by_name: Mapped[str] = mapped_column(String(128))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    entity_type: Mapped[str] = mapped_column(
        String(32), default="model", server_default="model", index=True
    )
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class SupervisedValidationAttachmentRecord(Base):
    __tablename__ = "supervised_validation_attachments"
    __table_args__ = (
        UniqueConstraint("model_change_id", "sha256", name="uq_supervised_validation_attachment_hash"),
        CheckConstraint("status IN ('active', 'revoked')", name="ck_supervised_validation_attachment_status"),
        CheckConstraint("scan_status IN ('not_scanned', 'pending', 'passed', 'rejected')", name="ck_supervised_validation_attachment_scan_status"),
        CheckConstraint("size_bytes > 0", name="ck_supervised_validation_attachment_size"),
        Index("ix_supervised_validation_attachment_change_status", "model_change_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    model_change_id: Mapped[str] = mapped_column(ForeignKey("model_changes.id", ondelete="RESTRICT"), index=True)
    original_name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_key: Mapped[str] = mapped_column(String(512), unique=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    scan_status: Mapped[str] = mapped_column(String(32), default="not_scanned", index=True)
    scan_engine: Mapped[str | None] = mapped_column(String(128), nullable=True)
    scan_result_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    scan_completed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    scan_completed_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    scan_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)

    __mapper_args__ = {"version_id_col": row_version}
    uploaded_by: Mapped[str] = mapped_column(String(128))
    uploaded_by_name: Mapped[str] = mapped_column(String(128))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class ModelValidationReportIssuanceRecord(Base):
    __tablename__ = "model_validation_report_issuances"
    __table_args__ = (
        Index("ix_model_validation_issuance_change_issued", "model_change_id", "issued_at"),
        Index(
            "uq_model_validation_issuance_active_change_report",
            "model_change_id", "report_hash", unique=True,
            sqlite_where=text("revoked_at IS NULL"),
            postgresql_where=text("revoked_at IS NULL"),
        ),
        UniqueConstraint("signature", name="uq_model_validation_issuance_signature"),
        UniqueConstraint("supersedes_issuance_id", name="uq_model_validation_issuance_supersedes"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    model_change_id: Mapped[str] = mapped_column(ForeignKey("model_changes.id", ondelete="RESTRICT"), index=True)
    report_template_version: Mapped[str] = mapped_column(String(64))
    report_hash: Mapped[str] = mapped_column(String(64), index=True)
    evidence_binding_hash: Mapped[str] = mapped_column(String(64), index=True)
    package_json: Mapped[dict] = mapped_column(JSON)
    package_hash: Mapped[str] = mapped_column(String(64), index=True)
    signature_algorithm: Mapped[str] = mapped_column(String(64), default="SHA-256-CANONICAL-JSON")
    signing_key_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    signing_public_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    signature: Mapped[str] = mapped_column(Text)
    issued_by: Mapped[str] = mapped_column(String(128), index=True)
    issued_by_name: Mapped[str] = mapped_column(String(128))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_by: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    revoked_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    revocation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    supersedes_issuance_id: Mapped[str | None] = mapped_column(ForeignKey("model_validation_report_issuances.id", ondelete="RESTRICT"), nullable=True, index=True)
    reissue_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class TenantModelRiskPolicyRecord(Base):
    __tablename__ = "tenant_model_risk_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", "version", name="uq_tenant_model_risk_policy_version"),
        CheckConstraint(
            "status IN ('draft', 'pending_review', 'published', 'rejected', 'retired')",
            name="ck_tenant_model_risk_policy_status",
        ),
        Index("ix_tenant_model_risk_policy_tenant_status", "tenant_id", "status", "version"),
        Index(
            "uq_tenant_model_risk_policy_active",
            "tenant_id",
            unique=True,
            sqlite_where=text("is_active = 1"),
            postgresql_where=text("is_active IS TRUE"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    levels_json: Mapped[list] = mapped_column(JSON)
    config_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
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


class ModelRiskAcceptanceRecord(Base):
    __tablename__ = "model_risk_acceptances"
    __table_args__ = (
        CheckConstraint("risk_level IN ('low', 'medium', 'high')", name="ck_model_risk_acceptance_level"),
        CheckConstraint("status IN ('pending', 'accepted', 'revoked')", name="ck_model_risk_acceptance_status"),
        Index("ix_model_risk_acceptance_change_status", "tenant_id", "model_change_id", "status"),
        Index(
            "uq_model_risk_acceptance_active_change",
            "tenant_id", "model_change_id",
            unique=True,
            sqlite_where=text("status IN ('pending', 'accepted')"),
            postgresql_where=text("status IN ('pending', 'accepted')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    model_change_id: Mapped[str] = mapped_column(ForeignKey("model_changes.id", ondelete="RESTRICT"), index=True)
    policy_id: Mapped[str] = mapped_column(ForeignKey("tenant_model_risk_policies.id", ondelete="RESTRICT"), index=True)
    policy_version: Mapped[int] = mapped_column(Integer)
    policy_config_hash: Mapped[str] = mapped_column(String(64), index=True)
    evidence_binding_hash: Mapped[str] = mapped_column(String(64), index=True)
    risk_level: Mapped[str] = mapped_column(String(16), index=True)
    required_roles_json: Mapped[list] = mapped_column(JSON)
    approvals_json: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    rationale: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(128), index=True)
    created_by_name: Mapped[str] = mapped_column(String(128))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    review_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    revoked_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    revoked_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class ModelRiskReacceptanceRecord(Base):
    __tablename__ = "model_risk_reacceptances"
    __table_args__ = (
        CheckConstraint("risk_level IN ('low', 'medium', 'high')", name="ck_model_risk_reacceptance_level"),
        CheckConstraint("status IN ('pending', 'accepted', 'revoked')", name="ck_model_risk_reacceptance_status"),
        Index("ix_model_risk_reacceptance_release_status", "tenant_id", "model_release_id", "status"),
        Index("uq_model_risk_reacceptance_pending_release", "tenant_id", "model_release_id", unique=True,
              sqlite_where=text("status = 'pending'"), postgresql_where=text("status = 'pending'")),
        Index("uq_model_risk_reacceptance_accepted_release", "tenant_id", "model_release_id", unique=True,
              sqlite_where=text("status = 'accepted'"), postgresql_where=text("status = 'accepted'")),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    model_release_id: Mapped[str] = mapped_column(ForeignKey("model_releases.id", ondelete="RESTRICT"), index=True)
    model_change_id: Mapped[str] = mapped_column(ForeignKey("model_changes.id", ondelete="RESTRICT"), index=True)
    prior_acceptance_id: Mapped[str] = mapped_column(ForeignKey("model_risk_acceptances.id", ondelete="RESTRICT"), index=True)
    policy_id: Mapped[str] = mapped_column(ForeignKey("tenant_model_risk_policies.id", ondelete="RESTRICT"), index=True)
    policy_version: Mapped[int] = mapped_column(Integer)
    policy_config_hash: Mapped[str] = mapped_column(String(64), index=True)
    source_evidence_binding_hash: Mapped[str] = mapped_column(String(64), index=True)
    release_config_hash: Mapped[str] = mapped_column(String(64), index=True)
    operational_evidence_json: Mapped[dict] = mapped_column(JSON)
    operational_evidence_hash: Mapped[str] = mapped_column(String(64), index=True)
    monitoring_run_id: Mapped[str | None] = mapped_column(ForeignKey("model_monitoring_runs.id", ondelete="RESTRICT"), nullable=True, index=True)
    monitoring_evidence_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    label_evidence_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    risk_level: Mapped[str] = mapped_column(String(16), index=True)
    required_roles_json: Mapped[list] = mapped_column(JSON)
    approvals_json: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    rationale: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(128), index=True)
    created_by_name: Mapped[str] = mapped_column(String(128))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    review_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    revoked_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    revoked_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class RuleCenterReleasePackage(Base):
    __tablename__ = "rule_center_release_packages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    change_reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    config_hash: Mapped[str] = mapped_column(String(64), index=True)
    dependency_snapshot_json: Mapped[dict] = mapped_column(JSON, default=dict)
    impact_json: Mapped[dict] = mapped_column(JSON, default=dict)
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


class RuleCenterReleasePackageMember(Base):
    __tablename__ = "rule_center_release_package_members"
    __table_args__ = (
        UniqueConstraint("package_id", "change_id", name="uq_rule_center_package_change"),
        UniqueConstraint("package_id", "asset_type", "code", name="uq_rule_center_package_asset"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    package_id: Mapped[str] = mapped_column(ForeignKey("rule_center_release_packages.id", ondelete="CASCADE"), index=True)
    change_id: Mapped[str] = mapped_column(ForeignKey("model_changes.id", ondelete="RESTRICT"), index=True)
    asset_type: Mapped[str] = mapped_column(String(32), index=True)
    code: Mapped[str] = mapped_column(String(128), index=True)
    candidate_version: Mapped[str] = mapped_column(String(128))
    sequence: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RuleCenterReplayDataset(Base):
    __tablename__ = "rule_center_replay_datasets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_rule_center_replay_dataset_tenant_id"),
        UniqueConstraint("tenant_id", "code", name="uq_rule_center_replay_dataset_tenant_code"),
        Index("ix_rule_center_replay_dataset_tenant_status", "tenant_id", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    created_by: Mapped[str] = mapped_column(String(128), index=True)
    created_by_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class RuleCenterReplayDatasetSnapshot(Base):
    __tablename__ = "rule_center_replay_dataset_snapshots"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_rule_center_replay_snapshot_tenant_id"),
        UniqueConstraint("tenant_id", "dataset_id", "version", name="uq_rule_center_replay_dataset_version"),
        UniqueConstraint("tenant_id", "dataset_id", "source_hash", name="uq_rule_center_replay_dataset_source"),
        ForeignKeyConstraint(
            ["tenant_id", "dataset_id"],
            ["rule_center_replay_datasets.tenant_id", "rule_center_replay_datasets.id"],
            ondelete="CASCADE",
            name="fk_rule_center_replay_snapshot_tenant_dataset",
        ),
        Index("ix_rule_center_replay_snapshot_tenant_dataset_created", "tenant_id", "dataset_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    dataset_id: Mapped[str] = mapped_column(String(36), index=True)
    version: Mapped[int] = mapped_column(Integer)
    source_name: Mapped[str] = mapped_column(String(256))
    schema_version: Mapped[str] = mapped_column(String(64))
    as_of_date: Mapped[date] = mapped_column(Date, index=True)
    evidence_reference: Mapped[str] = mapped_column(Text)
    data_classification: Mapped[str] = mapped_column(String(32))
    field_mapping_json: Mapped[dict] = mapped_column(JSON, default=dict)
    label_field: Mapped[str | None] = mapped_column(String(256), nullable=True)
    observed_at_field: Mapped[str | None] = mapped_column(String(256), nullable=True)
    sample_count: Mapped[int] = mapped_column(Integer)
    samples_json: Mapped[list] = mapped_column(JSON, default=list)
    coverage_json: Mapped[dict] = mapped_column(JSON, default=dict)
    source_hash: Mapped[str] = mapped_column(String(64), index=True)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_by: Mapped[str] = mapped_column(String(128), index=True)
    created_by_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class RuleCenterReplayRun(Base):
    __tablename__ = "rule_center_replay_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "dataset_snapshot_id"],
            ["rule_center_replay_dataset_snapshots.tenant_id", "rule_center_replay_dataset_snapshots.id"],
            ondelete="RESTRICT",
            name="fk_rule_center_replay_run_tenant_snapshot",
        ),
        Index("ix_rule_center_replay_tenant_package_created", "tenant_id", "package_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    package_id: Mapped[str] = mapped_column(ForeignKey("rule_center_release_packages.id", ondelete="CASCADE"), index=True)
    package_config_hash: Mapped[str] = mapped_column(String(64), index=True)
    dataset_snapshot_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    dataset_snapshot_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    model_key: Mapped[str] = mapped_column(String(64), index=True)
    model_version: Mapped[str] = mapped_column(String(128))
    pipeline_code: Mapped[str] = mapped_column(String(128), index=True)
    sample_source: Mapped[str] = mapped_column(String(64), default="demo_counterparties")
    sample_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    thresholds_json: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics_json: Mapped[dict] = mapped_column(JSON, default=dict)
    details_json: Mapped[list] = mapped_column(JSON, default=list)
    gate_json: Mapped[dict] = mapped_column(JSON, default=dict)
    asset_snapshot_json: Mapped[dict] = mapped_column(JSON, default=dict)
    assets_hash: Mapped[str] = mapped_column(String(64), index=True)
    evidence_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_by: Mapped[str] = mapped_column(String(128), index=True)
    created_by_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class RuleCenterReplayComparisonRun(Base):
    __tablename__ = "rule_center_replay_comparison_runs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_rule_center_replay_comparison_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "dataset_snapshot_id"],
            ["rule_center_replay_dataset_snapshots.tenant_id", "rule_center_replay_dataset_snapshots.id"],
            ondelete="RESTRICT",
            name="fk_rule_center_replay_comparison_tenant_snapshot",
        ),
        Index("ix_rule_center_replay_comparison_tenant_snapshot_created", "tenant_id", "dataset_snapshot_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    dataset_snapshot_id: Mapped[str] = mapped_column(String(36), index=True)
    dataset_snapshot_hash: Mapped[str] = mapped_column(String(64), index=True)
    champion_model_key: Mapped[str] = mapped_column(String(64), index=True)
    champion_model_version: Mapped[str] = mapped_column(String(128))
    challenger_model_key: Mapped[str] = mapped_column(String(64), index=True)
    challenger_model_version: Mapped[str] = mapped_column(String(128))
    challenger_change_id: Mapped[str | None] = mapped_column(ForeignKey("model_changes.id", ondelete="RESTRICT"), nullable=True, index=True)
    challenger_config_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    champion_pipeline_code: Mapped[str] = mapped_column(String(128))
    champion_pipeline_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    challenger_pipeline_code: Mapped[str] = mapped_column(String(128))
    challenger_pipeline_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    segment_field: Mapped[str] = mapped_column(String(256))
    evidence_level: Mapped[str] = mapped_column(String(32), index=True)
    config_json: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics_json: Mapped[dict] = mapped_column(JSON, default=dict)
    details_json: Mapped[list] = mapped_column(JSON, default=list)
    gate_json: Mapped[dict] = mapped_column(JSON, default=dict)
    asset_snapshot_json: Mapped[dict] = mapped_column(JSON, default=dict)
    assets_hash: Mapped[str] = mapped_column(String(64), index=True)
    evidence_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_by: Mapped[str] = mapped_column(String(128), index=True)
    created_by_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class RuleCenterReplayComparisonException(Base):
    __tablename__ = "rule_center_replay_comparison_exceptions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "comparison_run_id"],
            ["rule_center_replay_comparison_runs.tenant_id", "rule_center_replay_comparison_runs.id"],
            ondelete="CASCADE",
            name="fk_replay_comparison_exception_tenant_run",
        ),
        Index("ix_replay_comparison_exception_tenant_run_created", "tenant_id", "comparison_run_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    comparison_run_id: Mapped[str] = mapped_column(String(36), index=True)
    comparison_evidence_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending_review", index=True)
    reason: Mapped[str] = mapped_column(Text)
    business_impact: Mapped[str] = mapped_column(Text)
    compensating_controls: Mapped[str] = mapped_column(Text)
    valid_until: Mapped[date] = mapped_column(Date, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), index=True)
    requested_by: Mapped[str] = mapped_column(String(128), index=True)
    requested_by_name: Mapped[str] = mapped_column(String(128))
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class CreditAuthorityPolicyRecord(Base):
    __tablename__ = "credit_authority_policies"
    __table_args__ = (
        Index("ix_authority_policies_status_created", "status", "created_at"),
        Index(
            "uq_authority_policies_one_active",
            "is_active",
            unique=True,
            sqlite_where=text("is_active = 1"),
            postgresql_where=text("is_active IS TRUE"),
        ),
        Index(
            "uq_authority_policies_one_scheduled",
            "status",
            unique=True,
            sqlite_where=text("status = 'scheduled'"),
            postgresql_where=text("status = 'scheduled'"),
        ),
        UniqueConstraint("policy_version", name="uq_authority_policy_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    policy_version: Mapped[str] = mapped_column(String(128), index=True)
    base_policy_version: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    config_json: Mapped[dict] = mapped_column(JSON)
    config_hash: Mapped[str] = mapped_column(String(64), index=True)
    impact_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    impact_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    impact_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    restore_source_policy_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    restore_source_policy_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    change_reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(128), index=True)
    created_by_name: Mapped[str] = mapped_column(String(128))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    schedule_cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    schedule_cancelled_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    schedule_cancelled_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    schedule_cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class AuthorityPolicyActivationRunRecord(Base):
    __tablename__ = "authority_policy_activation_runs"
    __table_args__ = (
        Index("ix_authority_activation_runs_status_created", "status", "created_at"),
        Index("ix_authority_activation_runs_incident_created", "incident_status", "created_at"),
        UniqueConstraint("run_key", name="uq_authority_activation_run_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_key: Mapped[str] = mapped_column(String(128), index=True)
    trigger_type: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    scheduled_policy_id: Mapped[str | None] = mapped_column(ForeignKey("credit_authority_policies.id"), nullable=True, index=True)
    scheduled_policy_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    scheduled_effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active_policy_before: Mapped[str] = mapped_column(String(128))
    active_policy_after: Mapped[str] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    incident_status: Mapped[str] = mapped_column(String(32), default="not_applicable", index=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    acknowledged_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledgement_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resolved_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_of_run_id: Mapped[str | None] = mapped_column(ForeignKey("authority_policy_activation_runs.id"), nullable=True, index=True)
    resolved_by_run_id: Mapped[str | None] = mapped_column(ForeignKey("authority_policy_activation_runs.id"), nullable=True)
    actor_subject: Mapped[str] = mapped_column(String(128))
    actor_name: Mapped[str] = mapped_column(String(128))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    __mapper_args__ = {"version_id_col": row_version}


class AuthorityPolicyEvidenceAnchorRecord(Base):
    __tablename__ = "authority_policy_evidence_anchors"
    __table_args__ = (
        Index("ix_authority_evidence_anchors_policy_issued", "policy_id", "issued_at"),
        Index(
            "uq_authority_evidence_anchor_active_policy_package",
            "policy_id",
            "package_hash",
            unique=True,
            sqlite_where=text("revoked_at IS NULL"),
            postgresql_where=text("revoked_at IS NULL"),
        ),
        UniqueConstraint("anchor_hash", name="uq_authority_policy_evidence_anchors_anchor_hash"),
        UniqueConstraint("supersedes_anchor_id", name="uq_authority_evidence_anchor_supersedes"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    policy_id: Mapped[str] = mapped_column(ForeignKey("credit_authority_policies.id"), index=True)
    policy_version: Mapped[str] = mapped_column(String(128), index=True)
    schema_version: Mapped[str] = mapped_column(String(64))
    package_json: Mapped[dict] = mapped_column(JSON)
    package_hash: Mapped[str] = mapped_column(String(64), index=True)
    anchor_hash: Mapped[str] = mapped_column(String(64))
    integrity_passed: Mapped[bool] = mapped_column(Boolean, index=True)
    issued_by: Mapped[str] = mapped_column(String(128), index=True)
    issued_by_name: Mapped[str] = mapped_column(String(128))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_by: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    revoked_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    revocation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    supersedes_anchor_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "authority_policy_evidence_anchors.id",
            name="fk_authority_evidence_anchor_supersedes",
        ),
        nullable=True,
        index=True,
    )
    replacement_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __mapper_args__ = {"version_id_col": row_version}


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
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "counterparty_id"],
            ["counterparties.tenant_id", "counterparties.counterparty_id"],
            name="fk_rating_run_tenant_counterparty",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "case_id"],
            ["approval_cases.tenant_id", "approval_cases.case_id"],
            name="fk_rating_run_tenant_case",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_rating_run_tenant_id"),
        Index("ix_rating_runs_tenant_counterparty_created", "tenant_id", "counterparty_id", "created_at"),
        Index("ix_rating_runs_tenant_case_created", "tenant_id", "case_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    counterparty_id: Mapped[str] = mapped_column(String(128), index=True)
    case_id: Mapped[str | None] = mapped_column(ForeignKey("approval_cases.case_id"), index=True, nullable=True)
    template_key: Mapped[str] = mapped_column(String(64), index=True)
    model_snapshot_id: Mapped[str] = mapped_column(ForeignKey("model_snapshots.id"), index=True)
    input_json: Mapped[dict] = mapped_column(JSON)
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    result_json: Mapped[dict] = mapped_column(JSON)
    result_hash: Mapped[str] = mapped_column(String(64), index=True)
    asset_snapshot_json: Mapped[dict] = mapped_column(JSON, default=dict)
    assets_hash: Mapped[str] = mapped_column(String(64), default="0" * 64, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class DecisionExecutionRecord(Base):
    __tablename__ = "decision_executions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "request_id", name="uq_decision_execution_tenant_request"),
        UniqueConstraint("trace_id", name="uq_decision_execution_trace_id"),
        Index("ix_decision_execution_tenant_created", "tenant_id", "created_at"),
        Index("ix_decision_execution_tenant_counterparty", "tenant_id", "counterparty_id"),
        Index("ix_decision_execution_model_created", "model_key", "model_version", "created_at"),
        Index("ix_decision_execution_pipeline_created", "pipeline_code", "pipeline_version", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    client_id: Mapped[str] = mapped_column(String(128), index=True)
    request_id: Mapped[str] = mapped_column(String(128), index=True)
    request_hash: Mapped[str] = mapped_column(String(64), index=True)
    trace_id: Mapped[str] = mapped_column(String(36), index=True)
    counterparty_id: Mapped[str] = mapped_column(String(128), index=True)
    request_json: Mapped[dict] = mapped_column(JSON)
    normalized_input_json: Mapped[dict] = mapped_column(JSON)
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    model_key: Mapped[str] = mapped_column(String(64), index=True)
    model_version: Mapped[str] = mapped_column(String(128), index=True)
    model_config_hash: Mapped[str] = mapped_column(String(64), index=True)
    pipeline_code: Mapped[str] = mapped_column(String(128), index=True)
    pipeline_version: Mapped[int] = mapped_column(Integer, index=True)
    pipeline_hash: Mapped[str] = mapped_column(String(64), index=True)
    asset_snapshot_json: Mapped[dict] = mapped_column(JSON)
    assets_hash: Mapped[str] = mapped_column(String(64), default="0" * 64, index=True)
    result_json: Mapped[dict] = mapped_column(JSON)
    result_hash: Mapped[str] = mapped_column(String(64), index=True)
    trace_json: Mapped[dict] = mapped_column(JSON)
    trace_hash: Mapped[str] = mapped_column(String(64), index=True)
    evidence_hash: Mapped[str] = mapped_column(String(64), index=True)
    elapsed_ms: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[str] = mapped_column(String(128), index=True)
    created_by_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class DecisionJobRecord(Base):
    __tablename__ = "decision_jobs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "job_key", name="uq_decision_job_tenant_key"),
        Index("ix_decision_jobs_tenant_status_created", "tenant_id", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_key: Mapped[str] = mapped_column(String(128), index=True)
    request_hash: Mapped[str] = mapped_column(String(64), index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    client_id: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    total_count: Mapped[int] = mapped_column(Integer)
    succeeded_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    request_json: Mapped[dict] = mapped_column(JSON)
    results_json: Mapped[list] = mapped_column(JSON, default=list)
    failures_json: Mapped[list] = mapped_column(JSON, default=list)
    callback_json: Mapped[dict] = mapped_column(JSON, default=dict)
    asset_snapshot_json: Mapped[dict] = mapped_column(JSON, default=dict)
    assets_hash: Mapped[str] = mapped_column(String(64), default="0" * 64, index=True)
    result_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    evidence_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(128), index=True)
    created_by_name: Mapped[str] = mapped_column(String(128))
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    __mapper_args__ = {"version_id_col": row_version}


class DecisionWebhookDeliveryRecord(Base):
    __tablename__ = "decision_webhook_deliveries"
    __table_args__ = (
        Index("ix_decision_webhooks_job_created", "job_id", "created_at"),
        Index("ix_decision_webhooks_status_next", "status", "next_attempt_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("decision_jobs.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    endpoint_url: Mapped[str] = mapped_column(String(2000))
    secret_reference: Mapped[str] = mapped_column(String(256))
    payload_json: Mapped[dict] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    signature_timestamp: Mapped[str] = mapped_column(String(32))
    signature: Mapped[str] = mapped_column(String(64))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    delivery_history_json: Mapped[list] = mapped_column(JSON, default=list)
    manual_redelivery_count: Mapped[int] = mapped_column(Integer, default=0)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PortfolioRatingBatchRecord(Base):
    __tablename__ = "portfolio_rating_batches"
    __table_args__ = (
        Index("ix_portfolio_batches_tenant_template_created", "tenant_id", "template_key", "created_at"),
        UniqueConstraint("tenant_id", "batch_key", name="uq_portfolio_rating_batch_tenant_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    batch_key: Mapped[str] = mapped_column(String(128), index=True)
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
    asset_snapshot_json: Mapped[dict] = mapped_column(JSON, default=dict)
    assets_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_by: Mapped[str] = mapped_column(String(128), index=True)
    created_by_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class CreditReportRecord(Base):
    __tablename__ = "credit_reports"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "case_id"],
            ["approval_cases.tenant_id", "approval_cases.case_id"],
            name="fk_credit_report_tenant_case",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "counterparty_id"],
            ["counterparties.tenant_id", "counterparties.counterparty_id"],
            name="fk_credit_report_tenant_counterparty",
            ondelete="RESTRICT",
        ),
        Index("ix_credit_reports_tenant_case_version", "tenant_id", "case_id", "report_version"),
        Index("ix_credit_reports_tenant_counterparty_created", "tenant_id", "counterparty_id", "created_at"),
        UniqueConstraint("tenant_id", "case_id", "snapshot_hash", name="uq_credit_report_case_snapshot"),
        UniqueConstraint("tenant_id", "case_id", "report_version", name="uq_credit_report_case_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
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
        ForeignKeyConstraint(
            ["tenant_id", "case_id"],
            ["approval_cases.tenant_id", "approval_cases.case_id"],
            name="fk_decision_variance_tenant_case",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "counterparty_id"],
            ["counterparties.tenant_id", "counterparties.counterparty_id"],
            name="fk_decision_variance_tenant_counterparty",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "rating_run_id"],
            ["rating_runs.tenant_id", "rating_runs.id"],
            name="fk_decision_variance_tenant_rating_run",
            ondelete="RESTRICT",
        ),
        Index("ix_decision_variances_tenant_direction_materiality", "tenant_id", "direction", "materiality", "decided_at"),
        UniqueConstraint("tenant_id", "case_id", name="uq_decision_variance_tenant_case"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("approval_cases.case_id"), index=True)
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
        ForeignKeyConstraint(
            ["tenant_id", "counterparty_id"],
            ["counterparties.tenant_id", "counterparties.counterparty_id"],
            name="fk_enterprise_data_import_tenant_counterparty",
            ondelete="RESTRICT",
        ),
        Index("ix_enterprise_data_imports_tenant_counterparty_created", "tenant_id", "counterparty_id", "created_at"),
        UniqueConstraint("tenant_id", "id", name="uq_enterprise_data_import_tenant_id"),
        UniqueConstraint("tenant_id", "import_key", name="uq_enterprise_data_import_tenant_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    import_key: Mapped[str] = mapped_column(String(256), index=True)
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
        ForeignKeyConstraint(
            ["tenant_id", "import_id"],
            ["enterprise_data_imports.tenant_id", "enterprise_data_imports.id"],
            name="fk_enterprise_data_field_tenant_import",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "counterparty_id"],
            ["counterparties.tenant_id", "counterparties.counterparty_id"],
            name="fk_enterprise_data_field_tenant_counterparty",
            ondelete="RESTRICT",
        ),
        Index("ix_enterprise_data_fields_tenant_counterparty_path", "tenant_id", "counterparty_id", "field_path", "observed_at"),
        UniqueConstraint("tenant_id", "id", name="uq_enterprise_data_field_tenant_id"),
        UniqueConstraint("tenant_id", "import_id", "field_path", name="uq_enterprise_data_field_tenant_import_path"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
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
        ForeignKeyConstraint(
            ["tenant_id", "counterparty_id"],
            ["counterparties.tenant_id", "counterparties.counterparty_id"],
            name="fk_enterprise_data_resolution_tenant_counterparty",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "selected_field_id"],
            ["enterprise_data_fields.tenant_id", "enterprise_data_fields.id"],
            name="fk_enterprise_data_resolution_tenant_field",
            ondelete="RESTRICT",
        ),
        Index("ix_enterprise_data_resolutions_tenant_counterparty_path", "tenant_id", "counterparty_id", "field_path", "created_at"),
        Index(
            "uq_enterprise_data_pending_resolution",
            "tenant_id",
            "counterparty_id",
            "field_path",
            unique=True,
            sqlite_where=text("status = 'pending_review'"),
            postgresql_where=text("status = 'pending_review'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
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
        ForeignKeyConstraint(
            ["tenant_id", "counterparty_id"],
            ["counterparties.tenant_id", "counterparties.counterparty_id"],
            name="fk_indicator_observation_tenant_counterparty",
            ondelete="RESTRICT",
        ),
        Index("ix_indicator_observations_tenant_counterparty_indicator", "tenant_id", "counterparty_id", "indicator_id", "created_at"),
        Index("ix_indicator_observations_tenant_status_created", "tenant_id", "status", "created_at"),
        Index(
            "uq_indicator_observations_pending",
            "tenant_id",
            "counterparty_id",
            "indicator_id",
            unique=True,
            sqlite_where=text("status = 'pending_review'"),
            postgresql_where=text("status = 'pending_review'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
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
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "counterparty_id"],
            ["counterparties.tenant_id", "counterparties.counterparty_id"],
            name="fk_document_tenant_counterparty",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "case_id"],
            ["approval_cases.tenant_id", "approval_cases.case_id"],
            name="fk_document_tenant_case",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "source_document_id"],
            ["documents.tenant_id", "documents.id"],
            name="fk_document_tenant_source",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_document_tenant_id"),
        Index("ix_documents_tenant_counterparty_case", "tenant_id", "counterparty_id", "case_id", "created_at"),
        UniqueConstraint("tenant_id", "case_id", "source_document_id", name="uq_documents_case_source_document"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
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
    source_document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"), nullable=True, index=True)
    carried_over_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    carried_over_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    __mapper_args__ = {"version_id_col": row_version}


class DocumentCorrectionRecord(Base):
    __tablename__ = "document_corrections"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "counterparty_id"],
            ["counterparties.tenant_id", "counterparties.counterparty_id"],
            name="fk_document_correction_tenant_counterparty",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "case_id"],
            ["approval_cases.tenant_id", "approval_cases.case_id"],
            name="fk_document_correction_tenant_case",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "original_document_id"],
            ["documents.tenant_id", "documents.id"],
            name="fk_document_correction_tenant_original",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "current_document_id"],
            ["documents.tenant_id", "documents.id"],
            name="fk_document_correction_tenant_current",
            ondelete="RESTRICT",
        ),
        Index("ix_document_corrections_tenant_scope_status", "tenant_id", "counterparty_id", "case_id", "status", "created_at"),
        Index("ix_document_corrections_tenant_sla_status", "tenant_id", "status", "sla_due_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
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
    assigned_role: Mapped[str] = mapped_column(String(64), index=True)
    assigned_to: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    assigned_to_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assignment_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sla_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    sla_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    reminder_count: Mapped[int] = mapped_column(Integer, default=0)
    last_reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extension_count: Mapped[int] = mapped_column(Integer, default=0)
    total_extension_hours: Mapped[int] = mapped_column(Integer, default=0)
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
        ForeignKeyConstraint(
            ["tenant_id", "case_id"],
            ["approval_cases.tenant_id", "approval_cases.case_id"],
            name="fk_notification_tenant_case",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "counterparty_id"],
            ["counterparties.tenant_id", "counterparties.counterparty_id"],
            name="fk_notification_tenant_counterparty",
            ondelete="RESTRICT",
        ),
        Index("ix_notifications_tenant_role_status_created", "tenant_id", "recipient_role", "status", "created_at"),
        Index("ix_notifications_tenant_subject_status_created", "tenant_id", "recipient_subject", "status", "created_at"),
        UniqueConstraint("tenant_id", "dedup_key", name="uq_notifications_tenant_dedup_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), index=True)
    case_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    counterparty_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    recipient_role: Mapped[str] = mapped_column(String(64), index=True)
    recipient_subject: Mapped[str | None] = mapped_column(String(128), nullable=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    level: Mapped[str] = mapped_column(String(32), index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    action_json: Mapped[dict] = mapped_column(JSON, default=dict)
    dedup_key: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(16), default="unread", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TenantNotificationChannelRecord(Base):
    """Tenant-owned outbound notification routing policy."""

    __tablename__ = "tenant_notification_channels"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_tenant_notification_channel_name"),
        UniqueConstraint("tenant_id", "id", name="uq_tenant_notification_channel_tenant_id"),
        CheckConstraint("status IN ('active', 'disabled')", name="ck_tenant_notification_channel_status"),
        CheckConstraint("channel_type IN ('webhook')", name="ck_tenant_notification_channel_type"),
        CheckConstraint("delivery_mode IN ('sandbox', 'live')", name="ck_tenant_notification_channel_mode"),
        CheckConstraint("minimum_severity IN ('info', 'warning', 'critical')", name="ck_tenant_notification_channel_severity"),
        CheckConstraint("max_attempts BETWEEN 1 AND 10", name="ck_tenant_notification_channel_attempts"),
        CheckConstraint("timeout_seconds BETWEEN 1 AND 30", name="ck_tenant_notification_channel_timeout"),
        Index("ix_tenant_notification_channel_status", "tenant_id", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    channel_type: Mapped[str] = mapped_column(String(32), default="webhook")
    delivery_mode: Mapped[str] = mapped_column(String(32), default="sandbox")
    endpoint_url: Mapped[str] = mapped_column(String(2000))
    secret_reference: Mapped[str] = mapped_column(String(256))
    subscribed_categories_json: Mapped[list] = mapped_column(JSON, default=list)
    recipient_roles_json: Mapped[list] = mapped_column(JSON, default=list)
    minimum_severity: Mapped[str] = mapped_column(String(16), default="warning")
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=5)
    require_receipt: Mapped[bool] = mapped_column(Boolean, default=True)
    sandbox_status_sequence_json: Mapped[list] = mapped_column(JSON, default=lambda: [200])
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    created_by: Mapped[str] = mapped_column(String(128))
    created_by_name: Mapped[str] = mapped_column(String(255))
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class TenantNotificationDeliveryRecord(Base):
    """Immutable-payload delivery evidence derived from a tenant notification."""

    __tablename__ = "tenant_notification_deliveries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "channel_id"],
            ["tenant_notification_channels.tenant_id", "tenant_notification_channels.id"],
            name="fk_tenant_notification_delivery_channel",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_notification_delivery_key"),
        CheckConstraint(
            "status IN ('pending', 'retry_scheduled', 'delivered', 'dead_letter', 'cancelled')",
            name="ck_tenant_notification_delivery_status",
        ),
        CheckConstraint("delivery_mode IN ('sandbox', 'live')", name="ck_tenant_notification_delivery_mode"),
        CheckConstraint("attempt_count >= 0", name="ck_tenant_notification_delivery_attempts"),
        CheckConstraint("max_attempts BETWEEN 1 AND 10", name="ck_tenant_notification_delivery_max_attempts"),
        Index("ix_tenant_notification_delivery_status", "tenant_id", "status", "next_attempt_at"),
        Index("ix_tenant_notification_delivery_notification", "tenant_id", "notification_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    channel_id: Mapped[str] = mapped_column(String(36), index=True)
    notification_id: Mapped[str] = mapped_column(ForeignKey("notifications.id", ondelete="RESTRICT"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(512))
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    endpoint_url: Mapped[str] = mapped_column(String(2000))
    delivery_mode: Mapped[str] = mapped_column(String(32))
    secret_reference: Mapped[str] = mapped_column(String(256))
    require_receipt: Mapped[bool] = mapped_column(Boolean, default=True)
    transport_config_json: Mapped[dict] = mapped_column(JSON, default=dict)
    channel_config_hash: Mapped[str] = mapped_column(String(64), index=True)
    payload_json: Mapped[dict] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    signature_timestamp: Mapped[str] = mapped_column(String(32))
    signature: Mapped[str] = mapped_column(String(64))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    delivery_history_json: Mapped[list] = mapped_column(JSON, default=list)
    receipt_json: Mapped[dict] = mapped_column(JSON, default=dict)
    manual_redelivery_count: Mapped[int] = mapped_column(Integer, default=0)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class CreditFacilityRecord(Base):
    __tablename__ = "credit_facilities"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "case_id"],
            ["approval_cases.tenant_id", "approval_cases.case_id"],
            name="fk_credit_facility_tenant_case",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "counterparty_id"],
            ["counterparties.tenant_id", "counterparties.counterparty_id"],
            name="fk_credit_facility_tenant_counterparty",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "supersedes_facility_id"],
            ["credit_facilities.tenant_id", "credit_facilities.id"],
            name="fk_credit_facility_tenant_supersedes",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_credit_facility_tenant_id"),
        Index("ix_credit_facilities_tenant_status_expiry", "tenant_id", "status", "expires_at"),
        Index("ix_credit_facilities_tenant_counterparty_created", "tenant_id", "counterparty_id", "created_at"),
        UniqueConstraint("case_id", name="uq_credit_facility_case"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("approval_cases.case_id"), index=True)
    counterparty_id: Mapped[str] = mapped_column(String(128), index=True)
    counterparty_name: Mapped[str] = mapped_column(String(255))
    approved_limit: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    used_limit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    supersedes_facility_id: Mapped[str | None] = mapped_column(ForeignKey("credit_facilities.id"), nullable=True, index=True)
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


class FacilityControlConditionRecord(Base):
    __tablename__ = "facility_control_conditions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "facility_id"],
            ["credit_facilities.tenant_id", "credit_facilities.id"],
            name="fk_facility_control_condition_tenant_facility",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "source_case_id"],
            ["approval_cases.tenant_id", "approval_cases.case_id"],
            name="fk_facility_control_condition_tenant_case",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "linked_alert_id"],
            ["facility_alerts.tenant_id", "facility_alerts.id"],
            name="fk_facility_control_condition_tenant_alert",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_facility_control_condition_tenant_id"),
        Index("ix_facility_control_conditions_tenant_facility_status_due", "tenant_id", "facility_id", "status", "due_at"),
        Index("ix_facility_control_conditions_tenant_status_due", "tenant_id", "status", "due_at"),
        UniqueConstraint("tenant_id", "source_case_id", "sequence", name="uq_facility_control_condition_source_sequence"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    facility_id: Mapped[str] = mapped_column(ForeignKey("credit_facilities.id"))
    source_case_id: Mapped[str] = mapped_column(ForeignKey("approval_cases.case_id"))
    source_review_hash: Mapped[str] = mapped_column(String(64))
    sequence: Mapped[int] = mapped_column(Integer)
    measure: Mapped[str] = mapped_column(Text)
    owner_role: Mapped[str] = mapped_column(String(64), default="risk_manager")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    escalation_level: Mapped[int] = mapped_column(Integer, default=0)
    escalation_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    linked_alert_id: Mapped[str | None] = mapped_column(
        ForeignKey("facility_alerts.id", name="fk_facility_control_conditions_linked_alert"),
        nullable=True,
    )
    completion_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class FacilityControlExtensionRecord(Base):
    __tablename__ = "facility_control_extensions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "condition_id"],
            ["facility_control_conditions.tenant_id", "facility_control_conditions.id"],
            name="fk_facility_control_extension_tenant_condition",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "facility_id"],
            ["credit_facilities.tenant_id", "credit_facilities.id"],
            name="fk_facility_control_extension_tenant_facility",
            ondelete="RESTRICT",
        ),
        Index("ix_facility_control_extensions_tenant_condition_requested", "tenant_id", "condition_id", "requested_at"),
        Index(
            "uq_facility_control_extensions_pending",
            "tenant_id",
            "condition_id",
            unique=True,
            sqlite_where=text("status = 'pending'"),
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    condition_id: Mapped[str] = mapped_column(ForeignKey("facility_control_conditions.id"))
    facility_id: Mapped[str] = mapped_column(ForeignKey("credit_facilities.id"))
    extension_days: Mapped[int] = mapped_column(Integer)
    previous_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    proposed_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    requested_by: Mapped[str] = mapped_column(String(128))
    requested_by_name: Mapped[str] = mapped_column(String(128))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class CreditUsageRecord(Base):
    __tablename__ = "credit_usage_transactions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "facility_id"],
            ["credit_facilities.tenant_id", "credit_facilities.id"],
            name="fk_credit_usage_tenant_facility",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "transaction_ref", name="uq_credit_usage_tenant_transaction_ref"),
        Index("ix_credit_usage_tenant_facility_occurred", "tenant_id", "facility_id", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    facility_id: Mapped[str] = mapped_column(ForeignKey("credit_facilities.id"), index=True)
    transaction_ref: Mapped[str] = mapped_column(String(128), index=True)
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
        ForeignKeyConstraint(
            ["tenant_id", "facility_id"],
            ["credit_facilities.tenant_id", "credit_facilities.id"],
            name="fk_facility_alert_tenant_facility",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_facility_alert_tenant_id"),
        Index("ix_facility_alerts_tenant_status_severity_created", "tenant_id", "status", "severity", "created_at"),
        UniqueConstraint("tenant_id", "dedup_key", name="uq_facility_alert_dedup"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    facility_id: Mapped[str] = mapped_column(ForeignKey("credit_facilities.id"), index=True)
    alert_type: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    dedup_key: Mapped[str] = mapped_column(String(512))
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
        ForeignKeyConstraint(
            ["tenant_id", "facility_id"],
            ["credit_facilities.tenant_id", "credit_facilities.id"],
            name="fk_risk_event_tenant_facility",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "linked_alert_id"],
            ["facility_alerts.tenant_id", "facility_alerts.id"],
            name="fk_risk_event_tenant_alert",
            ondelete="RESTRICT",
        ),
        Index("ix_risk_events_tenant_facility_occurred", "tenant_id", "facility_id", "occurred_at"),
        Index("uq_risk_events_source_external_id", "tenant_id", "source", "external_event_id", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
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


class IndicatorDefinition(Base):
    __tablename__ = "indicator_definitions"
    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_indicator_code_version"),
        Index(
            "uq_indicator_single_active",
            "code",
            "is_active",
            unique=True,
            sqlite_where=text("is_active = 1"),
            postgresql_where=text("is_active = true"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(256))
    category: Mapped[str] = mapped_column(String(64), index=True)
    layer: Mapped[str] = mapped_column(String(16))
    data_type: Mapped[str] = mapped_column(String(16))
    field_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    expression: Mapped[str | None] = mapped_column(Text, nullable=True)
    dependencies: Mapped[list | None] = mapped_column(JSON, nullable=True)
    scoring_json: Mapped[dict] = mapped_column(JSON)
    max_score: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=3)
    default_weight: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=1.0)
    source_references: Mapped[list | None] = mapped_column(JSON, nullable=True)
    seed_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __mapper_args__ = {"version_id_col": row_version}


class ScorecardDefinition(Base):
    __tablename__ = "scorecard_definitions"
    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_scorecard_code_version"),
        Index(
            "uq_scorecard_single_active",
            "code",
            "is_active",
            unique=True,
            sqlite_where=text("is_active = 1"),
            postgresql_where=text("is_active = true"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="published", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    config_json: Mapped[dict] = mapped_column(JSON)
    config_hash: Mapped[str] = mapped_column(String(64), index=True)
    change_id: Mapped[str] = mapped_column(ForeignKey("model_changes.id"), index=True)
    created_by: Mapped[str] = mapped_column(String(128))
    created_by_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CreditCalibrationPlan(Base):
    __tablename__ = "credit_calibration_plans"
    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_credit_calibration_plan_code_version"),
        Index("ix_credit_calibration_plan_template_status", "template_key", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(256))
    version: Mapped[int] = mapped_column(Integer)
    template_key: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    candidate_json: Mapped[dict] = mapped_column(JSON)
    sample_policy_json: Mapped[dict] = mapped_column(JSON)
    business_basis: Mapped[str] = mapped_column(Text)
    config_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_by: Mapped[str] = mapped_column(String(128), index=True)
    created_by_name: Mapped[str] = mapped_column(String(128))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    reviewed_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class CreditCalibrationRun(Base):
    __tablename__ = "credit_calibration_runs"
    __table_args__ = (
        Index("ix_credit_calibration_run_plan_created", "plan_id", "created_at"),
        Index("ix_credit_calibration_run_snapshot_created", "dataset_snapshot_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("credit_calibration_plans.id", ondelete="RESTRICT"), index=True)
    plan_config_hash: Mapped[str] = mapped_column(String(64), index=True)
    base_model_version: Mapped[str] = mapped_column(String(128))
    baseline_config_hash: Mapped[str] = mapped_column(String(64), index=True)
    dataset_snapshot_id: Mapped[str] = mapped_column(ForeignKey("rule_center_replay_dataset_snapshots.id", ondelete="RESTRICT"), index=True)
    dataset_snapshot_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    report_json: Mapped[dict] = mapped_column(JSON)
    evidence_hash: Mapped[str] = mapped_column(String(64), index=True)
    evidence_level: Mapped[str] = mapped_column(String(32), index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(128), index=True)
    created_by_name: Mapped[str] = mapped_column(String(128))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class ScorecardValidationPolicy(Base):
    __tablename__ = "scorecard_validation_policies"
    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_scorecard_validation_policy_code_version"),
        Index(
            "uq_scorecard_validation_policy_single_active",
            "code", "is_active", unique=True,
            sqlite_where=text("is_active = 1"),
            postgresql_where=text("is_active = true"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    applicable_scorecard_codes: Mapped[list] = mapped_column(JSON, default=list)
    thresholds_json: Mapped[dict] = mapped_column(JSON)
    config_hash: Mapped[str] = mapped_column(String(64), index=True)
    change_reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(128), index=True)
    created_by_name: Mapped[str] = mapped_column(String(128))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    reviewed_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    __mapper_args__ = {"version_id_col": row_version}


class ScorecardDevelopmentRun(Base):
    __tablename__ = "scorecard_development_runs"
    __table_args__ = (
        Index("ix_scorecard_development_asset_created", "scorecard_asset_id", "created_at"),
        Index("ix_scorecard_development_snapshot_created", "dataset_snapshot_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scorecard_asset_id: Mapped[str] = mapped_column(ForeignKey("scorecard_definitions.id", ondelete="RESTRICT"), index=True)
    scorecard_code: Mapped[str] = mapped_column(String(128), index=True)
    scorecard_version: Mapped[int] = mapped_column(Integer)
    scorecard_config_hash: Mapped[str] = mapped_column(String(64), index=True)
    validation_policy_id: Mapped[str | None] = mapped_column(ForeignKey("scorecard_validation_policies.id", ondelete="RESTRICT"), nullable=True, index=True)
    validation_policy_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    dataset_snapshot_id: Mapped[str] = mapped_column(ForeignKey("rule_center_replay_dataset_snapshots.id", ondelete="RESTRICT"), index=True)
    dataset_snapshot_hash: Mapped[str] = mapped_column(String(64), index=True)
    validation_snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("rule_center_replay_dataset_snapshots.id", ondelete="RESTRICT"), nullable=True, index=True)
    validation_snapshot_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    oot_snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("rule_center_replay_dataset_snapshots.id", ondelete="RESTRICT"), nullable=True, index=True)
    oot_snapshot_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    label_policy_json: Mapped[dict] = mapped_column(JSON)
    report_json: Mapped[dict] = mapped_column(JSON)
    evidence_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    evidence_level: Mapped[str] = mapped_column(String(32), index=True)
    review_status: Mapped[str] = mapped_column(String(32), default="pending_review", index=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    reviewed_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(128), index=True)
    created_by_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    __mapper_args__ = {"version_id_col": row_version}


class ScorecardValidationMonitoringPlan(Base):
    __tablename__ = "scorecard_validation_monitoring_plans"
    __table_args__ = (
        UniqueConstraint("code", name="uq_scorecard_validation_monitoring_plan_code"),
        Index("ix_scorecard_validation_monitoring_plan_due", "enabled", "next_run_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text)
    scorecard_asset_id: Mapped[str] = mapped_column(ForeignKey("scorecard_definitions.id", ondelete="RESTRICT"), index=True)
    validation_policy_id: Mapped[str] = mapped_column(ForeignKey("scorecard_validation_policies.id", ondelete="RESTRICT"), index=True)
    training_dataset_id: Mapped[str] = mapped_column(ForeignKey("rule_center_replay_datasets.id", ondelete="RESTRICT"), index=True)
    validation_dataset_id: Mapped[str | None] = mapped_column(ForeignKey("rule_center_replay_datasets.id", ondelete="RESTRICT"), nullable=True, index=True)
    oot_dataset_id: Mapped[str | None] = mapped_column(ForeignKey("rule_center_replay_datasets.id", ondelete="RESTRICT"), nullable=True, index=True)
    run_config_json: Mapped[dict] = mapped_column(JSON)
    cadence: Mapped[str] = mapped_column(String(16), index=True)
    timezone_name: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    owner: Mapped[str] = mapped_column(String(128), index=True)
    last_scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_id: Mapped[str | None] = mapped_column(ForeignKey("scorecard_development_runs.id"), nullable=True, index=True)
    last_run_key: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    last_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(128), index=True)
    updated_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class ScorecardMonitoringSlaPolicy(Base):
    __tablename__ = "scorecard_monitoring_sla_policies"
    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_scorecard_monitoring_sla_policy_code_version"),
        Index(
            "uq_scorecard_monitoring_sla_policy_single_active",
            "code", "is_active", unique=True,
            sqlite_where=text("is_active = 1"),
            postgresql_where=text("is_active = true"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    applicable_scorecard_codes: Mapped[list] = mapped_column(JSON, default=list)
    applicable_event_types: Mapped[list] = mapped_column(JSON, default=list)
    severity_rules_json: Mapped[dict] = mapped_column(JSON)
    config_hash: Mapped[str] = mapped_column(String(64), index=True)
    change_reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(128), index=True)
    created_by_name: Mapped[str] = mapped_column(String(128))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    reviewed_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    __mapper_args__ = {"version_id_col": row_version}


class ScorecardValidationMonitoringEvent(Base):
    __tablename__ = "scorecard_validation_monitoring_events"
    __table_args__ = (
        UniqueConstraint("dedup_key", name="uq_scorecard_validation_monitoring_event_dedup"),
        Index("ix_scorecard_validation_monitoring_event_queue", "status", "severity", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("scorecard_validation_monitoring_plans.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("scorecard_development_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    evidence_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    metric_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    metric_label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metric_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    threshold_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    threshold_operator: Mapped[str | None] = mapped_column(String(8), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    details_json: Mapped[dict] = mapped_column(JSON, default=dict)
    dedup_key: Mapped[str] = mapped_column(String(512), unique=True)
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    assignee: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    sla_policy_id: Mapped[str | None] = mapped_column(ForeignKey("scorecard_monitoring_sla_policies.id", ondelete="RESTRICT"), nullable=True, index=True)
    sla_policy_snapshot_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    sla_policy_snapshot_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    sla_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    sla_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    escalation_level: Mapped[int] = mapped_column(Integer, default=0)
    last_escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    remediation_plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    remediation_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    remediated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    remediated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revalidation_run_id: Mapped[str | None] = mapped_column(ForeignKey("scorecard_development_runs.id", ondelete="RESTRICT"), nullable=True, index=True)
    revalidation_evidence_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revalidation_conclusion: Mapped[str | None] = mapped_column(Text, nullable=True)
    revalidated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    revalidated_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    revalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class ScorecardMonitoringSavedView(Base):
    __tablename__ = "scorecard_monitoring_saved_views"
    __table_args__ = (
        UniqueConstraint("owner_subject", "name", name="uq_scorecard_monitoring_saved_view_owner_name"),
        Index(
            "uq_scorecard_monitoring_saved_view_owner_default",
            "owner_subject", unique=True,
            sqlite_where=text("is_default = 1"),
            postgresql_where=text("is_default = true"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_subject: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(128))
    filters_json: Mapped[dict] = mapped_column(JSON, default=dict)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __mapper_args__ = {"version_id_col": row_version}


class ScorecardMonitoringSchedulerLease(Base):
    __tablename__ = "scorecard_monitoring_scheduler_leases"

    lease_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    execution_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    run_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    actor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    trigger_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    acquired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ScorecardMonitoringSchedulerRun(Base):
    __tablename__ = "scorecard_monitoring_scheduler_runs"
    __table_args__ = (
        UniqueConstraint("run_key", name="uq_scorecard_monitoring_scheduler_run_key"),
        Index("ix_scorecard_monitoring_scheduler_run_status_started", "status", "started_at"),
        Index("ix_scorecard_monitoring_scheduler_run_trigger_started", "trigger_type", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    trigger_type: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actor: Mapped[str] = mapped_column(String(128), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    recovery_of_run_id: Mapped[str | None] = mapped_column(ForeignKey("scorecard_monitoring_scheduler_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    recovery_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    completed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    backlog_before: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    backlog_after: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    oldest_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    details_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class RuleDefinition(Base):
    __tablename__ = "rule_definitions"
    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_rule_code_version"),
        Index(
            "uq_rule_single_active",
            "code",
            "is_active",
            unique=True,
            sqlite_where=text("is_active = 1"),
            postgresql_where=text("is_active = true"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(256))
    rule_type: Mapped[str] = mapped_column(String(32), index=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    conditions_json: Mapped[dict] = mapped_column(JSON)
    condition_relation: Mapped[str] = mapped_column(String(8), default="all")
    actions_json: Mapped[dict] = mapped_column(JSON)
    priority: Mapped[int] = mapped_column(Integer, default=999)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __mapper_args__ = {"version_id_col": row_version}


class RuleSetDefinition(Base):
    __tablename__ = "rule_set_definitions"
    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_rule_set_code_version"),
        Index(
            "uq_rule_set_single_active",
            "code",
            "is_active",
            unique=True,
            sqlite_where=text("is_active = 1"),
            postgresql_where=text("is_active = true"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(256))
    rule_codes: Mapped[list] = mapped_column(JSON)
    evaluation_strategy: Mapped[str] = mapped_column(
        String(32), default="most_restrictive"
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __mapper_args__ = {"version_id_col": row_version}


class DecisionPipelineDefinition(Base):
    __tablename__ = "decision_pipeline_definitions"
    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_pipeline_code_version"),
        Index(
            "uq_pipeline_single_active",
            "code",
            "is_active",
            unique=True,
            sqlite_where=text("is_active = 1"),
            postgresql_where=text("is_active = true"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(256))
    stages_json: Mapped[list] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __mapper_args__ = {"version_id_col": row_version}
