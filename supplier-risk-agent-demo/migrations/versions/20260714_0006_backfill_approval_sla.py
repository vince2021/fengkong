"""Backfill SLA timestamps for existing approval cases.

Revision ID: 20260714_0006
Revises: 20260714_0005
"""

from datetime import datetime, timedelta, timezone

from alembic import op
import sqlalchemy as sa


revision = "20260714_0006"
down_revision = "20260714_0005"
branch_labels = None
depends_on = None

STAGE_SLA_HOURS = {
    "registration": 8,
    "document_upload": 48,
    "supplement": 48,
    "approval_submit": 8,
    "model_selection": 8,
    "scoring": 2,
    "credit_proposal": 16,
    "final_strategy": 24,
}


def upgrade() -> None:
    approval_cases = sa.table(
        "approval_cases",
        sa.column("case_id", sa.String),
        sa.column("current_stage", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("stage_started_at", sa.DateTime(timezone=True)),
        sa.column("stage_due_at", sa.DateTime(timezone=True)),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(approval_cases.c.case_id, approval_cases.c.current_stage, approval_cases.c.created_at, approval_cases.c.updated_at)
        .where(approval_cases.c.stage_due_at.is_(None))
    ).all()
    now = datetime.now(timezone.utc)
    for row in rows:
        started_at = row.updated_at or row.created_at or now
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        due_at = started_at + timedelta(hours=STAGE_SLA_HOURS.get(row.current_stage, 24))
        connection.execute(
            sa.update(approval_cases)
            .where(approval_cases.c.case_id == row.case_id)
            .values(stage_started_at=started_at, stage_due_at=due_at)
        )


def downgrade() -> None:
    pass
