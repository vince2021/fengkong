"""Bind rating runs to approval cases.

Revision ID: 20260714_0004
Revises: 20260714_0003
"""

from alembic import op
import sqlalchemy as sa


revision = "20260714_0004"
down_revision = "20260714_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("rating_runs") as batch_op:
        batch_op.add_column(sa.Column("case_id", sa.String(length=128), nullable=True))
        batch_op.create_foreign_key("fk_rating_runs_case_id", "approval_cases", ["case_id"], ["case_id"])
        batch_op.create_index("ix_rating_runs_case_id", ["case_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("rating_runs") as batch_op:
        batch_op.drop_index("ix_rating_runs_case_id")
        batch_op.drop_constraint("fk_rating_runs_case_id", type_="foreignkey")
        batch_op.drop_column("case_id")
