"""bind approvals and indicator observations to tenant counterparties

Revision ID: 20260907_0082
Revises: 20260907_0081
"""
from alembic import op
import sqlalchemy as sa


revision = "20260907_0082"
down_revision = "20260907_0081"
branch_labels = None
depends_on = None

LEGACY_TENANT_ID = "tenant-demo-hengxin"


def _backfill_tenant_id(table_name: str) -> None:
    connection = op.get_bind()
    counterparty_ids = connection.execute(
        sa.text(f"SELECT DISTINCT counterparty_id FROM {table_name} WHERE tenant_id IS NULL")
    ).scalars().all()
    for counterparty_id in counterparty_ids:
        matches = connection.execute(
            sa.text(
                "SELECT tenant_id FROM counterparties "
                "WHERE counterparty_id = :counterparty_id ORDER BY tenant_id"
            ),
            {"counterparty_id": counterparty_id},
        ).scalars().all()
        if not matches:
            raise RuntimeError(
                f"Cannot backfill {table_name}: counterparty {counterparty_id!r} is not registered in counterparties"
            )
        if LEGACY_TENANT_ID in matches:
            tenant_id = LEGACY_TENANT_ID
        elif len(matches) == 1:
            tenant_id = matches[0]
        else:
            raise RuntimeError(
                f"Cannot backfill {table_name}: counterparty {counterparty_id!r} is ambiguous across tenants"
            )
        connection.execute(
            sa.text(f"UPDATE {table_name} SET tenant_id = :tenant_id WHERE tenant_id IS NULL AND counterparty_id = :counterparty_id"),
            {"tenant_id": tenant_id, "counterparty_id": counterparty_id},
        )


def upgrade() -> None:
    with op.batch_alter_table("approval_cases") as batch:
        batch.add_column(sa.Column("tenant_id", sa.String(128), nullable=True))
    with op.batch_alter_table("enterprise_indicator_observations") as batch:
        batch.add_column(sa.Column("tenant_id", sa.String(128), nullable=True))

    _backfill_tenant_id("approval_cases")
    _backfill_tenant_id("enterprise_indicator_observations")

    with op.batch_alter_table("approval_cases") as batch:
        batch.alter_column("tenant_id", existing_type=sa.String(128), nullable=False)
        batch.create_foreign_key(
            "fk_approval_case_tenant_counterparty",
            "counterparties",
            ["tenant_id", "counterparty_id"],
            ["tenant_id", "counterparty_id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_approval_cases_tenant_id", ["tenant_id"])
        batch.create_index(
            "ix_approval_cases_tenant_counterparty_created", ["tenant_id", "counterparty_id", "created_at"]
        )
        batch.create_index("ix_approval_cases_tenant_status_created", ["tenant_id", "status", "created_at"])

    with op.batch_alter_table("enterprise_indicator_observations") as batch:
        batch.drop_index("uq_indicator_observations_pending")
        batch.drop_index("ix_indicator_observations_counterparty_indicator")
        batch.alter_column("tenant_id", existing_type=sa.String(128), nullable=False)
        batch.create_foreign_key(
            "fk_indicator_observation_tenant_counterparty",
            "counterparties",
            ["tenant_id", "counterparty_id"],
            ["tenant_id", "counterparty_id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_enterprise_indicator_observations_tenant_id", ["tenant_id"])
        batch.create_index(
            "ix_indicator_observations_tenant_counterparty_indicator",
            ["tenant_id", "counterparty_id", "indicator_id", "created_at"],
        )
        batch.create_index(
            "ix_indicator_observations_tenant_status_created", ["tenant_id", "status", "created_at"]
        )
        batch.create_index(
            "uq_indicator_observations_pending",
            ["tenant_id", "counterparty_id", "indicator_id"],
            unique=True,
            sqlite_where=sa.text("status = 'pending_review'"),
            postgresql_where=sa.text("status = 'pending_review'"),
        )


def downgrade() -> None:
    with op.batch_alter_table("enterprise_indicator_observations") as batch:
        batch.drop_index("uq_indicator_observations_pending")
        batch.drop_index("ix_indicator_observations_tenant_status_created")
        batch.drop_index("ix_indicator_observations_tenant_counterparty_indicator")
        batch.drop_index("ix_enterprise_indicator_observations_tenant_id")
        batch.drop_constraint("fk_indicator_observation_tenant_counterparty", type_="foreignkey")
        batch.drop_column("tenant_id")
        batch.create_index(
            "ix_indicator_observations_counterparty_indicator", ["counterparty_id", "indicator_id", "created_at"]
        )
        batch.create_index(
            "uq_indicator_observations_pending",
            ["counterparty_id", "indicator_id"],
            unique=True,
            sqlite_where=sa.text("status = 'pending_review'"),
            postgresql_where=sa.text("status = 'pending_review'"),
        )

    with op.batch_alter_table("approval_cases") as batch:
        batch.drop_index("ix_approval_cases_tenant_status_created")
        batch.drop_index("ix_approval_cases_tenant_counterparty_created")
        batch.drop_index("ix_approval_cases_tenant_id")
        batch.drop_constraint("fk_approval_case_tenant_counterparty", type_="foreignkey")
        batch.drop_column("tenant_id")
