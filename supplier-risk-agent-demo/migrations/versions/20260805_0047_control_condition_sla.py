"""add control condition SLA escalation

Revision ID: 20260805_0047
Revises: 20260805_0046
"""

from alembic import op
import sqlalchemy as sa


revision = "20260805_0047"
down_revision = "20260805_0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("facility_control_conditions")}
    foreign_keys = {foreign_key["name"] for foreign_key in inspector.get_foreign_keys("facility_control_conditions")}
    with op.batch_alter_table("facility_control_conditions") as batch:
        if "escalation_level" not in columns:
            batch.add_column(sa.Column("escalation_level", sa.Integer(), nullable=False, server_default="0"))
        if "escalation_role" not in columns:
            batch.add_column(sa.Column("escalation_role", sa.String(length=64), nullable=True))
        if "escalated_at" not in columns:
            batch.add_column(sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True))
        if "linked_alert_id" not in columns:
            batch.add_column(sa.Column("linked_alert_id", sa.String(length=36), nullable=True))
        if "fk_facility_control_conditions_linked_alert" not in foreign_keys:
            batch.create_foreign_key(
                "fk_facility_control_conditions_linked_alert",
                "facility_alerts",
                ["linked_alert_id"],
                ["id"],
            )
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("facility_control_conditions")}
    if "ix_facility_control_conditions_status_due" not in indexes:
        op.create_index(
            "ix_facility_control_conditions_status_due",
            "facility_control_conditions",
            ["status", "due_at"],
        )
    if bind.dialect.name == "sqlite":
        op.execute("PRAGMA optimize")


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("facility_control_conditions")}
    if "ix_facility_control_conditions_status_due" in indexes:
        op.drop_index("ix_facility_control_conditions_status_due", table_name="facility_control_conditions")
    columns = {column["name"] for column in sa.inspect(bind).get_columns("facility_control_conditions")}
    foreign_keys = {foreign_key["name"] for foreign_key in sa.inspect(bind).get_foreign_keys("facility_control_conditions")}
    with op.batch_alter_table("facility_control_conditions") as batch:
        if "fk_facility_control_conditions_linked_alert" in foreign_keys:
            batch.drop_constraint("fk_facility_control_conditions_linked_alert", type_="foreignkey")
        for column_name in ["linked_alert_id", "escalated_at", "escalation_role", "escalation_level"]:
            if column_name in columns:
                batch.drop_column(column_name)
