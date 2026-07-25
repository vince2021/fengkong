"""Prevent audit hash-chain forks.

Revision ID: 20260714_0003
Revises: 20260714_0002
"""

from alembic import op


revision = "20260714_0003"
down_revision = "20260714_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("audit_events") as batch_op:
        batch_op.create_unique_constraint("uq_audit_chain_parent", ["aggregate_type", "aggregate_id", "previous_hash"])


def downgrade() -> None:
    with op.batch_alter_table("audit_events") as batch_op:
        batch_op.drop_constraint("uq_audit_chain_parent", type_="unique")
