"""Add governed tenant monitoring difference cases.

Revision ID: 20260924_0111
Revises: 20260924_0110
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260924_0111"
down_revision = "20260924_0110"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_monitoring_diff_cases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("policy_id", sa.String(36), nullable=False),
        sa.Column("base_run_id", sa.String(36), sa.ForeignKey("tenant_monitoring_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("against_run_id", sa.String(36), sa.ForeignKey("tenant_monitoring_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("base_evidence_hash", sa.String(64), nullable=False),
        sa.Column("against_evidence_hash", sa.String(64), nullable=False),
        sa.Column("diff_hash", sa.String(64), nullable=False),
        sa.Column("comparison_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("severity", sa.String(32), nullable=False, server_default="warning"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("assigned_role", sa.String(64), nullable=False, server_default="risk_manager"),
        sa.Column("assigned_to", sa.String(128), nullable=True),
        sa.Column("assigned_to_name", sa.String(128), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recompute_status", sa.String(32), nullable=False, server_default="not_started"),
        sa.Column("recomputed_run_id", sa.String(36), sa.ForeignKey("tenant_monitoring_runs.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("recomputed_diff_hash", sa.String(64), nullable=True),
        sa.Column("recomputed_by", sa.String(128), nullable=True),
        sa.Column("recomputed_by_name", sa.String(128), nullable=True),
        sa.Column("recomputed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recompute_error", sa.Text(), nullable=True),
        sa.Column("disposition", sa.String(64), nullable=True),
        sa.Column("conclusion", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.String(128), nullable=True),
        sa.Column("resolved_by_name", sa.String(128), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_by_name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["tenant_id", "policy_id"], ["tenant_rollout_policies.tenant_id", "tenant_rollout_policies.id"],
            ondelete="RESTRICT", name="fk_tenant_monitoring_diff_case_policy",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'assigned', 'recomputing', 'pending_disposition', 'resolved', 'rejected')",
            name="ck_tenant_monitoring_diff_case_status",
        ),
        sa.CheckConstraint("severity IN ('info', 'warning', 'critical')", name="ck_tenant_monitoring_diff_case_severity"),
        sa.CheckConstraint(
            "recompute_status IN ('not_started', 'running', 'completed', 'failed')",
            name="ck_tenant_monitoring_diff_case_recompute_status",
        ),
        sa.CheckConstraint(
            "disposition IS NULL OR disposition IN ('accepted_change', 'data_issue', 'calculation_issue', "
            "'model_drift', 'policy_threshold_change_required', 'superseded')",
            name="ck_tenant_monitoring_diff_case_disposition",
        ),
        sa.UniqueConstraint("tenant_id", "diff_hash", name="uq_tenant_monitoring_diff_case_hash"),
    )
    op.create_index("ix_tenant_monitoring_diff_cases_tenant_id", "tenant_monitoring_diff_cases", ["tenant_id"])
    op.create_index("ix_tenant_monitoring_diff_cases_policy_id", "tenant_monitoring_diff_cases", ["policy_id"])
    op.create_index("ix_tenant_monitoring_diff_cases_base_run_id", "tenant_monitoring_diff_cases", ["base_run_id"])
    op.create_index("ix_tenant_monitoring_diff_cases_against_run_id", "tenant_monitoring_diff_cases", ["against_run_id"])
    op.create_index("ix_tenant_monitoring_diff_cases_diff_hash", "tenant_monitoring_diff_cases", ["diff_hash"])
    op.create_index("ix_tenant_monitoring_diff_cases_status", "tenant_monitoring_diff_cases", ["status"])
    op.create_index("ix_tenant_monitoring_diff_cases_severity", "tenant_monitoring_diff_cases", ["severity"])
    op.create_index("ix_tenant_monitoring_diff_cases_assigned_to", "tenant_monitoring_diff_cases", ["assigned_to"])
    op.create_index("ix_tenant_monitoring_diff_cases_due_at", "tenant_monitoring_diff_cases", ["due_at"])
    op.create_index("ix_tenant_monitoring_diff_cases_recompute_status", "tenant_monitoring_diff_cases", ["recompute_status"])
    op.create_index("ix_tenant_monitoring_diff_cases_recomputed_run_id", "tenant_monitoring_diff_cases", ["recomputed_run_id"])
    op.create_index("ix_tenant_monitoring_diff_cases_disposition", "tenant_monitoring_diff_cases", ["disposition"])
    op.create_index("ix_tenant_monitoring_diff_cases_created_at", "tenant_monitoring_diff_cases", ["created_at"])
    op.create_index(
        "ix_tenant_monitoring_diff_case_queue", "tenant_monitoring_diff_cases",
        ["tenant_id", "policy_id", "status", "due_at"],
    )


def downgrade() -> None:
    op.drop_table("tenant_monitoring_diff_cases")
