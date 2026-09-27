"""add tenant-scoped counterparty import mapping templates

Revision ID: 20260907_0081
Revises: 20260907_0080
"""
from alembic import op
import sqlalchemy as sa


revision = "20260907_0081"
down_revision = "20260907_0080"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "counterparty_import_mapping_templates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("template_key", sa.String(128), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("file_format", sa.String(16), nullable=False),
        sa.Column("mapping_json", sa.JSON(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("updated_by", sa.String(128), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("file_format IN ('json', 'csv')", name="ck_counterparty_import_mapping_file_format"),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_counterparty_import_mapping_status"),
        sa.UniqueConstraint("tenant_id", "template_key", name="uq_counterparty_import_mapping_tenant_key"),
    )
    for column in ("tenant_id", "template_key", "file_format", "status", "created_by", "updated_by"):
        op.create_index(
            f"ix_counterparty_import_mapping_templates_{column}",
            "counterparty_import_mapping_templates",
            [column],
        )
    op.create_index(
        "ix_counterparty_import_mapping_tenant_status_updated",
        "counterparty_import_mapping_templates",
        ["tenant_id", "status", "updated_at"],
    )


def downgrade() -> None:
    op.drop_table("counterparty_import_mapping_templates")
