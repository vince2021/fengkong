"""add two-phase counterparty import batches

Revision ID: 20260907_0080
Revises: 20260907_0079
"""
from alembic import op
import sqlalchemy as sa


revision = "20260907_0080"
down_revision = "20260907_0079"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "counterparty_import_batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("import_key", sa.String(128), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_format", sa.String(16), nullable=False),
        sa.Column("duplicate_strategy", sa.String(16), nullable=False),
        sa.Column("field_mapping_json", sa.JSON(), nullable=False),
        sa.Column("source_content", sa.Text(), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("preview_hash", sa.String(64), nullable=False),
        sa.Column("normalized_rows_json", sa.JSON(), nullable=False),
        sa.Column("row_receipts_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("valid_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invalid_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("create_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("update_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skip_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("committed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("precheck_reason", sa.Text(), nullable=False),
        sa.Column("commit_reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_by_name", sa.String(128), nullable=False),
        sa.Column("committed_by", sa.String(128), nullable=True),
        sa.Column("committed_by_name", sa.String(128), nullable=True),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("file_format IN ('json', 'csv')", name="ck_counterparty_import_file_format"),
        sa.CheckConstraint("duplicate_strategy IN ('reject', 'skip', 'update')", name="ck_counterparty_import_duplicate_strategy"),
        sa.CheckConstraint("status IN ('prechecked', 'blocked', 'committed')", name="ck_counterparty_import_status"),
        sa.CheckConstraint("total_count >= 0", name="ck_counterparty_import_total_nonnegative"),
        sa.CheckConstraint("valid_count >= 0 AND invalid_count >= 0", name="ck_counterparty_import_validation_counts_nonnegative"),
        sa.UniqueConstraint("tenant_id", "import_key", name="uq_counterparty_import_tenant_key"),
    )
    for column in (
        "tenant_id", "import_key", "file_format", "duplicate_strategy", "source_hash", "request_hash",
        "preview_hash", "status", "created_by", "committed_by",
    ):
        op.create_index(f"ix_counterparty_import_batches_{column}", "counterparty_import_batches", [column])
    op.create_index(
        "ix_counterparty_import_tenant_status_created", "counterparty_import_batches", ["tenant_id", "status", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("counterparty_import_batches")
