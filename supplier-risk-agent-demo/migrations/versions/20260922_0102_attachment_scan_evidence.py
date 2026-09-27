"""Persist attachment scan provenance and optimistic versioning.

Revision ID: 20260922_0102
Revises: 20260922_0101
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260922_0102"
down_revision = "20260922_0101"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("supervised_validation_attachments", sa.Column("scan_engine", sa.String(128), nullable=True))
    op.add_column("supervised_validation_attachments", sa.Column("scan_result_reason", sa.Text(), nullable=True))
    op.add_column("supervised_validation_attachments", sa.Column("scan_completed_by", sa.String(128), nullable=True))
    op.add_column("supervised_validation_attachments", sa.Column("scan_completed_by_name", sa.String(128), nullable=True))
    op.add_column("supervised_validation_attachments", sa.Column("scan_completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("supervised_validation_attachments", sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"))
    op.create_index("ix_supervised_validation_attachment_scan_engine", "supervised_validation_attachments", ["scan_engine"])
    op.create_index("ix_supervised_validation_attachment_scan_completed_at", "supervised_validation_attachments", ["scan_completed_at"])


def downgrade() -> None:
    op.drop_index("ix_supervised_validation_attachment_scan_completed_at", table_name="supervised_validation_attachments")
    op.drop_index("ix_supervised_validation_attachment_scan_engine", table_name="supervised_validation_attachments")
    op.drop_column("supervised_validation_attachments", "row_version")
    op.drop_column("supervised_validation_attachments", "scan_completed_at")
    op.drop_column("supervised_validation_attachments", "scan_completed_by_name")
    op.drop_column("supervised_validation_attachments", "scan_completed_by")
    op.drop_column("supervised_validation_attachments", "scan_result_reason")
    op.drop_column("supervised_validation_attachments", "scan_engine")
