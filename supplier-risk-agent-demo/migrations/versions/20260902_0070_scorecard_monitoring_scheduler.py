"""add scorecard monitoring scheduler governance

Revision ID: 20260902_0070
Revises: 20260901_0069
Create Date: 2026-09-02
"""

from alembic import op
import sqlalchemy as sa


revision = "20260902_0070"
down_revision = "20260901_0069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scorecard_monitoring_scheduler_leases",
        sa.Column("lease_key", sa.String(length=64), nullable=False),
        sa.Column("execution_id", sa.String(length=36), nullable=True),
        sa.Column("run_key", sa.String(length=128), nullable=True),
        sa.Column("actor", sa.String(length=128), nullable=True),
        sa.Column("trigger_type", sa.String(length=32), nullable=True),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("lease_key"),
    )
    op.create_table(
        "scorecard_monitoring_scheduler_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_key", sa.String(length=128), nullable=False),
        sa.Column("trigger_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("attempt_number", sa.Integer(), server_default="1", nullable=False),
        sa.Column("recovery_of_run_id", sa.String(length=36), nullable=True),
        sa.Column("recovery_reason", sa.Text(), nullable=True),
        sa.Column("due_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("backlog_before", sa.Integer(), server_default="0", nullable=False),
        sa.Column("backlog_after", sa.Integer(), server_default="0", nullable=False),
        sa.Column("oldest_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_type", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["recovery_of_run_id"], ["scorecard_monitoring_scheduler_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_key", name="uq_scorecard_monitoring_scheduler_run_key"),
    )
    op.create_index("ix_scorecard_monitoring_scheduler_run_run_key", "scorecard_monitoring_scheduler_runs", ["run_key"], unique=True)
    op.create_index("ix_scorecard_monitoring_scheduler_run_trigger_type", "scorecard_monitoring_scheduler_runs", ["trigger_type"], unique=False)
    op.create_index("ix_scorecard_monitoring_scheduler_run_status", "scorecard_monitoring_scheduler_runs", ["status"], unique=False)
    op.create_index("ix_scorecard_monitoring_scheduler_run_as_of", "scorecard_monitoring_scheduler_runs", ["as_of"], unique=False)
    op.create_index("ix_scorecard_monitoring_scheduler_run_started_at", "scorecard_monitoring_scheduler_runs", ["started_at"], unique=False)
    op.create_index("ix_scorecard_monitoring_scheduler_run_actor", "scorecard_monitoring_scheduler_runs", ["actor"], unique=False)
    op.create_index("ix_scorecard_monitoring_scheduler_run_recovery_of_run_id", "scorecard_monitoring_scheduler_runs", ["recovery_of_run_id"], unique=False)
    op.create_index("ix_scorecard_monitoring_scheduler_run_created_at", "scorecard_monitoring_scheduler_runs", ["created_at"], unique=False)
    op.create_index("ix_scorecard_monitoring_scheduler_run_status_started", "scorecard_monitoring_scheduler_runs", ["status", "started_at"], unique=False)
    op.create_index("ix_scorecard_monitoring_scheduler_run_trigger_started", "scorecard_monitoring_scheduler_runs", ["trigger_type", "started_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_scorecard_monitoring_scheduler_run_trigger_started", table_name="scorecard_monitoring_scheduler_runs")
    op.drop_index("ix_scorecard_monitoring_scheduler_run_status_started", table_name="scorecard_monitoring_scheduler_runs")
    op.drop_index("ix_scorecard_monitoring_scheduler_run_created_at", table_name="scorecard_monitoring_scheduler_runs")
    op.drop_index("ix_scorecard_monitoring_scheduler_run_recovery_of_run_id", table_name="scorecard_monitoring_scheduler_runs")
    op.drop_index("ix_scorecard_monitoring_scheduler_run_actor", table_name="scorecard_monitoring_scheduler_runs")
    op.drop_index("ix_scorecard_monitoring_scheduler_run_started_at", table_name="scorecard_monitoring_scheduler_runs")
    op.drop_index("ix_scorecard_monitoring_scheduler_run_as_of", table_name="scorecard_monitoring_scheduler_runs")
    op.drop_index("ix_scorecard_monitoring_scheduler_run_status", table_name="scorecard_monitoring_scheduler_runs")
    op.drop_index("ix_scorecard_monitoring_scheduler_run_trigger_type", table_name="scorecard_monitoring_scheduler_runs")
    op.drop_index("ix_scorecard_monitoring_scheduler_run_run_key", table_name="scorecard_monitoring_scheduler_runs")
    op.drop_table("scorecard_monitoring_scheduler_runs")
    op.drop_table("scorecard_monitoring_scheduler_leases")
