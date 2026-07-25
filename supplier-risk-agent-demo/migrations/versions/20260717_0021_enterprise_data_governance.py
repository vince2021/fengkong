"""Add governed enterprise data imports and field lineage.

Revision ID: 20260717_0021
Revises: 20260716_0020
"""

from alembic import op
import sqlalchemy as sa


revision = "20260717_0021"
down_revision = "20260716_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "enterprise_data_imports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("import_key", sa.String(length=256), nullable=False),
        sa.Column("counterparty_id", sa.String(length=128), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("source_priority", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("as_of_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_reference", sa.Text(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("field_count", sa.Integer(), nullable=False),
        sa.Column("conflict_count", sa.Integer(), nullable=False),
        sa.Column("stale_count", sa.Integer(), nullable=False),
        sa.Column("invalid_count", sa.Integer(), nullable=False),
        sa.Column("quality_score", sa.Numeric(precision=6, scale=4), nullable=False),
        sa.Column("quality_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("import_key", name="uq_enterprise_data_import_key"),
    )
    for name, columns, unique in [
        ("ix_enterprise_data_imports_import_key", ["import_key"], True),
        ("ix_enterprise_data_imports_counterparty_id", ["counterparty_id"], False),
        ("ix_enterprise_data_imports_source_type", ["source_type"], False),
        ("ix_enterprise_data_imports_as_of_date", ["as_of_date"], False),
        ("ix_enterprise_data_imports_payload_hash", ["payload_hash"], False),
        ("ix_enterprise_data_imports_status", ["status"], False),
        ("ix_enterprise_data_imports_created_by", ["created_by"], False),
        ("ix_enterprise_data_imports_created_at", ["created_at"], False),
        ("ix_enterprise_data_imports_counterparty_created", ["counterparty_id", "created_at"], False),
    ]:
        op.create_index(name, "enterprise_data_imports", columns, unique=unique)

    op.create_table(
        "enterprise_data_fields",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("import_id", sa.String(length=36), nullable=False),
        sa.Column("counterparty_id", sa.String(length=128), nullable=False),
        sa.Column("field_path", sa.String(length=512), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=False),
        sa.Column("value_hash", sa.String(length=64), nullable=False),
        sa.Column("value_type", sa.String(length=32), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("source_priority", sa.Integer(), nullable=False),
        sa.Column("evidence_reference", sa.Text(), nullable=False),
        sa.Column("evidence_locator", sa.String(length=512), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("freshness_days", sa.Integer(), nullable=False),
        sa.Column("freshness_status", sa.String(length=16), nullable=False),
        sa.Column("validation_status", sa.String(length=16), nullable=False),
        sa.Column("conflict_status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["import_id"], ["enterprise_data_imports.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("import_id", "field_path", name="uq_enterprise_data_field_import_path"),
    )
    for name, columns in [
        ("ix_enterprise_data_fields_import_id", ["import_id"]),
        ("ix_enterprise_data_fields_counterparty_id", ["counterparty_id"]),
        ("ix_enterprise_data_fields_field_path", ["field_path"]),
        ("ix_enterprise_data_fields_value_hash", ["value_hash"]),
        ("ix_enterprise_data_fields_source_type", ["source_type"]),
        ("ix_enterprise_data_fields_observed_at", ["observed_at"]),
        ("ix_enterprise_data_fields_freshness_status", ["freshness_status"]),
        ("ix_enterprise_data_fields_validation_status", ["validation_status"]),
        ("ix_enterprise_data_fields_conflict_status", ["conflict_status"]),
        ("ix_enterprise_data_fields_created_at", ["created_at"]),
        ("ix_enterprise_data_fields_counterparty_path", ["counterparty_id", "field_path", "observed_at"]),
    ]:
        op.create_index(name, "enterprise_data_fields", columns, unique=False)


def downgrade() -> None:
    op.drop_table("enterprise_data_fields")
    op.drop_table("enterprise_data_imports")
