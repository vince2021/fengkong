"""model governance: bind comparison evidence to candidate changes

Revision ID: 20260828_0061
Revises: 20260828_0060
Create Date: 2026-08-28
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260828_0061"
down_revision = "20260828_0060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("model_changes") as batch:
        batch.add_column(sa.Column("comparison_evidence_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
    with op.batch_alter_table("rule_center_replay_comparison_runs") as batch:
        batch.add_column(sa.Column("challenger_change_id", sa.String(length=36), sa.ForeignKey("model_changes.id", name="fk_replay_comparison_challenger_change", ondelete="RESTRICT"), nullable=True))
        batch.add_column(sa.Column("challenger_config_hash", sa.String(length=64), nullable=True))
        batch.create_index("ix_rule_center_replay_comparison_runs_challenger_change_id", ["challenger_change_id"])
        batch.create_index("ix_rule_center_replay_comparison_runs_challenger_config_hash", ["challenger_config_hash"])


def downgrade() -> None:
    with op.batch_alter_table("rule_center_replay_comparison_runs") as batch:
        batch.drop_index("ix_rule_center_replay_comparison_runs_challenger_config_hash")
        batch.drop_index("ix_rule_center_replay_comparison_runs_challenger_change_id")
        batch.drop_column("challenger_config_hash")
        batch.drop_column("challenger_change_id")
    with op.batch_alter_table("model_changes") as batch:
        batch.drop_column("comparison_evidence_json")
