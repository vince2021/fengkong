"""Add document correction tasks and replacement version chains.

Revision ID: 20260721_0028
Revises: 20260721_0027
"""

from alembic import op
import sqlalchemy as sa


revision = "20260721_0028"
down_revision = "20260721_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "document_corrections" in inspector.get_table_names():
        return
    op.create_table(
        "document_corrections",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("counterparty_id", sa.String(length=128), nullable=False),
        sa.Column("case_id", sa.String(length=128), nullable=True),
        sa.Column("document_type", sa.String(length=64), nullable=False),
        sa.Column("original_document_id", sa.String(length=36), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("current_document_id", sa.String(length=36), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("version_document_ids_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'open'")),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("failed_check_keys_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("requested_by", sa.String(length=128), nullable=False),
        sa.Column("requested_by_name", sa.String(length=128), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_by", sa.String(length=128), nullable=True),
        sa.Column("resolved_by_name", sa.String(length=128), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    for name, columns in [
        ("ix_document_corrections_counterparty_id", ["counterparty_id"]),
        ("ix_document_corrections_case_id", ["case_id"]),
        ("ix_document_corrections_document_type", ["document_type"]),
        ("ix_document_corrections_original_document_id", ["original_document_id"]),
        ("ix_document_corrections_current_document_id", ["current_document_id"]),
        ("ix_document_corrections_status", ["status"]),
        ("ix_document_corrections_requested_by", ["requested_by"]),
        ("ix_document_corrections_created_at", ["created_at"]),
        ("ix_document_corrections_scope_status", ["counterparty_id", "case_id", "status", "created_at"]),
    ]:
        op.create_index(name, "document_corrections", columns, unique=False)


def downgrade() -> None:
    op.drop_table("document_corrections")
