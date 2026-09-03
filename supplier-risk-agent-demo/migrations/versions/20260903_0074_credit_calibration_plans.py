"""add governed credit calibration plans and runs

Revision ID: 20260903_0074
Revises: 20260903_0073
"""
from alembic import op
import sqlalchemy as sa


revision = "20260903_0074"
down_revision = "20260903_0073"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credit_calibration_plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("template_key", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("candidate_json", sa.JSON(), nullable=False),
        sa.Column("sample_policy_json", sa.JSON(), nullable=False),
        sa.Column("business_basis", sa.Text(), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_by_name", sa.String(128), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(128), nullable=True),
        sa.Column("reviewed_by_name", sa.String(128), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("code", "version", name="uq_credit_calibration_plan_code_version"),
    )
    for column in ("code", "template_key", "status", "config_hash", "created_by", "reviewed_by", "created_at"):
        op.create_index(f"ix_credit_calibration_plans_{column}", "credit_calibration_plans", [column])
    op.create_index("ix_credit_calibration_plan_template_status", "credit_calibration_plans", ["template_key", "status", "created_at"])

    op.create_table(
        "credit_calibration_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("plan_id", sa.String(36), sa.ForeignKey("credit_calibration_plans.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("plan_config_hash", sa.String(64), nullable=False),
        sa.Column("base_model_version", sa.String(128), nullable=False),
        sa.Column("baseline_config_hash", sa.String(64), nullable=False),
        sa.Column("dataset_snapshot_id", sa.String(36), sa.ForeignKey("rule_center_replay_dataset_snapshots.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("dataset_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="completed"),
        sa.Column("report_json", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("evidence_level", sa.String(32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_by_name", sa.String(128), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    for column in ("plan_id", "plan_config_hash", "baseline_config_hash", "dataset_snapshot_id", "dataset_snapshot_hash", "status", "evidence_hash", "evidence_level", "created_by", "created_at"):
        op.create_index(f"ix_credit_calibration_runs_{column}", "credit_calibration_runs", [column])
    op.create_index("ix_credit_calibration_run_plan_created", "credit_calibration_runs", ["plan_id", "created_at"])
    op.create_index("ix_credit_calibration_run_snapshot_created", "credit_calibration_runs", ["dataset_snapshot_id", "created_at"])


def downgrade() -> None:
    op.drop_table("credit_calibration_runs")
    op.drop_table("credit_calibration_plans")
