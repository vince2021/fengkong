"""Add versioned public signing-key metadata to model validation issuances.

Revision ID: 20260922_0103
Revises: 20260922_0102
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260922_0103"
down_revision = "20260922_0102"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("model_validation_report_issuances", sa.Column("signing_key_id", sa.String(128), nullable=True))
    op.add_column("model_validation_report_issuances", sa.Column("signing_public_key", sa.Text(), nullable=True))
    if op.get_bind().dialect.name != "sqlite":
        op.alter_column("model_validation_report_issuances", "signature", existing_type=sa.String(64), type_=sa.Text(), existing_nullable=False)
    op.create_index("ix_model_validation_issuance_signing_key_id", "model_validation_report_issuances", ["signing_key_id"])


def downgrade() -> None:
    op.drop_index("ix_model_validation_issuance_signing_key_id", table_name="model_validation_report_issuances")
    if op.get_bind().dialect.name != "sqlite":
        op.alter_column("model_validation_report_issuances", "signature", existing_type=sa.Text(), type_=sa.String(64), existing_nullable=False)
    op.drop_column("model_validation_report_issuances", "signing_public_key")
    op.drop_column("model_validation_report_issuances", "signing_key_id")
