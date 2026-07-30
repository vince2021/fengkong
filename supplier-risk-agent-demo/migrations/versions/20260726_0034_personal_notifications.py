"""Add personal recipients to task notifications.

Revision ID: 20260726_0034
Revises: 20260726_0033
"""

from alembic import op
import sqlalchemy as sa


revision = "20260726_0034"
down_revision = "20260726_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "notifications" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("notifications")}
    if "recipient_subject" not in columns:
        with op.batch_alter_table("notifications") as batch:
            batch.add_column(sa.Column("recipient_subject", sa.String(length=128), nullable=True))
    inspector = sa.inspect(bind)
    if "ix_notifications_subject_status_created" not in {index["name"] for index in inspector.get_indexes("notifications")}:
        op.create_index(
            "ix_notifications_subject_status_created",
            "notifications",
            ["recipient_subject", "status", "created_at"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "notifications" not in inspector.get_table_names():
        return
    if "ix_notifications_subject_status_created" in {index["name"] for index in inspector.get_indexes("notifications")}:
        op.drop_index("ix_notifications_subject_status_created", table_name="notifications")
    columns = {column["name"] for column in inspector.get_columns("notifications")}
    if "recipient_subject" in columns:
        with op.batch_alter_table("notifications") as batch:
            batch.drop_column("recipient_subject")
