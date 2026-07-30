"""Add expiration leases to personal task assignments.

Revision ID: 20260726_0033
Revises: 20260725_0032
"""

from datetime import timedelta

from alembic import op
import sqlalchemy as sa


revision = "20260726_0033"
down_revision = "20260725_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table_name in ["approval_cases", "document_corrections"]:
        if table_name not in inspector.get_table_names():
            continue
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        if "assignment_expires_at" not in columns:
            with op.batch_alter_table(table_name) as batch:
                batch.add_column(sa.Column("assignment_expires_at", sa.DateTime(timezone=True), nullable=True))
        assignment_table = sa.table(
            table_name,
            sa.column("assigned_to", sa.String()),
            sa.column("assigned_at", sa.DateTime(timezone=True)),
            sa.column("assignment_expires_at", sa.DateTime(timezone=True)),
        )
        rows = bind.execute(
            sa.select(assignment_table.c.assigned_at).where(
                assignment_table.c.assigned_to.is_not(None),
                assignment_table.c.assigned_at.is_not(None),
                assignment_table.c.assignment_expires_at.is_(None),
            )
        ).all()
        for (assigned_at,) in rows:
            bind.execute(
                assignment_table.update()
                .where(
                    assignment_table.c.assigned_to.is_not(None),
                    assignment_table.c.assigned_at == assigned_at,
                    assignment_table.c.assignment_expires_at.is_(None),
                )
                .values(assignment_expires_at=assigned_at + timedelta(hours=4))
            )


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in ["document_corrections", "approval_cases"]:
        inspector = sa.inspect(bind)
        if table_name not in inspector.get_table_names():
            continue
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        if "assignment_expires_at" in columns:
            with op.batch_alter_table(table_name) as batch:
                batch.drop_column("assignment_expires_at")
