"""bind approved scorecard validation evidence to model changes

Revision ID: 20260901_0066
Revises: 20260901_0065
"""
from alembic import op
import sqlalchemy as sa


revision = "20260901_0066"
down_revision = "20260901_0065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("model_changes") as batch:
        batch.add_column(sa.Column("scorecard_validation_run_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("scorecard_validation_evidence_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
        batch.add_column(sa.Column("scorecard_validation_binding_hash", sa.String(64), nullable=True))
        batch.create_foreign_key(
            "fk_model_change_scorecard_validation_run",
            "scorecard_development_runs",
            ["scorecard_validation_run_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.create_index("ix_model_changes_scorecard_validation_run_id", "model_changes", ["scorecard_validation_run_id"])
    op.create_index("ix_model_changes_scorecard_validation_binding_hash", "model_changes", ["scorecard_validation_binding_hash"])


def downgrade() -> None:
    op.drop_index("ix_model_changes_scorecard_validation_binding_hash", table_name="model_changes")
    op.drop_index("ix_model_changes_scorecard_validation_run_id", table_name="model_changes")
    with op.batch_alter_table("model_changes") as batch:
        batch.drop_constraint("fk_model_change_scorecard_validation_run", type_="foreignkey")
        batch.drop_column("scorecard_validation_binding_hash")
        batch.drop_column("scorecard_validation_evidence_json")
        batch.drop_column("scorecard_validation_run_id")
