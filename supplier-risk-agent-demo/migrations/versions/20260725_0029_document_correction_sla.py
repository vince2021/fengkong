"""Add responsibility and SLA tracking to document corrections.

Revision ID: 20260725_0029
Revises: 20260721_0028
"""

from datetime import datetime, timedelta, timezone

from alembic import op
import sqlalchemy as sa


revision = "20260725_0029"
down_revision = "20260721_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "document_corrections" not in inspector.get_table_names():
        return
    existing_columns = {column["name"] for column in inspector.get_columns("document_corrections")}
    with op.batch_alter_table("document_corrections") as batch:
        if "assigned_role" not in existing_columns:
            batch.add_column(sa.Column("assigned_role", sa.String(length=64), nullable=True))
        if "sla_started_at" not in existing_columns:
            batch.add_column(sa.Column("sla_started_at", sa.DateTime(timezone=True), nullable=True))
        if "sla_due_at" not in existing_columns:
            batch.add_column(sa.Column("sla_due_at", sa.DateTime(timezone=True), nullable=True))

    table = sa.table(
        "document_corrections",
        sa.column("id", sa.String()),
        sa.column("status", sa.String()),
        sa.column("requested_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("assigned_role", sa.String()),
        sa.column("sla_started_at", sa.DateTime(timezone=True)),
        sa.column("sla_due_at", sa.DateTime(timezone=True)),
    )
    rows = bind.execute(
        sa.select(
            table.c.id,
            table.c.status,
            table.c.requested_at,
            table.c.created_at,
            table.c.assigned_role,
            table.c.sla_started_at,
            table.c.sla_due_at,
        )
    ).mappings()
    for row in rows:
        status = row["status"] if row["status"] in {"open", "resubmitted"} else "open"
        started_at = row["sla_started_at"] or row["requested_at"] or row["created_at"] or datetime.now(timezone.utc)
        role = row["assigned_role"] or ("risk_manager" if row["status"] == "resubmitted" else "relationship_manager")
        due_at = row["sla_due_at"] or started_at + timedelta(hours=24 if status == "resubmitted" else 48)
        bind.execute(
            table.update()
            .where(table.c.id == row["id"])
            .values(assigned_role=role, sla_started_at=started_at, sla_due_at=due_at)
        )

    with op.batch_alter_table("document_corrections") as batch:
        batch.alter_column("assigned_role", existing_type=sa.String(length=64), nullable=False)
        batch.alter_column("sla_started_at", existing_type=sa.DateTime(timezone=True), nullable=False)
        batch.alter_column("sla_due_at", existing_type=sa.DateTime(timezone=True), nullable=False)

    inspector = sa.inspect(bind)
    existing_indexes = {index["name"] for index in inspector.get_indexes("document_corrections")}
    for name, columns in [
        ("ix_document_corrections_assigned_role", ["assigned_role"]),
        ("ix_document_corrections_sla_started_at", ["sla_started_at"]),
        ("ix_document_corrections_sla_due_at", ["sla_due_at"]),
        ("ix_document_corrections_sla_status", ["status", "sla_due_at"]),
    ]:
        if name not in existing_indexes:
            op.create_index(name, "document_corrections", columns, unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "document_corrections" not in inspector.get_table_names():
        return
    existing_indexes = {index["name"] for index in inspector.get_indexes("document_corrections")}
    for name in [
        "ix_document_corrections_sla_status",
        "ix_document_corrections_sla_due_at",
        "ix_document_corrections_sla_started_at",
        "ix_document_corrections_assigned_role",
    ]:
        if name in existing_indexes:
            op.drop_index(name, table_name="document_corrections")
    with op.batch_alter_table("document_corrections") as batch:
        batch.drop_column("sla_due_at")
        batch.drop_column("sla_started_at")
        batch.drop_column("assigned_role")
