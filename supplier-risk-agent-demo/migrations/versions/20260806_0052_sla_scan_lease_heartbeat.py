"""add SLA scan lease heartbeat evidence

Revision ID: 20260806_0052
Revises: 20260805_0051
"""

from alembic import op
import sqlalchemy as sa


revision = "20260806_0052"
down_revision = "20260805_0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "sla_scan_leases" not in sa.inspect(bind).get_table_names():
        return
    columns = {column["name"] for column in sa.inspect(bind).get_columns("sla_scan_leases")}
    with op.batch_alter_table("sla_scan_leases") as batch_op:
        if "last_heartbeat_at" not in columns:
            batch_op.add_column(sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True))
        if "heartbeat_count" not in columns:
            batch_op.add_column(sa.Column("heartbeat_count", sa.Integer(), nullable=False, server_default="0"))
    if bind.dialect.name == "sqlite":
        op.execute("PRAGMA optimize")


def downgrade() -> None:
    bind = op.get_bind()
    if "sla_scan_leases" not in sa.inspect(bind).get_table_names():
        return
    columns = {column["name"] for column in sa.inspect(bind).get_columns("sla_scan_leases")}
    with op.batch_alter_table("sla_scan_leases") as batch_op:
        if "heartbeat_count" in columns:
            batch_op.drop_column("heartbeat_count")
        if "last_heartbeat_at" in columns:
            batch_op.drop_column("last_heartbeat_at")
