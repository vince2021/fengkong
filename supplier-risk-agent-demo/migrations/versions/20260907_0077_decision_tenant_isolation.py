"""isolate synchronous decisions by authenticated tenant

Revision ID: 20260907_0077
Revises: 20260903_0076
"""
from alembic import op
import sqlalchemy as sa


revision = "20260907_0077"
down_revision = "20260903_0076"
branch_labels = None
depends_on = None


TABLE = "decision_executions"
OLD_REQUEST_UNIQUE = "uq_decision_execution_request_id"
OLD_EVIDENCE_UNIQUE = "uq_decision_execution_evidence_hash"
TENANT_REQUEST_UNIQUE = "uq_decision_execution_tenant_request"


def upgrade() -> None:
    unique_constraints = {
        constraint["name"]
        for constraint in sa.inspect(op.get_bind()).get_unique_constraints(TABLE)
        if constraint.get("name")
    }
    with op.batch_alter_table(TABLE) as batch:
        batch.add_column(
            sa.Column("tenant_id", sa.String(128), nullable=False, server_default="tenant-legacy")
        )
        batch.add_column(
            sa.Column("client_id", sa.String(128), nullable=False, server_default="legacy-client")
        )
        if OLD_REQUEST_UNIQUE in unique_constraints:
            batch.drop_constraint(OLD_REQUEST_UNIQUE, type_="unique")
        if OLD_EVIDENCE_UNIQUE in unique_constraints:
            batch.drop_constraint(OLD_EVIDENCE_UNIQUE, type_="unique")
        batch.create_unique_constraint(
            TENANT_REQUEST_UNIQUE,
            ["tenant_id", "request_id"],
        )

    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column("tenant_id", server_default=None)
        batch.alter_column("client_id", server_default=None)

    op.create_index("ix_decision_executions_tenant_id", TABLE, ["tenant_id"])
    op.create_index("ix_decision_executions_client_id", TABLE, ["client_id"])
    op.create_index(
        "ix_decision_execution_tenant_created",
        TABLE,
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "ix_decision_execution_tenant_counterparty",
        TABLE,
        ["tenant_id", "counterparty_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_decision_execution_tenant_counterparty", table_name=TABLE)
    op.drop_index("ix_decision_execution_tenant_created", table_name=TABLE)
    op.drop_index("ix_decision_executions_client_id", table_name=TABLE)
    op.drop_index("ix_decision_executions_tenant_id", table_name=TABLE)

    with op.batch_alter_table(TABLE) as batch:
        batch.drop_constraint(TENANT_REQUEST_UNIQUE, type_="unique")
        batch.create_unique_constraint(OLD_REQUEST_UNIQUE, ["request_id"])
        batch.create_unique_constraint(OLD_EVIDENCE_UNIQUE, ["evidence_hash"])
        batch.drop_column("client_id")
        batch.drop_column("tenant_id")
