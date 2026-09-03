"""add scorecard validation and out-of-time snapshots

Revision ID: 20260901_0064
Revises: 20260831_0063
"""
from alembic import op
import sqlalchemy as sa

revision = "20260901_0064"
down_revision = "20260831_0063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("scorecard_development_runs") as batch:
        batch.add_column(sa.Column("validation_snapshot_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("validation_snapshot_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("oot_snapshot_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("oot_snapshot_hash", sa.String(64), nullable=True))
        batch.create_foreign_key("fk_scorecard_development_validation_snapshot", "rule_center_replay_dataset_snapshots", ["validation_snapshot_id"], ["id"], ondelete="RESTRICT")
        batch.create_foreign_key("fk_scorecard_development_oot_snapshot", "rule_center_replay_dataset_snapshots", ["oot_snapshot_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_scorecard_development_runs_validation_snapshot_id", "scorecard_development_runs", ["validation_snapshot_id"])
    op.create_index("ix_scorecard_development_runs_validation_snapshot_hash", "scorecard_development_runs", ["validation_snapshot_hash"])
    op.create_index("ix_scorecard_development_runs_oot_snapshot_id", "scorecard_development_runs", ["oot_snapshot_id"])
    op.create_index("ix_scorecard_development_runs_oot_snapshot_hash", "scorecard_development_runs", ["oot_snapshot_hash"])


def downgrade() -> None:
    op.drop_index("ix_scorecard_development_runs_oot_snapshot_hash", table_name="scorecard_development_runs")
    op.drop_index("ix_scorecard_development_runs_oot_snapshot_id", table_name="scorecard_development_runs")
    op.drop_index("ix_scorecard_development_runs_validation_snapshot_hash", table_name="scorecard_development_runs")
    op.drop_index("ix_scorecard_development_runs_validation_snapshot_id", table_name="scorecard_development_runs")
    with op.batch_alter_table("scorecard_development_runs") as batch:
        batch.drop_constraint("fk_scorecard_development_oot_snapshot", type_="foreignkey")
        batch.drop_constraint("fk_scorecard_development_validation_snapshot", type_="foreignkey")
        batch.drop_column("oot_snapshot_hash")
        batch.drop_column("oot_snapshot_id")
        batch.drop_column("validation_snapshot_hash")
        batch.drop_column("validation_snapshot_id")
