"""Add action counters to document correction tasks.

Revision ID: 20260725_0030
Revises: 20260725_0029
"""

from alembic import op
import sqlalchemy as sa


revision = "20260725_0030"
down_revision = "20260725_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "document_corrections" not in inspector.get_table_names():
        return
    existing_columns = {column["name"] for column in inspector.get_columns("document_corrections")}
    with op.batch_alter_table("document_corrections") as batch:
        if "reminder_count" not in existing_columns:
            batch.add_column(sa.Column("reminder_count", sa.Integer(), nullable=False, server_default=sa.text("0")))
        if "last_reminded_at" not in existing_columns:
            batch.add_column(sa.Column("last_reminded_at", sa.DateTime(timezone=True), nullable=True))
        if "extension_count" not in existing_columns:
            batch.add_column(sa.Column("extension_count", sa.Integer(), nullable=False, server_default=sa.text("0")))
        if "total_extension_hours" not in existing_columns:
            batch.add_column(sa.Column("total_extension_hours", sa.Integer(), nullable=False, server_default=sa.text("0")))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "document_corrections" not in inspector.get_table_names():
        return
    existing_columns = {column["name"] for column in inspector.get_columns("document_corrections")}
    with op.batch_alter_table("document_corrections") as batch:
        for name in ["total_extension_hours", "extension_count", "last_reminded_at", "reminder_count"]:
            if name in existing_columns:
                batch.drop_column(name)
