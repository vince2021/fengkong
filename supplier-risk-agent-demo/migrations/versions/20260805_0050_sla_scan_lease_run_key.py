"""add run key to SLA scan execution lease

Revision ID: 20260805_0050
Revises: 20260805_0049
"""

from alembic import op
import sqlalchemy as sa


revision = "20260805_0050"
down_revision = "20260805_0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("sla_scan_leases")}
    if "run_key" not in columns:
        with op.batch_alter_table("sla_scan_leases") as batch_op:
            batch_op.add_column(sa.Column("run_key", sa.String(length=128), nullable=True))
    if bind.dialect.name == "sqlite":
        op.execute("PRAGMA optimize")


def downgrade() -> None:
    bind = op.get_bind()
    if "sla_scan_leases" not in sa.inspect(bind).get_table_names():
        return
    columns = {column["name"] for column in sa.inspect(bind).get_columns("sla_scan_leases")}
    if "run_key" in columns:
        with op.batch_alter_table("sla_scan_leases") as batch_op:
            batch_op.drop_column("run_key")
