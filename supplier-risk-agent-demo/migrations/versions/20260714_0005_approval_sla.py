"""Add approval stage SLA timestamps.

Revision ID: 20260714_0005
Revises: 20260714_0004
"""

from alembic import op
import sqlalchemy as sa


revision = "20260714_0005"
down_revision = "20260714_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("approval_cases") as batch_op:
        batch_op.add_column(sa.Column("stage_started_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("stage_due_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index("ix_approval_cases_stage_due_at", ["stage_due_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("approval_cases") as batch_op:
        batch_op.drop_index("ix_approval_cases_stage_due_at")
        batch_op.drop_column("stage_due_at")
        batch_op.drop_column("stage_started_at")
