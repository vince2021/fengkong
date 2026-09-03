"""add scorecard validation gate review

Revision ID: 20260901_0065
Revises: 20260901_0064
"""
from alembic import op
import sqlalchemy as sa

revision = "20260901_0065"
down_revision = "20260901_0064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("scorecard_development_runs") as batch:
        batch.add_column(sa.Column("review_status", sa.String(32), nullable=False, server_default="not_required"))
        batch.add_column(sa.Column("reviewed_by", sa.String(128), nullable=True))
        batch.add_column(sa.Column("reviewed_by_name", sa.String(128), nullable=True))
        batch.add_column(sa.Column("review_comment", sa.Text(), nullable=True))
        batch.add_column(sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("review_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"))
    op.create_index("ix_scorecard_development_runs_review_status", "scorecard_development_runs", ["review_status"])
    op.create_index("ix_scorecard_development_runs_reviewed_by", "scorecard_development_runs", ["reviewed_by"])
    op.create_index("ix_scorecard_development_runs_review_hash", "scorecard_development_runs", ["review_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_scorecard_development_runs_review_hash", table_name="scorecard_development_runs")
    op.drop_index("ix_scorecard_development_runs_reviewed_by", table_name="scorecard_development_runs")
    op.drop_index("ix_scorecard_development_runs_review_status", table_name="scorecard_development_runs")
    with op.batch_alter_table("scorecard_development_runs") as batch:
        batch.drop_column("row_version")
        batch.drop_column("review_hash")
        batch.drop_column("reviewed_at")
        batch.drop_column("review_comment")
        batch.drop_column("reviewed_by_name")
        batch.drop_column("reviewed_by")
        batch.drop_column("review_status")
