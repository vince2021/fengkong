"""Add SLA notification records.

Revision ID: 20260714_0007
Revises: 20260714_0006
"""

from alembic import op
import sqlalchemy as sa


revision = "20260714_0007"
down_revision = "20260714_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("case_id", sa.String(length=128), nullable=False),
        sa.Column("counterparty_id", sa.String(length=128), nullable=False),
        sa.Column("recipient_role", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("level", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("dedup_key", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="unread"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["case_id"], ["approval_cases.case_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedup_key", name="uq_notifications_dedup_key"),
    )
    op.create_index("ix_notifications_case_id", "notifications", ["case_id"], unique=False)
    op.create_index("ix_notifications_counterparty_id", "notifications", ["counterparty_id"], unique=False)
    op.create_index("ix_notifications_recipient_role", "notifications", ["recipient_role"], unique=False)
    op.create_index("ix_notifications_category", "notifications", ["category"], unique=False)
    op.create_index("ix_notifications_level", "notifications", ["level"], unique=False)
    op.create_index("ix_notifications_severity", "notifications", ["severity"], unique=False)
    op.create_index("ix_notifications_status", "notifications", ["status"], unique=False)
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"], unique=False)
    op.create_index("ix_notifications_role_status_created", "notifications", ["recipient_role", "status", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_table("notifications")
