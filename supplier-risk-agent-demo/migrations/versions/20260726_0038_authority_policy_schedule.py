"""add authority policy effective-date scheduling

Revision ID: 20260726_0038
Revises: 20260726_0037
"""

from alembic import op
import sqlalchemy as sa


revision = "20260726_0038"
down_revision = "20260726_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("credit_authority_policies", sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("credit_authority_policies", sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("credit_authority_policies", sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("credit_authority_policies", sa.Column("schedule_cancelled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("credit_authority_policies", sa.Column("schedule_cancelled_by", sa.String(length=128), nullable=True))
    op.add_column("credit_authority_policies", sa.Column("schedule_cancelled_by_name", sa.String(length=128), nullable=True))
    op.add_column("credit_authority_policies", sa.Column("schedule_cancel_reason", sa.Text(), nullable=True))
    op.create_index(
        "ix_credit_authority_policies_effective_at",
        "credit_authority_policies",
        ["effective_at"],
    )
    op.create_index(
        "uq_authority_policies_one_scheduled",
        "credit_authority_policies",
        ["status"],
        unique=True,
        sqlite_where=sa.text("status = 'scheduled'"),
        postgresql_where=sa.text("status = 'scheduled'"),
    )


def downgrade() -> None:
    op.drop_index("uq_authority_policies_one_scheduled", table_name="credit_authority_policies")
    op.drop_index("ix_credit_authority_policies_effective_at", table_name="credit_authority_policies")
    op.drop_column("credit_authority_policies", "schedule_cancel_reason")
    op.drop_column("credit_authority_policies", "schedule_cancelled_by_name")
    op.drop_column("credit_authority_policies", "schedule_cancelled_by")
    op.drop_column("credit_authority_policies", "schedule_cancelled_at")
    op.drop_column("credit_authority_policies", "superseded_at")
    op.drop_column("credit_authority_policies", "activated_at")
    op.drop_column("credit_authority_policies", "effective_at")
