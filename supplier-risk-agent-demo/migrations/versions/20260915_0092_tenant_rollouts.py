"""add tenant Champion/Challenger rollout governance

Revision ID: 20260915_0092
Revises: 20260915_0091
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260915_0092"
down_revision = "20260915_0091"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_rollout_policies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("comparison_run_id", sa.String(length=36), nullable=False),
        sa.Column("comparison_evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("comparison_assets_hash", sa.String(length=64), nullable=False),
        sa.Column("champion_model_key", sa.String(length=64), nullable=False),
        sa.Column("champion_model_version", sa.String(length=128), nullable=False),
        sa.Column("champion_pipeline_code", sa.String(length=128), nullable=False),
        sa.Column("champion_pipeline_version", sa.String(length=128), nullable=True),
        sa.Column("challenger_model_key", sa.String(length=64), nullable=False),
        sa.Column("challenger_model_version", sa.String(length=128), nullable=False),
        sa.Column("challenger_pipeline_code", sa.String(length=128), nullable=False),
        sa.Column("challenger_pipeline_version", sa.String(length=128), nullable=True),
        sa.Column("routing_key_field", sa.String(length=128), nullable=False),
        sa.Column("traffic_basis_points", sa.Integer(), nullable=False),
        sa.Column("observation_window_minutes", sa.Integer(), nullable=False),
        sa.Column("min_sample_size", sa.Integer(), nullable=False),
        sa.Column("thresholds_json", sa.JSON(), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("arm_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("assets_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_by_name", sa.String(length=128), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(length=128), nullable=True),
        sa.Column("reviewed_by_name", sa.String(length=128), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_reason", sa.Text(), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("status IN ('draft', 'pending_review', 'scheduled', 'active', 'paused', 'rolled_back', 'completed', 'rejected')", name="ck_tenant_rollout_policy_status"),
        sa.CheckConstraint("traffic_basis_points BETWEEN 1 AND 9999", name="ck_tenant_rollout_policy_traffic"),
        sa.CheckConstraint("ends_at > starts_at", name="ck_tenant_rollout_policy_window"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "comparison_run_id"],
            ["rule_center_replay_comparison_runs.tenant_id", "rule_center_replay_comparison_runs.id"],
            name="fk_tenant_rollout_policy_tenant_comparison", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_tenant_rollout_policy_tenant_id"),
    )
    for column in ("tenant_id", "comparison_run_id", "comparison_evidence_hash", "comparison_assets_hash", "champion_model_key", "challenger_model_key", "config_hash", "assets_hash", "status", "starts_at", "ends_at"):
        op.create_index(f"ix_tenant_rollout_policies_{column}", "tenant_rollout_policies", [column])
    op.create_index("ix_tenant_rollout_policy_tenant_status", "tenant_rollout_policies", ["tenant_id", "status", "starts_at", "ends_at"])
    op.create_index(
        "uq_tenant_rollout_one_active_model", "tenant_rollout_policies", ["tenant_id", "champion_model_key"], unique=True,
        sqlite_where=sa.text("status = 'active'"), postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "tenant_routing_decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("policy_id", sa.String(length=36), nullable=False),
        sa.Column("policy_config_hash", sa.String(length=64), nullable=False),
        sa.Column("policy_assets_hash", sa.String(length=64), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("request_ref", sa.String(length=256), nullable=False),
        sa.Column("routing_key_hash", sa.String(length=64), nullable=False),
        sa.Column("bucket", sa.Integer(), nullable=False),
        sa.Column("selected_arm", sa.String(length=16), nullable=False),
        sa.Column("selected_assets_json", sa.JSON(), nullable=False),
        sa.Column("selected_assets_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("elapsed_ms", sa.Integer(), nullable=True),
        sa.Column("score", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("rating", sa.String(length=32), nullable=True),
        sa.Column("admission", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("result_hash", sa.String(length=64), nullable=True),
        sa.Column("evidence_hash", sa.String(length=64), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("selected_arm IN ('champion', 'challenger')", name="ck_tenant_routing_decision_arm"),
        sa.CheckConstraint("status IN ('selected', 'completed', 'failed')", name="ck_tenant_routing_decision_status"),
        sa.CheckConstraint("bucket BETWEEN 0 AND 9999", name="ck_tenant_routing_decision_bucket"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "policy_id"], ["tenant_rollout_policies.tenant_id", "tenant_rollout_policies.id"], name="fk_tenant_routing_decision_tenant_policy", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "channel", "request_ref", name="uq_tenant_routing_decision_request"),
    )
    for column in ("tenant_id", "policy_id", "policy_config_hash", "channel", "request_ref", "routing_key_hash", "selected_arm", "selected_assets_hash", "status", "evidence_hash", "created_at"):
        op.create_index(f"ix_tenant_routing_decisions_{column}", "tenant_routing_decisions", [column])
    op.create_index("ix_tenant_routing_policy_arm_created", "tenant_routing_decisions", ["tenant_id", "policy_id", "selected_arm", "created_at"])

    op.create_table(
        "tenant_rollout_evaluations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("policy_id", sa.String(length=36), nullable=False),
        sa.Column("trigger_type", sa.String(length=32), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("evidence_level", sa.String(length=32), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("gate_json", sa.JSON(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_by_name", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "policy_id"], ["tenant_rollout_policies.tenant_id", "tenant_rollout_policies.id"], name="fk_tenant_rollout_evaluation_tenant_policy", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("tenant_id", "policy_id", "evidence_hash", "created_at"):
        op.create_index(f"ix_tenant_rollout_evaluations_{column}", "tenant_rollout_evaluations", [column])
    op.create_index("ix_tenant_rollout_evaluation_policy_created", "tenant_rollout_evaluations", ["tenant_id", "policy_id", "created_at"])


def downgrade() -> None:
    op.drop_table("tenant_rollout_evaluations")
    op.drop_table("tenant_routing_decisions")
    op.drop_table("tenant_rollout_policies")
