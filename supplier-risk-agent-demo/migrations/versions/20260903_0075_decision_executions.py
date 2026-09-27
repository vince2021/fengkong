"""add immutable synchronous decision executions

Revision ID: 20260903_0075
Revises: 20260903_0074
"""
from alembic import op
import sqlalchemy as sa


revision = "20260903_0075"
down_revision = "20260903_0074"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "decision_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("trace_id", sa.String(36), nullable=False),
        sa.Column("counterparty_id", sa.String(128), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("normalized_input_json", sa.JSON(), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("model_key", sa.String(64), nullable=False),
        sa.Column("model_version", sa.String(128), nullable=False),
        sa.Column("model_config_hash", sa.String(64), nullable=False),
        sa.Column("pipeline_code", sa.String(128), nullable=False),
        sa.Column("pipeline_version", sa.Integer(), nullable=False),
        sa.Column("pipeline_hash", sa.String(64), nullable=False),
        sa.Column("asset_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("assets_hash", sa.String(64), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("result_hash", sa.String(64), nullable=False),
        sa.Column("trace_json", sa.JSON(), nullable=False),
        sa.Column("trace_hash", sa.String(64), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("elapsed_ms", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_by_name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("request_id", name="uq_decision_execution_request_id"),
        sa.UniqueConstraint("trace_id", name="uq_decision_execution_trace_id"),
        sa.UniqueConstraint("evidence_hash", name="uq_decision_execution_evidence_hash"),
    )
    for column in (
        "request_id", "request_hash", "trace_id", "counterparty_id", "input_hash",
        "model_key", "model_version", "model_config_hash", "pipeline_code", "pipeline_version",
        "pipeline_hash", "assets_hash", "result_hash", "trace_hash", "evidence_hash", "created_by", "created_at",
    ):
        op.create_index(f"ix_decision_executions_{column}", "decision_executions", [column])
    op.create_index("ix_decision_execution_model_created", "decision_executions", ["model_key", "model_version", "created_at"])
    op.create_index("ix_decision_execution_pipeline_created", "decision_executions", ["pipeline_code", "pipeline_version", "created_at"])


def downgrade() -> None:
    op.drop_table("decision_executions")
