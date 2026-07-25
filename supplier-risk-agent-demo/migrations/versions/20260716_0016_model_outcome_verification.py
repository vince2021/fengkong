"""Require independent verification before outcomes enter model backtesting.

Revision ID: 20260716_0016
Revises: 20260715_0015
"""

from alembic import op
import sqlalchemy as sa


revision = "20260716_0016"
down_revision = "20260715_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("model_outcomes", sa.Column("verification_status", sa.String(length=32), nullable=False, server_default="pending_verification"))
    op.add_column("model_outcomes", sa.Column("verified_by", sa.String(length=128), nullable=True))
    op.add_column("model_outcomes", sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("model_outcomes", sa.Column("verification_note", sa.Text(), nullable=True))
    op.add_column("model_outcomes", sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"))
    op.create_index("ix_model_outcomes_verification_status", "model_outcomes", ["verification_status"])


def downgrade() -> None:
    op.drop_index("ix_model_outcomes_verification_status", table_name="model_outcomes")
    op.drop_column("model_outcomes", "row_version")
    op.drop_column("model_outcomes", "verification_note")
    op.drop_column("model_outcomes", "verified_at")
    op.drop_column("model_outcomes", "verified_by")
    op.drop_column("model_outcomes", "verification_status")
