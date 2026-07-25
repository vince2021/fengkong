"""Ensure one active release per model template.

Revision ID: 20260714_0009
Revises: 20260714_0008
"""

from alembic import op
import sqlalchemy as sa


revision = "20260714_0009"
down_revision = "20260714_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_model_releases_one_active",
        "model_releases",
        ["template_key"],
        unique=True,
        sqlite_where=sa.text("is_active = 1"),
        postgresql_where=sa.text("is_active IS TRUE"),
    )


def downgrade() -> None:
    op.drop_index("uq_model_releases_one_active", table_name="model_releases")
