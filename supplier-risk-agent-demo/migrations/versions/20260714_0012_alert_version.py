"""Add optimistic versioning to facility alerts.

Revision ID: 20260714_0012
Revises: 20260714_0011
"""

from alembic import op
import sqlalchemy as sa


revision = "20260714_0012"
down_revision = "20260714_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("facility_alerts", sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"))


def downgrade() -> None:
    op.drop_column("facility_alerts", "row_version")
