"""persist authority policy impact assessment

Revision ID: 20260726_0036
Revises: 20260726_0035
"""

from alembic import op
import sqlalchemy as sa


revision = "20260726_0036"
down_revision = "20260726_0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("credit_authority_policies", sa.Column("impact_json", sa.JSON(), nullable=True))
    op.add_column("credit_authority_policies", sa.Column("impact_hash", sa.String(length=64), nullable=True))
    op.add_column("credit_authority_policies", sa.Column("impact_evaluated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("credit_authority_policies", "impact_evaluated_at")
    op.drop_column("credit_authority_policies", "impact_hash")
    op.drop_column("credit_authority_policies", "impact_json")
