"""Initial approval, audit, model snapshot, and rating run schema."""

from alembic import op
import sqlalchemy as sa


revision = "20260714_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "approval_cases",
        sa.Column("case_id", sa.String(length=128), primary_key=True),
        sa.Column("counterparty_id", sa.String(length=128), nullable=False),
        sa.Column("counterparty_name", sa.String(length=255), nullable=False),
        sa.Column("current_stage", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("completed_stages", sa.JSON(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("timeline", sa.JSON(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_approval_cases_counterparty_id", "approval_cases", ["counterparty_id"])
    op.create_index("ix_approval_cases_status", "approval_cases", ["status"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("aggregate_type", sa.String(length=64), nullable=False),
        sa.Column("aggregate_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("previous_hash", sa.String(length=64), nullable=False),
        sa.Column("event_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audit_aggregate", "audit_events", ["aggregate_type", "aggregate_id", "created_at"])
    op.create_index("ix_audit_events_aggregate_id", "audit_events", ["aggregate_id"])
    op.create_index("ix_audit_events_aggregate_type", "audit_events", ["aggregate_type"])
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"])

    op.create_table(
        "model_snapshots",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("template_key", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("model_version", sa.String(length=128), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("template_key", "model_version", "config_hash", name="uq_model_snapshot"),
    )
    op.create_index("ix_model_snapshots_config_hash", "model_snapshots", ["config_hash"])
    op.create_index("ix_model_snapshots_model_version", "model_snapshots", ["model_version"])
    op.create_index("ix_model_snapshots_template_key", "model_snapshots", ["template_key"])

    op.create_table(
        "rating_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("counterparty_id", sa.String(length=128), nullable=False),
        sa.Column("template_key", sa.String(length=64), nullable=False),
        sa.Column("model_snapshot_id", sa.String(length=36), sa.ForeignKey("model_snapshots.id"), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("result_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_rating_runs_counterparty_id", "rating_runs", ["counterparty_id"])
    op.create_index("ix_rating_runs_created_at", "rating_runs", ["created_at"])
    op.create_index("ix_rating_runs_model_snapshot_id", "rating_runs", ["model_snapshot_id"])
    op.create_index("ix_rating_runs_result_hash", "rating_runs", ["result_hash"])
    op.create_index("ix_rating_runs_template_key", "rating_runs", ["template_key"])


def downgrade() -> None:
    op.drop_table("rating_runs")
    op.drop_table("model_snapshots")
    op.drop_table("audit_events")
    op.drop_table("approval_cases")
