"""Scope risk event idempotency keys by source.

Revision ID: 20260714_0014
Revises: 20260714_0013
"""

from alembic import op


revision = "20260714_0014"
down_revision = "20260714_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_risk_events_external_event_id", table_name="risk_events")
    op.create_index("ix_risk_events_external_event_id", "risk_events", ["external_event_id"])
    op.create_index("uq_risk_events_source_external_id", "risk_events", ["source", "external_event_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_risk_events_source_external_id", table_name="risk_events")
    op.drop_index("ix_risk_events_external_event_id", table_name="risk_events")
    op.create_index("ix_risk_events_external_event_id", "risk_events", ["external_event_id"], unique=True)
