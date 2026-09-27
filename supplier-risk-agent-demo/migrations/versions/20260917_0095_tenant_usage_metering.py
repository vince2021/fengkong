"""Add tenant usage metering ledger and monthly reconciliation snapshots.

Revision ID: 20260917_0095
Revises: 20260916_0094
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260917_0095"
down_revision = "20260916_0094"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_usage_daily_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("usage_json", sa.JSON(), nullable=False),
        sa.Column("source_watermark_json", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.UniqueConstraint("tenant_id", "usage_date", name="uq_tenant_usage_daily_tenant_date"),
    )
    op.create_index("ix_tenant_usage_daily_records_tenant_id", "tenant_usage_daily_records", ["tenant_id"])
    op.create_index("ix_tenant_usage_daily_records_usage_date", "tenant_usage_daily_records", ["usage_date"])
    op.create_index("ix_tenant_usage_daily_records_evidence_hash", "tenant_usage_daily_records", ["evidence_hash"])
    op.create_index("ix_tenant_usage_daily_records_computed_at", "tenant_usage_daily_records", ["computed_at"])
    op.create_index("ix_tenant_usage_daily_tenant_date", "tenant_usage_daily_records", ["tenant_id", "usage_date"])
    op.create_table(
        "tenant_usage_statements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("billing_month", sa.Date(), nullable=False),
        sa.Column("statement_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("statement_json", sa.JSON(), nullable=False),
        sa.Column("statement_hash", sa.String(64), nullable=False),
        sa.Column("generated_by", sa.String(128), nullable=False),
        sa.Column("generated_by_name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("status = 'generated'", name="ck_tenant_usage_statement_status"),
        sa.UniqueConstraint("tenant_id", "billing_month", "statement_version", name="uq_tenant_usage_statement_version"),
    )
    op.create_index("ix_tenant_usage_statements_tenant_id", "tenant_usage_statements", ["tenant_id"])
    op.create_index("ix_tenant_usage_statements_billing_month", "tenant_usage_statements", ["billing_month"])
    op.create_index("ix_tenant_usage_statements_statement_hash", "tenant_usage_statements", ["statement_hash"])
    op.create_index("ix_tenant_usage_statements_created_at", "tenant_usage_statements", ["created_at"])
    op.create_index("ix_tenant_usage_statement_tenant_month", "tenant_usage_statements", ["tenant_id", "billing_month", "statement_version"])


def downgrade() -> None:
    op.drop_table("tenant_usage_statements")
    op.drop_table("tenant_usage_daily_records")
