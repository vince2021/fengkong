"""rule_center: add champion challenger replay comparisons

Revision ID: 20260826_0059
Revises: 20260826_0058
Create Date: 2026-08-26
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260826_0059"
down_revision = "20260826_0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rule_center_replay_comparison_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("dataset_snapshot_id", sa.String(length=36), sa.ForeignKey("rule_center_replay_dataset_snapshots.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("dataset_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("champion_model_key", sa.String(length=64), nullable=False),
        sa.Column("champion_model_version", sa.String(length=128), nullable=False),
        sa.Column("challenger_model_key", sa.String(length=64), nullable=False),
        sa.Column("challenger_model_version", sa.String(length=128), nullable=False),
        sa.Column("champion_pipeline_code", sa.String(length=128), nullable=False),
        sa.Column("champion_pipeline_version", sa.Integer(), nullable=True),
        sa.Column("challenger_pipeline_code", sa.String(length=128), nullable=False),
        sa.Column("challenger_pipeline_version", sa.Integer(), nullable=True),
        sa.Column("segment_field", sa.String(length=256), nullable=False),
        sa.Column("evidence_level", sa.String(length=32), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_by_name", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    for name in ("dataset_snapshot_id", "dataset_snapshot_hash", "champion_model_key", "challenger_model_key", "evidence_level", "evidence_hash", "created_by", "created_at"):
        op.create_index(f"ix_rule_center_replay_comparison_runs_{name}", "rule_center_replay_comparison_runs", [name])
    op.create_index("ix_rule_center_replay_comparison_snapshot_created", "rule_center_replay_comparison_runs", ["dataset_snapshot_id", "created_at"])


def downgrade() -> None:
    op.drop_table("rule_center_replay_comparison_runs")
