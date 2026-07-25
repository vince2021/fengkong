"""Add risk event ingestion and alert disposition metadata.

Revision ID: 20260714_0011
Revises: 20260714_0010
"""

from alembic import op
import sqlalchemy as sa


revision = "20260714_0011"
down_revision = "20260714_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("facility_alerts", sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("facility_alerts", sa.Column("acknowledged_by", sa.String(length=128), nullable=True))
    op.add_column("facility_alerts", sa.Column("disposition_action", sa.String(length=32), nullable=True))
    op.add_column("facility_alerts", sa.Column("disposition_note", sa.Text(), nullable=True))
    op.create_table(
        "risk_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("facility_id", sa.String(length=36), nullable=False),
        sa.Column("external_event_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("linked_alert_id", sa.String(length=36), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["facility_id"], ["credit_facilities.id"]),
        sa.ForeignKeyConstraint(["linked_alert_id"], ["facility_alerts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ["facility_id", "external_event_id", "event_type", "source", "severity", "occurred_at", "linked_alert_id", "created_at"]:
        op.create_index(f"ix_risk_events_{column}", "risk_events", [column], unique=column == "external_event_id")
    op.create_index("ix_risk_events_facility_occurred", "risk_events", ["facility_id", "occurred_at"])


def downgrade() -> None:
    op.drop_table("risk_events")
    op.drop_column("facility_alerts", "disposition_note")
    op.drop_column("facility_alerts", "disposition_action")
    op.drop_column("facility_alerts", "acknowledged_by")
    op.drop_column("facility_alerts", "acknowledged_at")
