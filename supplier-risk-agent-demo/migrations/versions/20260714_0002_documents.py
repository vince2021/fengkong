"""Add document metadata table.

Revision ID: 20260714_0002
Revises: 20260714_0001
"""

from alembic import op
import sqlalchemy as sa


revision = "20260714_0002"
down_revision = "20260714_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("counterparty_id", sa.String(length=128), nullable=False),
        sa.Column("case_id", sa.String(length=128), nullable=True),
        sa.Column("document_type", sa.String(length=64), nullable=False),
        sa.Column("original_name", sa.String(length=512), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False, unique=True),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("uploaded_by", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_documents_case_id", "documents", ["case_id"])
    op.create_index("ix_documents_counterparty_id", "documents", ["counterparty_id"])
    op.create_index("ix_documents_counterparty_case", "documents", ["counterparty_id", "case_id", "created_at"])
    op.create_index("ix_documents_created_at", "documents", ["created_at"])
    op.create_index("ix_documents_document_type", "documents", ["document_type"])
    op.create_index("ix_documents_sha256", "documents", ["sha256"])
    op.create_index("ix_documents_status", "documents", ["status"])
    op.create_index("ix_documents_uploaded_by", "documents", ["uploaded_by"])


def downgrade() -> None:
    op.drop_table("documents")
