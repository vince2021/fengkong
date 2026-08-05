"""add governed control condition extensions

Revision ID: 20260805_0048
Revises: 20260805_0047
"""

from alembic import op
import sqlalchemy as sa


revision = "20260805_0048"
down_revision = "20260805_0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "facility_control_extensions" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "facility_control_extensions",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("condition_id", sa.String(length=36), sa.ForeignKey("facility_control_conditions.id"), nullable=False),
            sa.Column("facility_id", sa.String(length=36), sa.ForeignKey("credit_facilities.id"), nullable=False),
            sa.Column("extension_days", sa.Integer(), nullable=False),
            sa.Column("previous_due_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("proposed_due_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("requested_by", sa.String(length=128), nullable=False),
            sa.Column("requested_by_name", sa.String(length=128), nullable=False),
            sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("reviewed_by", sa.String(length=128), nullable=True),
            sa.Column("reviewed_by_name", sa.String(length=128), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("review_comment", sa.Text(), nullable=True),
            sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("facility_control_extensions")}
    if "ix_facility_control_extensions_condition_requested" not in indexes:
        op.create_index(
            "ix_facility_control_extensions_condition_requested",
            "facility_control_extensions",
            ["condition_id", "requested_at"],
        )
    if "uq_facility_control_extensions_pending" not in indexes:
        op.create_index(
            "uq_facility_control_extensions_pending",
            "facility_control_extensions",
            ["condition_id"],
            unique=True,
            sqlite_where=sa.text("status = 'pending'"),
            postgresql_where=sa.text("status = 'pending'"),
        )
    if bind.dialect.name == "sqlite":
        op.execute("PRAGMA optimize")


def downgrade() -> None:
    if "facility_control_extensions" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("facility_control_extensions")
