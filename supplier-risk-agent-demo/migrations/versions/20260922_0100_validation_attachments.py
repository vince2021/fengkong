"""Persist supervised validation attachment metadata and audit boundaries.

Revision ID: 20260922_0100
Revises: 20260921_0099
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260922_0100"
down_revision = "20260921_0099"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "supervised_validation_attachments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("model_change_id", sa.String(36), sa.ForeignKey("model_changes.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("scan_status", sa.String(32), nullable=False, server_default="not_scanned"),
        sa.Column("uploaded_by", sa.String(128), nullable=False),
        sa.Column("uploaded_by_name", sa.String(128), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("revoked_by", sa.String(128), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('active', 'revoked')", name="ck_supervised_validation_attachment_status"),
        sa.CheckConstraint("scan_status IN ('not_scanned', 'pending', 'passed', 'rejected')", name="ck_supervised_validation_attachment_scan_status"),
        sa.CheckConstraint("size_bytes > 0", name="ck_supervised_validation_attachment_size"),
        sa.UniqueConstraint("model_change_id", "sha256", name="uq_supervised_validation_attachment_hash"),
    )
    op.create_index("ix_supervised_validation_attachment_tenant_id", "supervised_validation_attachments", ["tenant_id"])
    op.create_index("ix_supervised_validation_attachment_change_status", "supervised_validation_attachments", ["model_change_id", "status"])
    op.create_index("ix_supervised_validation_attachment_sha256", "supervised_validation_attachments", ["sha256"])


def downgrade() -> None:
    op.drop_index("ix_supervised_validation_attachment_sha256", table_name="supervised_validation_attachments")
    op.drop_index("ix_supervised_validation_attachment_change_status", table_name="supervised_validation_attachments")
    op.drop_index("ix_supervised_validation_attachment_tenant_id", table_name="supervised_validation_attachments")
    op.drop_table("supervised_validation_attachments")
