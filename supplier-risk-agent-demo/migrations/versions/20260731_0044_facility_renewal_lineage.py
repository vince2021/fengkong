"""add facility renewal lineage and opening balance

Revision ID: 20260731_0044
Revises: 20260730_0043
"""

from alembic import op
import sqlalchemy as sa


revision = "20260731_0044"
down_revision = "20260730_0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    approval_columns = {column["name"] for column in inspector.get_columns("approval_cases")}
    with op.batch_alter_table("approval_cases") as batch:
        if "application_type" not in approval_columns:
            batch.add_column(sa.Column("application_type", sa.String(length=32), nullable=False, server_default="new_credit"))
        if "source_facility_id" not in approval_columns:
            batch.add_column(sa.Column("source_facility_id", sa.String(length=36), nullable=True))
    approval_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("approval_cases")}
    if "ix_approval_cases_application_type" not in approval_indexes:
        op.create_index("ix_approval_cases_application_type", "approval_cases", ["application_type"])
    if "ix_approval_cases_source_facility_id" not in approval_indexes:
        op.create_index("ix_approval_cases_source_facility_id", "approval_cases", ["source_facility_id"])
    if "uq_approval_cases_open_renewal" not in approval_indexes:
        op.create_index(
            "uq_approval_cases_open_renewal",
            "approval_cases",
            ["source_facility_id"],
            unique=True,
            sqlite_where=sa.text("source_facility_id IS NOT NULL AND status IN ('处理中', '待补件')"),
            postgresql_where=sa.text("source_facility_id IS NOT NULL AND status IN ('处理中', '待补件')"),
        )

    facility_columns = {column["name"] for column in sa.inspect(bind).get_columns("credit_facilities")}
    with op.batch_alter_table("credit_facilities") as batch:
        if "opening_balance" not in facility_columns:
            batch.add_column(sa.Column("opening_balance", sa.Numeric(precision=18, scale=2), nullable=False, server_default="0"))
        if "supersedes_facility_id" not in facility_columns:
            batch.add_column(sa.Column("supersedes_facility_id", sa.String(length=36), nullable=True))
            batch.create_foreign_key(
                "fk_credit_facilities_supersedes",
                "credit_facilities",
                ["supersedes_facility_id"],
                ["id"],
            )
    facility_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("credit_facilities")}
    if "ix_credit_facilities_supersedes_facility_id" not in facility_indexes:
        op.create_index("ix_credit_facilities_supersedes_facility_id", "credit_facilities", ["supersedes_facility_id"])


def downgrade() -> None:
    bind = op.get_bind()
    facility_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("credit_facilities")}
    if "ix_credit_facilities_supersedes_facility_id" in facility_indexes:
        op.drop_index("ix_credit_facilities_supersedes_facility_id", table_name="credit_facilities")
    with op.batch_alter_table("credit_facilities") as batch:
        batch.drop_constraint("fk_credit_facilities_supersedes", type_="foreignkey")
        batch.drop_column("supersedes_facility_id")
        batch.drop_column("opening_balance")

    approval_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("approval_cases")}
    for name in ["uq_approval_cases_open_renewal", "ix_approval_cases_source_facility_id", "ix_approval_cases_application_type"]:
        if name in approval_indexes:
            op.drop_index(name, table_name="approval_cases")
    with op.batch_alter_table("approval_cases") as batch:
        batch.drop_column("source_facility_id")
        batch.drop_column("application_type")
