"""add scorecard monitoring SLA and independent revalidation

Revision ID: 20260901_0069
Revises: 20260901_0068
"""
from alembic import op
import sqlalchemy as sa
from datetime import timedelta


revision = "20260901_0069"
down_revision = "20260901_0068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("scorecard_validation_monitoring_events") as batch:
        batch.add_column(sa.Column("sla_started_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("sla_due_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("escalation_level", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("last_escalated_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("remediated_by", sa.String(128), nullable=True))
        batch.add_column(sa.Column("remediated_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("revalidation_run_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("revalidation_evidence_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("revalidation_conclusion", sa.Text(), nullable=True))
        batch.add_column(sa.Column("revalidated_by", sa.String(128), nullable=True))
        batch.add_column(sa.Column("revalidated_by_name", sa.String(128), nullable=True))
        batch.add_column(sa.Column("revalidated_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key(
            "fk_scorecard_monitoring_event_revalidation_run",
            "scorecard_development_runs",
            ["revalidation_run_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    events = sa.table(
        "scorecard_validation_monitoring_events",
        sa.column("id", sa.String), sa.column("severity", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("sla_started_at", sa.DateTime(timezone=True)),
        sa.column("sla_due_at", sa.DateTime(timezone=True)),
    )
    connection = op.get_bind()
    for row in connection.execute(sa.select(events.c.id, events.c.severity, events.c.created_at)):
        hours = 24 if row.severity == "critical" else 72
        connection.execute(
            events.update().where(events.c.id == row.id).values(
                sla_started_at=row.created_at,
                sla_due_at=row.created_at + timedelta(hours=hours),
            )
        )
    with op.batch_alter_table("scorecard_validation_monitoring_events") as batch:
        batch.alter_column("sla_started_at", existing_type=sa.DateTime(timezone=True), nullable=False)
        batch.alter_column("sla_due_at", existing_type=sa.DateTime(timezone=True), nullable=False)

    op.create_index("ix_scorecard_validation_monitoring_events_sla_started_at", "scorecard_validation_monitoring_events", ["sla_started_at"])
    op.create_index("ix_scorecard_validation_monitoring_events_sla_due_at", "scorecard_validation_monitoring_events", ["sla_due_at"])
    op.create_index("ix_scorecard_validation_monitoring_events_revalidation_run_id", "scorecard_validation_monitoring_events", ["revalidation_run_id"])
    op.create_index(
        "ix_scorecard_validation_monitoring_event_sla_queue",
        "scorecard_validation_monitoring_events",
        ["status", "sla_due_at", "escalation_level"],
    )


def downgrade() -> None:
    op.drop_index("ix_scorecard_validation_monitoring_event_sla_queue", table_name="scorecard_validation_monitoring_events")
    op.drop_index("ix_scorecard_validation_monitoring_events_revalidation_run_id", table_name="scorecard_validation_monitoring_events")
    op.drop_index("ix_scorecard_validation_monitoring_events_sla_due_at", table_name="scorecard_validation_monitoring_events")
    op.drop_index("ix_scorecard_validation_monitoring_events_sla_started_at", table_name="scorecard_validation_monitoring_events")
    with op.batch_alter_table("scorecard_validation_monitoring_events") as batch:
        batch.drop_constraint("fk_scorecard_monitoring_event_revalidation_run", type_="foreignkey")
        batch.drop_column("revalidated_at")
        batch.drop_column("revalidated_by_name")
        batch.drop_column("revalidated_by")
        batch.drop_column("revalidation_conclusion")
        batch.drop_column("revalidation_evidence_hash")
        batch.drop_column("revalidation_run_id")
        batch.drop_column("remediated_at")
        batch.drop_column("remediated_by")
        batch.drop_column("last_escalated_at")
        batch.drop_column("escalation_level")
        batch.drop_column("sla_due_at")
        batch.drop_column("sla_started_at")
