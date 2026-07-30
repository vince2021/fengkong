"""Add structured navigation actions to notifications.

Revision ID: 20260725_0031
Revises: 20260725_0030
"""

from alembic import op
import sqlalchemy as sa


revision = "20260725_0031"
down_revision = "20260725_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "notifications" not in inspector.get_table_names():
        return
    existing_columns = {column["name"] for column in inspector.get_columns("notifications")}
    if "action_json" not in existing_columns:
        with op.batch_alter_table("notifications") as batch:
            batch.add_column(
                sa.Column("action_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "notifications" not in inspector.get_table_names():
        return
    existing_columns = {column["name"] for column in inspector.get_columns("notifications")}
    if "action_json" in existing_columns:
        with op.batch_alter_table("notifications") as batch:
            batch.drop_column("action_json")
