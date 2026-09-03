"""add scorecard continuous validation monitoring

Revision ID: 20260901_0068
Revises: 20260901_0067
"""
from alembic import op
import sqlalchemy as sa


revision = "20260901_0068"
down_revision = "20260901_0067"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scorecard_validation_monitoring_plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("scorecard_asset_id", sa.String(36), sa.ForeignKey("scorecard_definitions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("validation_policy_id", sa.String(36), sa.ForeignKey("scorecard_validation_policies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("training_dataset_id", sa.String(36), sa.ForeignKey("rule_center_replay_datasets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("validation_dataset_id", sa.String(36), sa.ForeignKey("rule_center_replay_datasets.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("oot_dataset_id", sa.String(36), sa.ForeignKey("rule_center_replay_datasets.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("run_config_json", sa.JSON(), nullable=False),
        sa.Column("cadence", sa.String(16), nullable=False),
        sa.Column("timezone_name", sa.String(64), nullable=False, server_default="Asia/Shanghai"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("owner", sa.String(128), nullable=False),
        sa.Column("last_scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_id", sa.String(36), sa.ForeignKey("scorecard_development_runs.id"), nullable=True),
        sa.Column("last_run_key", sa.String(256), nullable=True),
        sa.Column("last_status", sa.String(32), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("updated_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("code", name="uq_scorecard_validation_monitoring_plan_code"),
    )
    for name, columns in (
        ("ix_scorecard_validation_monitoring_plans_code", ["code"]),
        ("ix_scorecard_validation_monitoring_plans_scorecard_asset_id", ["scorecard_asset_id"]),
        ("ix_scorecard_validation_monitoring_plans_validation_policy_id", ["validation_policy_id"]),
        ("ix_scorecard_validation_monitoring_plans_training_dataset_id", ["training_dataset_id"]),
        ("ix_scorecard_validation_monitoring_plans_validation_dataset_id", ["validation_dataset_id"]),
        ("ix_scorecard_validation_monitoring_plans_oot_dataset_id", ["oot_dataset_id"]),
        ("ix_scorecard_validation_monitoring_plans_cadence", ["cadence"]),
        ("ix_scorecard_validation_monitoring_plans_enabled", ["enabled"]),
        ("ix_scorecard_validation_monitoring_plans_next_run_at", ["next_run_at"]),
        ("ix_scorecard_validation_monitoring_plans_owner", ["owner"]),
        ("ix_scorecard_validation_monitoring_plans_last_run_id", ["last_run_id"]),
        ("ix_scorecard_validation_monitoring_plans_last_run_key", ["last_run_key"]),
        ("ix_scorecard_validation_monitoring_plans_created_by", ["created_by"]),
        ("ix_scorecard_validation_monitoring_plans_created_at", ["created_at"]),
    ):
        op.create_index(name, "scorecard_validation_monitoring_plans", columns)
    op.create_index("ix_scorecard_validation_monitoring_plan_due", "scorecard_validation_monitoring_plans", ["enabled", "next_run_at"])

    op.create_table(
        "scorecard_validation_monitoring_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("plan_id", sa.String(36), sa.ForeignKey("scorecard_validation_monitoring_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("scorecard_development_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("evidence_hash", sa.String(64), nullable=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("metric_key", sa.String(64), nullable=True),
        sa.Column("metric_label", sa.String(128), nullable=True),
        sa.Column("metric_value", sa.Numeric(12, 6), nullable=True),
        sa.Column("threshold_value", sa.Numeric(12, 6), nullable=True),
        sa.Column("threshold_operator", sa.String(8), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("dedup_key", sa.String(512), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("assignee", sa.String(128), nullable=True),
        sa.Column("acknowledged_by", sa.String(128), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("remediation_plan", sa.Text(), nullable=True),
        sa.Column("remediation_result", sa.Text(), nullable=True),
        sa.Column("closed_by", sa.String(128), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("dedup_key", name="uq_scorecard_validation_monitoring_event_dedup"),
    )
    for name, columns in (
        ("ix_scorecard_validation_monitoring_events_plan_id", ["plan_id"]),
        ("ix_scorecard_validation_monitoring_events_run_id", ["run_id"]),
        ("ix_scorecard_validation_monitoring_events_evidence_hash", ["evidence_hash"]),
        ("ix_scorecard_validation_monitoring_events_event_type", ["event_type"]),
        ("ix_scorecard_validation_monitoring_events_severity", ["severity"]),
        ("ix_scorecard_validation_monitoring_events_metric_key", ["metric_key"]),
        ("ix_scorecard_validation_monitoring_events_status", ["status"]),
        ("ix_scorecard_validation_monitoring_events_assignee", ["assignee"]),
        ("ix_scorecard_validation_monitoring_events_created_at", ["created_at"]),
    ):
        op.create_index(name, "scorecard_validation_monitoring_events", columns)
    op.create_index("ix_scorecard_validation_monitoring_event_queue", "scorecard_validation_monitoring_events", ["status", "severity", "created_at"])


def downgrade() -> None:
    op.drop_table("scorecard_validation_monitoring_events")
    op.drop_table("scorecard_validation_monitoring_plans")
