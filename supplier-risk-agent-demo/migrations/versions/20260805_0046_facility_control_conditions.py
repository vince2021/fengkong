"""add facility control condition tasks

Revision ID: 20260805_0046
Revises: 20260731_0045
"""

from alembic import op
import sqlalchemy as sa


revision = "20260805_0046"
down_revision = "20260731_0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "facility_control_conditions" not in inspector.get_table_names():
        op.create_table(
            "facility_control_conditions",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("facility_id", sa.String(length=36), sa.ForeignKey("credit_facilities.id"), nullable=False),
            sa.Column("source_case_id", sa.String(length=64), sa.ForeignKey("approval_cases.case_id"), nullable=False),
            sa.Column("source_review_hash", sa.String(length=64), nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("measure", sa.Text(), nullable=False),
            sa.Column("owner_role", sa.String(length=64), nullable=False, server_default="risk_manager"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completion_note", sa.Text(), nullable=True),
            sa.Column("completed_by", sa.String(length=128), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("source_case_id", "sequence", name="uq_facility_control_condition_source_sequence"),
        )
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("facility_control_conditions")}
    if "ix_facility_control_conditions_facility_status_due" not in indexes:
        op.create_index("ix_facility_control_conditions_facility_status_due", "facility_control_conditions", ["facility_id", "status", "due_at"])
    if bind.dialect.name == "sqlite":
        op.execute("PRAGMA optimize")


def downgrade() -> None:
    if "facility_control_conditions" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("facility_control_conditions")
