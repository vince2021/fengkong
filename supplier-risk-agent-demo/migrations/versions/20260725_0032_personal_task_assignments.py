"""Add personal ownership to approval and correction tasks.

Revision ID: 20260725_0032
Revises: 20260725_0031
"""

from alembic import op
import sqlalchemy as sa


revision = "20260725_0032"
down_revision = "20260725_0031"
branch_labels = None
depends_on = None


def _add_assignment_columns(table_name: str) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    with op.batch_alter_table(table_name) as batch:
        if "assigned_to" not in columns:
            batch.add_column(sa.Column("assigned_to", sa.String(length=128), nullable=True))
        if "assigned_to_name" not in columns:
            batch.add_column(sa.Column("assigned_to_name", sa.String(length=128), nullable=True))
        if "assigned_at" not in columns:
            batch.add_column(sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True))
    inspector = sa.inspect(bind)
    index_name = f"ix_{table_name}_assigned_to"
    if index_name not in {index["name"] for index in inspector.get_indexes(table_name)}:
        op.create_index(index_name, table_name, ["assigned_to"], unique=False)


def upgrade() -> None:
    _add_assignment_columns("approval_cases")
    _add_assignment_columns("document_corrections")


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in ["document_corrections", "approval_cases"]:
        inspector = sa.inspect(bind)
        if table_name not in inspector.get_table_names():
            continue
        index_name = f"ix_{table_name}_assigned_to"
        if index_name in {index["name"] for index in inspector.get_indexes(table_name)}:
            op.drop_index(index_name, table_name=table_name)
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        with op.batch_alter_table(table_name) as batch:
            for name in ["assigned_at", "assigned_to_name", "assigned_to"]:
                if name in columns:
                    batch.drop_column(name)
