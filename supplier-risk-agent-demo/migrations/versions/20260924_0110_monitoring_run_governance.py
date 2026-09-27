"""Add governed publication lifecycle to tenant monitoring snapshots.

Revision ID: 20260924_0110
Revises: 20260924_0109
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260924_0110"
down_revision = "20260924_0109"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tenant_monitoring_runs") as batch:
        batch.add_column(sa.Column("governance_status", sa.String(32), nullable=False, server_default="published"))
        batch.add_column(sa.Column("submitted_by", sa.String(128), nullable=True))
        batch.add_column(sa.Column("submitted_by_name", sa.String(128), nullable=True))
        batch.add_column(sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("reviewed_by", sa.String(128), nullable=True))
        batch.add_column(sa.Column("reviewed_by_name", sa.String(128), nullable=True))
        batch.add_column(sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("review_comment", sa.Text(), nullable=True))
        batch.add_column(sa.Column("retracted_by", sa.String(128), nullable=True))
        batch.add_column(sa.Column("retracted_by_name", sa.String(128), nullable=True))
        batch.add_column(sa.Column("retracted_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("retraction_reason", sa.Text(), nullable=True))
        batch.add_column(sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"))
        batch.create_check_constraint(
            "ck_tenant_monitoring_run_governance_status",
            "governance_status IN ('draft', 'pending_review', 'published', 'rejected', 'retracted')",
        )
    op.create_index("ix_tenant_monitoring_runs_governance_status", "tenant_monitoring_runs", ["governance_status"])


def downgrade() -> None:
    op.drop_index("ix_tenant_monitoring_runs_governance_status", table_name="tenant_monitoring_runs")
    with op.batch_alter_table("tenant_monitoring_runs") as batch:
        batch.drop_constraint("ck_tenant_monitoring_run_governance_status", type_="check")
        for column in (
            "row_version", "retraction_reason", "retracted_at", "retracted_by_name", "retracted_by",
            "review_comment", "reviewed_at", "reviewed_by_name", "reviewed_by", "submitted_at",
            "submitted_by_name", "submitted_by", "governance_status",
        ):
            batch.drop_column(column)
