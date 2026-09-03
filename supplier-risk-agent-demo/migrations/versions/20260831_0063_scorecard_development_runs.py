"""add scorecard development analysis runs

Revision ID: 20260831_0063
Revises: 20260831_0062
"""
from alembic import op
import sqlalchemy as sa

revision = "20260831_0063"
down_revision = "20260831_0062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scorecard_development_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scorecard_asset_id", sa.String(36), sa.ForeignKey("scorecard_definitions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("scorecard_code", sa.String(128), nullable=False),
        sa.Column("scorecard_version", sa.Integer(), nullable=False),
        sa.Column("scorecard_config_hash", sa.String(64), nullable=False),
        sa.Column("dataset_snapshot_id", sa.String(36), sa.ForeignKey("rule_center_replay_dataset_snapshots.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("dataset_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("label_policy_json", sa.JSON(), nullable=False),
        sa.Column("report_json", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("evidence_level", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_by_name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_scorecard_development_runs_scorecard_asset_id", "scorecard_development_runs", ["scorecard_asset_id"])
    op.create_index("ix_scorecard_development_runs_scorecard_code", "scorecard_development_runs", ["scorecard_code"])
    op.create_index("ix_scorecard_development_runs_scorecard_config_hash", "scorecard_development_runs", ["scorecard_config_hash"])
    op.create_index("ix_scorecard_development_runs_dataset_snapshot_id", "scorecard_development_runs", ["dataset_snapshot_id"])
    op.create_index("ix_scorecard_development_runs_dataset_snapshot_hash", "scorecard_development_runs", ["dataset_snapshot_hash"])
    op.create_index("ix_scorecard_development_runs_evidence_hash", "scorecard_development_runs", ["evidence_hash"], unique=True)
    op.create_index("ix_scorecard_development_runs_evidence_level", "scorecard_development_runs", ["evidence_level"])
    op.create_index("ix_scorecard_development_runs_created_by", "scorecard_development_runs", ["created_by"])
    op.create_index("ix_scorecard_development_runs_created_at", "scorecard_development_runs", ["created_at"])
    op.create_index("ix_scorecard_development_asset_created", "scorecard_development_runs", ["scorecard_asset_id", "created_at"])
    op.create_index("ix_scorecard_development_snapshot_created", "scorecard_development_runs", ["dataset_snapshot_id", "created_at"])


def downgrade() -> None:
    op.drop_table("scorecard_development_runs")
