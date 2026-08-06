"""converge control condition schema and remove legacy indexes

Revision ID: 20260805_0051
Revises: 20260805_0050
"""

from alembic import op
import sqlalchemy as sa


revision = "20260805_0051"
down_revision = "20260805_0050"
branch_labels = None
depends_on = None


LEGACY_CONDITION_INDEXES = {
    "ix_facility_control_conditions_created_at",
    "ix_facility_control_conditions_due_at",
    "ix_facility_control_conditions_facility_id",
    "ix_facility_control_conditions_owner_role",
    "ix_facility_control_conditions_source_case_id",
    "ix_facility_control_conditions_source_review_hash",
    "ix_facility_control_conditions_status",
}
LEGACY_EXTENSION_INDEXES = {
    "ix_facility_control_extensions_condition_status_created",
}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    condition_columns = {column["name"]: column for column in inspector.get_columns("facility_control_conditions")}
    source_case_type = condition_columns["source_case_id"]["type"]
    if getattr(source_case_type, "length", None) != 128:
        with op.batch_alter_table("facility_control_conditions") as batch_op:
            batch_op.alter_column(
                "source_case_id",
                existing_type=source_case_type,
                type_=sa.String(length=128),
                existing_nullable=False,
            )

    condition_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("facility_control_conditions")}
    for index_name in sorted(LEGACY_CONDITION_INDEXES & condition_indexes):
        op.drop_index(index_name, table_name="facility_control_conditions")
    extension_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("facility_control_extensions")}
    for index_name in sorted(LEGACY_EXTENSION_INDEXES & extension_indexes):
        op.drop_index(index_name, table_name="facility_control_extensions")
    if bind.dialect.name == "sqlite":
        op.execute("PRAGMA optimize")


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"]: column for column in sa.inspect(bind).get_columns("facility_control_conditions")}
    source_case_type = columns["source_case_id"]["type"]
    if getattr(source_case_type, "length", None) != 64:
        with op.batch_alter_table("facility_control_conditions") as batch_op:
            batch_op.alter_column(
                "source_case_id",
                existing_type=source_case_type,
                type_=sa.String(length=64),
                existing_nullable=False,
            )
