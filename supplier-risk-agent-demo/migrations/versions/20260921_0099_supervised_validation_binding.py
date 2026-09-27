"""Bind supervised validation evidence to model changes.

Revision ID: 20260921_0099
Revises: 20260919_0098
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260921_0099"
down_revision = "20260919_0098"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("model_changes") as batch:
        batch.add_column(sa.Column("supervised_validation_evidence_json", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("supervised_validation_binding_hash", sa.String(64), nullable=True))
    op.execute(sa.text("UPDATE model_changes SET supervised_validation_evidence_json = '{}' WHERE supervised_validation_evidence_json IS NULL"))
    op.create_index("ix_model_changes_supervised_validation_binding_hash", "model_changes", ["supervised_validation_binding_hash"])


def downgrade() -> None:
    op.drop_index("ix_model_changes_supervised_validation_binding_hash", table_name="model_changes")
    with op.batch_alter_table("model_changes") as batch:
        batch.drop_column("supervised_validation_binding_hash")
        batch.drop_column("supervised_validation_evidence_json")
