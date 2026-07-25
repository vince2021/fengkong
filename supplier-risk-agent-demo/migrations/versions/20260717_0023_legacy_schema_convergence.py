"""Converge legacy auto-created SQLite schemas with migration metadata.

Revision ID: 20260717_0023
Revises: 20260717_0022
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260717_0023"
down_revision = "20260717_0022"
branch_labels = None
depends_on = None


def _has_unique_constraint(inspector: sa.Inspector, table: str, columns: list[str]) -> bool:
    expected = set(columns)
    return any(set(item.get("column_names") or []) == expected for item in inspector.get_unique_constraints(table))


def _requires_numeric(inspector: sa.Inspector, table: str, column: str) -> bool:
    metadata = next(item for item in inspector.get_columns(table) if item["name"] == column)
    column_type = metadata["type"]
    return not (
        isinstance(column_type, sa.Numeric)
        and column_type.precision == 18
        and column_type.scale == 2
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_unique_constraint(inspector, "audit_events", ["aggregate_type", "aggregate_id", "previous_hash"]):
        with op.batch_alter_table("audit_events") as batch_op:
            batch_op.create_unique_constraint(
                "uq_audit_chain_parent",
                ["aggregate_type", "aggregate_id", "previous_hash"],
            )

    for table, columns in {
        "credit_facilities": ["approved_limit", "used_limit"],
        "credit_usage_transactions": ["amount", "balance_after"],
    }.items():
        if any(_requires_numeric(inspector, table, column) for column in columns):
            with op.batch_alter_table(table) as batch_op:
                for column in columns:
                    batch_op.alter_column(
                        column,
                        existing_type=next(
                            item["type"] for item in inspector.get_columns(table) if item["name"] == column
                        ),
                        type_=sa.Numeric(precision=18, scale=2),
                        existing_nullable=False,
                    )


def downgrade() -> None:
    # This migration only reconciles schemas that bypassed earlier migrations.
    # Reversing it would deliberately recreate the legacy drift.
    pass
