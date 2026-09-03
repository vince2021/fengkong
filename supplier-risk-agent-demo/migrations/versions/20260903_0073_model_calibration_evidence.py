"""bind credit calibration evidence to model changes

Revision ID: 20260903_0073
Revises: 20260902_0072
"""
from alembic import op
import sqlalchemy as sa


revision = "20260903_0073"
down_revision = "20260902_0072"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("model_changes") as batch:
        batch.add_column(sa.Column("calibration_snapshot_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("calibration_evidence_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
        batch.add_column(sa.Column("calibration_evidence_binding_hash", sa.String(64), nullable=True))
        batch.create_foreign_key(
            "fk_model_change_calibration_snapshot",
            "rule_center_replay_dataset_snapshots",
            ["calibration_snapshot_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.create_index("ix_model_changes_calibration_snapshot_id", "model_changes", ["calibration_snapshot_id"])
    op.create_index("ix_model_changes_calibration_evidence_binding_hash", "model_changes", ["calibration_evidence_binding_hash"])


def downgrade() -> None:
    op.drop_index("ix_model_changes_calibration_evidence_binding_hash", table_name="model_changes")
    op.drop_index("ix_model_changes_calibration_snapshot_id", table_name="model_changes")
    with op.batch_alter_table("model_changes") as batch:
        batch.drop_constraint("fk_model_change_calibration_snapshot", type_="foreignkey")
        batch.drop_column("calibration_evidence_binding_hash")
        batch.drop_column("calibration_evidence_json")
        batch.drop_column("calibration_snapshot_id")
