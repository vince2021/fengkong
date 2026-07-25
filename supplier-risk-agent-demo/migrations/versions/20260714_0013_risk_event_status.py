"""Add lifecycle state to risk events.

Revision ID: 20260714_0013
Revises: 20260714_0012
"""

from alembic import op
import sqlalchemy as sa


revision = "20260714_0013"
down_revision = "20260714_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("risk_events", sa.Column("status", sa.String(length=16), nullable=False, server_default="active"))
    op.add_column("risk_events", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_risk_events_status", "risk_events", ["status"])


def downgrade() -> None:
    op.drop_index("ix_risk_events_status", table_name="risk_events")
    op.drop_column("risk_events", "resolved_at")
    op.drop_column("risk_events", "status")
