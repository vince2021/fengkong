"""rule_center: add pre-release replay evidence

Revision ID: 20260826_0057
Revises: 20260826_0056
Create Date: 2026-08-26
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260826_0057"
down_revision = "20260826_0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rule_center_replay_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("package_id", sa.String(length=36), sa.ForeignKey("rule_center_release_packages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("package_config_hash", sa.String(length=64), nullable=False),
        sa.Column("model_key", sa.String(length=64), nullable=False),
        sa.Column("model_version", sa.String(length=128), nullable=False),
        sa.Column("pipeline_code", sa.String(length=128), nullable=False),
        sa.Column("sample_source", sa.String(length=64), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("thresholds_json", sa.JSON(), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("gate_json", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_by_name", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_rule_center_replay_runs_package_id", "rule_center_replay_runs", ["package_id"])
    op.create_index("ix_rule_center_replay_runs_package_config_hash", "rule_center_replay_runs", ["package_config_hash"])
    op.create_index("ix_rule_center_replay_runs_model_key", "rule_center_replay_runs", ["model_key"])
    op.create_index("ix_rule_center_replay_runs_pipeline_code", "rule_center_replay_runs", ["pipeline_code"])
    op.create_index("ix_rule_center_replay_runs_status", "rule_center_replay_runs", ["status"])
    op.create_index("ix_rule_center_replay_runs_evidence_hash", "rule_center_replay_runs", ["evidence_hash"])
    op.create_index("ix_rule_center_replay_runs_created_by", "rule_center_replay_runs", ["created_by"])
    op.create_index("ix_rule_center_replay_runs_created_at", "rule_center_replay_runs", ["created_at"])
    op.create_index("ix_rule_center_replay_package_created", "rule_center_replay_runs", ["package_id", "created_at"])


def downgrade() -> None:
    op.drop_table("rule_center_replay_runs")
