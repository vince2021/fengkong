"""add durable SLA scan execution lease

Revision ID: 20260805_0049
Revises: 20260805_0048
"""

from alembic import op
import sqlalchemy as sa


revision = "20260805_0049"
down_revision = "20260805_0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "sla_scan_leases" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "sla_scan_leases",
            sa.Column("lease_key", sa.String(length=64), primary_key=True),
            sa.Column("execution_id", sa.String(length=36), nullable=True),
            sa.Column("actor", sa.String(length=128), nullable=True),
            sa.Column("trigger_type", sa.String(length=32), nullable=True),
            sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    if bind.dialect.name == "sqlite":
        op.execute("PRAGMA optimize")


def downgrade() -> None:
    if "sla_scan_leases" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("sla_scan_leases")
