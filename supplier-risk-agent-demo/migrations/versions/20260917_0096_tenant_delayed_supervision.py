"""Add tenant outcome linkage and delayed supervised evaluation evidence.

Revision ID: 20260917_0096
Revises: 20260917_0095
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260917_0096"
down_revision = "20260917_0095"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_outcome_labels",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("policy_id", sa.String(36), nullable=False),
        sa.Column("routing_decision_id", sa.String(36), sa.ForeignKey("tenant_routing_decisions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("decision_execution_id", sa.String(36), sa.ForeignKey("decision_executions.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("source", sa.String(128), nullable=False),
        sa.Column("external_label_id", sa.String(128), nullable=False),
        sa.Column("counterparty_id", sa.String(128), nullable=False),
        sa.Column("label_definition", sa.String(128), nullable=False),
        sa.Column("observed_event", sa.Boolean(), nullable=False),
        sa.Column("observation_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("loss_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("exposure_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("evidence_reference", sa.Text(), nullable=False),
        sa.Column("link_status", sa.String(32), nullable=False),
        sa.Column("selected_arm", sa.String(16), nullable=False),
        sa.Column("model_key", sa.String(64), nullable=False),
        sa.Column("model_version", sa.String(128), nullable=False),
        sa.Column("predicted_score", sa.Numeric(12, 4), nullable=False),
        sa.Column("risk_score", sa.Numeric(8, 6), nullable=False),
        sa.Column("rating", sa.String(32), nullable=True),
        sa.Column("admission", sa.String(64), nullable=True),
        sa.Column("routing_evidence_hash", sa.String(64), nullable=False),
        sa.Column("execution_evidence_hash", sa.String(64), nullable=True),
        sa.Column("selected_assets_hash", sa.String(64), nullable=False),
        sa.Column("label_payload_hash", sa.String(64), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("verification_status", sa.String(32), nullable=False, server_default="pending_verification"),
        sa.Column("verified_by", sa.String(128), nullable=True),
        sa.Column("verified_by_name", sa.String(128), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verification_note", sa.Text(), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_by_name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("link_status IN ('route_only', 'decision_execution')", name="ck_tenant_outcome_label_link_status"),
        sa.CheckConstraint("verification_status IN ('pending_verification', 'verified', 'rejected')", name="ck_tenant_outcome_label_verification"),
        sa.CheckConstraint("predicted_score BETWEEN 0 AND 100", name="ck_tenant_outcome_label_score"),
        sa.CheckConstraint("risk_score BETWEEN 0 AND 1", name="ck_tenant_outcome_label_risk_score"),
        sa.ForeignKeyConstraint(["tenant_id", "policy_id"], ["tenant_rollout_policies.tenant_id", "tenant_rollout_policies.id"], name="fk_tenant_outcome_label_tenant_policy", ondelete="RESTRICT"),
        sa.UniqueConstraint("tenant_id", "source", "external_label_id", name="uq_tenant_outcome_label_external"),
        sa.UniqueConstraint("tenant_id", "routing_decision_id", "label_definition", name="uq_tenant_outcome_label_route_definition"),
    )
    for column in ("tenant_id", "policy_id", "routing_decision_id", "decision_execution_id", "source", "external_label_id", "counterparty_id", "observed_event", "observation_end", "link_status", "selected_arm", "model_key", "model_version", "evidence_hash", "verification_status", "created_at"):
        op.create_index(f"ix_tenant_outcome_labels_{column}", "tenant_outcome_labels", [column])
    op.create_index("ix_tenant_outcome_label_policy_status", "tenant_outcome_labels", ["tenant_id", "policy_id", "verification_status", "observation_end"])

    op.create_table(
        "tenant_supervised_evaluations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("policy_id", sa.String(36), nullable=False),
        sa.Column("evaluation_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("coverage_json", sa.JSON(), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("evidence_level", sa.String(32), nullable=False),
        sa.Column("label_watermark_json", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_by_name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("evidence_level IN ('supervised', 'insufficient_maturity', 'insufficient_labels')", name="ck_tenant_supervised_evaluation_level"),
        sa.ForeignKeyConstraint(["tenant_id", "policy_id"], ["tenant_rollout_policies.tenant_id", "tenant_rollout_policies.id"], name="fk_tenant_supervised_evaluation_tenant_policy", ondelete="RESTRICT"),
    )
    for column in ("tenant_id", "policy_id", "evaluation_as_of", "evidence_level", "evidence_hash", "created_at"):
        op.create_index(f"ix_tenant_supervised_evaluations_{column}", "tenant_supervised_evaluations", [column])
    op.create_index("ix_tenant_supervised_evaluation_policy_created", "tenant_supervised_evaluations", ["tenant_id", "policy_id", "created_at"])


def downgrade() -> None:
    op.drop_table("tenant_supervised_evaluations")
    op.drop_table("tenant_outcome_labels")
