"""add tenant-scoped counterparty master data

Revision ID: 20260907_0079
Revises: 20260907_0078
"""
from alembic import op
import sqlalchemy as sa


revision = "20260907_0079"
down_revision = "20260907_0078"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "counterparties",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("counterparty_id", sa.String(128), nullable=False),
        sa.Column("credit_code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("counterparty_type", sa.String(32), nullable=False),
        sa.Column("industry", sa.String(128), nullable=False),
        sa.Column("cooperation_status", sa.String(64), nullable=False, server_default="pending"),
        sa.Column("is_key_counterparty", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("requested_limit", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("current_limit", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("current_payment_term_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_rating", sa.String(32), nullable=True),
        sa.Column("current_segment", sa.String(128), nullable=True),
        sa.Column("external_json", sa.JSON(), nullable=False),
        sa.Column("internal_json", sa.JSON(), nullable=False),
        sa.Column("financial_json", sa.JSON(), nullable=False),
        sa.Column("extensions_json", sa.JSON(), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("source_type", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_by", sa.String(128), nullable=True),
        sa.Column("archive_reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("updated_by", sa.String(128), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("counterparty_type IN ('supplier', 'customer')", name="ck_counterparty_type"),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_counterparty_status"),
        sa.CheckConstraint("requested_limit >= 0", name="ck_counterparty_requested_limit_nonnegative"),
        sa.CheckConstraint("current_limit >= 0", name="ck_counterparty_current_limit_nonnegative"),
        sa.CheckConstraint("current_payment_term_days >= 0", name="ck_counterparty_payment_term_nonnegative"),
        sa.UniqueConstraint("tenant_id", "counterparty_id", name="uq_counterparty_tenant_business_id"),
        sa.UniqueConstraint("tenant_id", "credit_code", name="uq_counterparty_tenant_credit_code"),
    )
    for column in (
        "tenant_id", "counterparty_id", "credit_code", "name", "counterparty_type", "industry",
        "cooperation_status", "current_rating", "profile_hash", "status", "source_type",
    ):
        op.create_index(f"ix_counterparties_{column}", "counterparties", [column])
    op.create_index("ix_counterparty_tenant_status_updated", "counterparties", ["tenant_id", "status", "updated_at"])
    op.create_index("ix_counterparty_tenant_type_name", "counterparties", ["tenant_id", "counterparty_type", "name"])


def downgrade() -> None:
    op.drop_table("counterparties")
