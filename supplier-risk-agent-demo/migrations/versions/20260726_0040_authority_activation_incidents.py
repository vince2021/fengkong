"""add authority policy activation incident disposition

Revision ID: 20260726_0040
Revises: 20260726_0039
"""

from alembic import op
import sqlalchemy as sa


revision = "20260726_0040"
down_revision = "20260726_0039"
branch_labels = None
depends_on = None


RUN_TABLE = "authority_policy_activation_runs"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns(RUN_TABLE)}
    additions = [
        ("incident_status", sa.Column("incident_status", sa.String(length=32), nullable=False, server_default="not_applicable")),
        ("acknowledged_by", sa.Column("acknowledged_by", sa.String(length=128), nullable=True)),
        ("acknowledged_by_name", sa.Column("acknowledged_by_name", sa.String(length=128), nullable=True)),
        ("acknowledged_at", sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True)),
        ("acknowledgement_note", sa.Column("acknowledgement_note", sa.Text(), nullable=True)),
        ("resolved_by", sa.Column("resolved_by", sa.String(length=128), nullable=True)),
        ("resolved_by_name", sa.Column("resolved_by_name", sa.String(length=128), nullable=True)),
        ("resolved_at", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True)),
        ("resolution_type", sa.Column("resolution_type", sa.String(length=32), nullable=True)),
        ("resolution_note", sa.Column("resolution_note", sa.Text(), nullable=True)),
        ("retry_of_run_id", sa.Column("retry_of_run_id", sa.String(length=36), nullable=True)),
        ("resolved_by_run_id", sa.Column("resolved_by_run_id", sa.String(length=36), nullable=True)),
        ("row_version", sa.Column("row_version", sa.Integer(), nullable=False, server_default="1")),
    ]
    with op.batch_alter_table(RUN_TABLE) as batch:
        for name, column in additions:
            if name not in columns:
                batch.add_column(column)

    op.execute(
        sa.text(
            f"UPDATE {RUN_TABLE} SET incident_status = "
            "CASE WHEN status = 'blocked' THEN 'open' ELSE 'not_applicable' END "
            "WHERE incident_status = 'not_applicable'"
        )
    )

    inspector = sa.inspect(bind)
    foreign_keys = inspector.get_foreign_keys(RUN_TABLE)
    foreign_key_columns = {
        tuple(item.get("constrained_columns") or [])
        for item in foreign_keys
    }
    with op.batch_alter_table(RUN_TABLE) as batch:
        if ("retry_of_run_id",) not in foreign_key_columns:
            batch.create_foreign_key(
                "fk_authority_activation_retry_of_run",
                RUN_TABLE,
                ["retry_of_run_id"],
                ["id"],
            )
        if ("resolved_by_run_id",) not in foreign_key_columns:
            batch.create_foreign_key(
                "fk_authority_activation_resolved_by_run",
                RUN_TABLE,
                ["resolved_by_run_id"],
                ["id"],
            )

    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes(RUN_TABLE)}
    index_specs = {
        "ix_authority_policy_activation_runs_incident_status": ["incident_status"],
        "ix_authority_policy_activation_runs_retry_of_run_id": ["retry_of_run_id"],
        "ix_authority_activation_runs_incident_created": ["incident_status", "created_at"],
    }
    for name, index_columns in index_specs.items():
        if name not in indexes:
            op.create_index(name, RUN_TABLE, index_columns)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes(RUN_TABLE)}
    for name in [
        "ix_authority_activation_runs_incident_created",
        "ix_authority_policy_activation_runs_retry_of_run_id",
        "ix_authority_policy_activation_runs_incident_status",
    ]:
        if name in indexes:
            op.drop_index(name, table_name=RUN_TABLE)
    inspector = sa.inspect(bind)
    foreign_key_names = {
        item.get("name")
        for item in inspector.get_foreign_keys(RUN_TABLE)
        if item.get("name")
    }
    with op.batch_alter_table(RUN_TABLE) as batch:
        if "fk_authority_activation_resolved_by_run" in foreign_key_names:
            batch.drop_constraint("fk_authority_activation_resolved_by_run", type_="foreignkey")
        if "fk_authority_activation_retry_of_run" in foreign_key_names:
            batch.drop_constraint("fk_authority_activation_retry_of_run", type_="foreignkey")
        for column in [
            "row_version",
            "resolved_by_run_id",
            "retry_of_run_id",
            "resolution_note",
            "resolution_type",
            "resolved_at",
            "resolved_by_name",
            "resolved_by",
            "acknowledgement_note",
            "acknowledged_at",
            "acknowledged_by_name",
            "acknowledged_by",
            "incident_status",
        ]:
            batch.drop_column(column)
