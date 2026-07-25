"""Add outcome import reconciliation and monitoring schedules.

Revision ID: 20260716_0018
Revises: 20260716_0017
"""

from alembic import op
import sqlalchemy as sa


revision = "20260716_0018"
down_revision = "20260716_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_outcome_imports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("import_key", sa.String(length=256), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("template_key", sa.String(length=64), nullable=False),
        sa.Column("population_period", sa.String(length=6), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("expected_count", sa.Integer(), nullable=False),
        sa.Column("received_count", sa.Integer(), nullable=False),
        sa.Column("created_count", sa.Integer(), nullable=False),
        sa.Column("idempotent_count", sa.Integer(), nullable=False),
        sa.Column("rejected_count", sa.Integer(), nullable=False),
        sa.Column("results_json", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("import_key", name="uq_model_outcome_import_key"),
    )
    op.create_index("ix_model_outcome_imports_import_key", "model_outcome_imports", ["import_key"], unique=True)
    op.create_index("ix_model_outcome_imports_source", "model_outcome_imports", ["source"], unique=False)
    op.create_index("ix_model_outcome_imports_template_key", "model_outcome_imports", ["template_key"], unique=False)
    op.create_index("ix_model_outcome_imports_population_period", "model_outcome_imports", ["population_period"], unique=False)
    op.create_index("ix_model_outcome_imports_status", "model_outcome_imports", ["status"], unique=False)
    op.create_index("ix_model_outcome_imports_created_at", "model_outcome_imports", ["created_at"], unique=False)
    op.create_index("ix_model_outcome_imports_template_period", "model_outcome_imports", ["template_key", "population_period", "created_at"], unique=False)

    op.create_table(
        "model_monitoring_schedules",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("template_key", sa.String(length=64), nullable=False),
        sa.Column("cadence", sa.String(length=16), nullable=False),
        sa.Column("timezone_name", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_id", sa.String(length=36), nullable=True),
        sa.Column("last_status", sa.String(length=32), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("updated_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["last_run_id"], ["model_monitoring_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_key", name="uq_model_monitoring_schedule_template"),
    )
    op.create_index("ix_model_monitoring_schedules_template_key", "model_monitoring_schedules", ["template_key"], unique=True)
    op.create_index("ix_model_monitoring_schedules_cadence", "model_monitoring_schedules", ["cadence"], unique=False)
    op.create_index("ix_model_monitoring_schedules_enabled", "model_monitoring_schedules", ["enabled"], unique=False)
    op.create_index("ix_model_monitoring_schedules_next_run_at", "model_monitoring_schedules", ["next_run_at"], unique=False)
    op.create_index("ix_model_monitoring_schedules_last_run_id", "model_monitoring_schedules", ["last_run_id"], unique=False)
    op.create_index("ix_model_monitoring_schedules_created_at", "model_monitoring_schedules", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_table("model_monitoring_schedules")
    op.drop_table("model_outcome_imports")
