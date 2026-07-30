"""track authority policy restore provenance

Revision ID: 20260726_0037
Revises: 20260726_0036
"""

from alembic import op
import sqlalchemy as sa


revision = "20260726_0037"
down_revision = "20260726_0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("credit_authority_policies", sa.Column("restore_source_policy_id", sa.String(length=36), nullable=True))
    op.add_column("credit_authority_policies", sa.Column("restore_source_policy_version", sa.String(length=128), nullable=True))
    op.create_index(
        "ix_credit_authority_policies_restore_source_policy_id",
        "credit_authority_policies",
        ["restore_source_policy_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_credit_authority_policies_restore_source_policy_id", table_name="credit_authority_policies")
    op.drop_column("credit_authority_policies", "restore_source_policy_version")
    op.drop_column("credit_authority_policies", "restore_source_policy_id")
