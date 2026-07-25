"""Add credit facilities, utilization transactions, and post-credit alerts.

Revision ID: 20260714_0010
Revises: 20260714_0009
"""

from alembic import op
import sqlalchemy as sa


revision = "20260714_0010"
down_revision = "20260714_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credit_facilities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("case_id", sa.String(length=128), nullable=False),
        sa.Column("counterparty_id", sa.String(length=128), nullable=False),
        sa.Column("counterparty_name", sa.String(length=255), nullable=False),
        sa.Column("approved_limit", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("used_limit", sa.Numeric(precision=18, scale=2), nullable=False, server_default="0"),
        sa.Column("payment_term_days", sa.Integer(), nullable=False),
        sa.Column("rating", sa.String(length=32), nullable=False),
        sa.Column("access_strategy", sa.String(length=64), nullable=False),
        sa.Column("monitoring_frequency", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_review_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_review_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["case_id"], ["approval_cases.case_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", name="uq_credit_facility_case"),
    )
    for column in ["case_id", "counterparty_id", "rating", "status", "effective_at", "expires_at", "next_review_at", "created_at"]:
        op.create_index(f"ix_credit_facilities_{column}", "credit_facilities", [column])
    op.create_index("ix_credit_facilities_status_expiry", "credit_facilities", ["status", "expires_at"])

    op.create_table(
        "credit_usage_transactions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("facility_id", sa.String(length=36), nullable=False),
        sa.Column("transaction_ref", sa.String(length=128), nullable=False),
        sa.Column("transaction_type", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("balance_after", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["facility_id"], ["credit_facilities.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ["facility_id", "transaction_ref", "transaction_type", "occurred_at"]:
        op.create_index(f"ix_credit_usage_transactions_{column}", "credit_usage_transactions", [column], unique=column == "transaction_ref")
    op.create_index("ix_credit_usage_facility_occurred", "credit_usage_transactions", ["facility_id", "occurred_at"])

    op.create_table(
        "facility_alerts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("facility_id", sa.String(length=36), nullable=False),
        sa.Column("alert_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("dedup_key", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(length=128), nullable=True),
        sa.ForeignKeyConstraint(["facility_id"], ["credit_facilities.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedup_key", name="uq_facility_alert_dedup"),
    )
    for column in ["facility_id", "alert_type", "severity", "status", "created_at"]:
        op.create_index(f"ix_facility_alerts_{column}", "facility_alerts", [column])
    op.create_index("ix_facility_alerts_status_severity_created", "facility_alerts", ["status", "severity", "created_at"])


def downgrade() -> None:
    op.drop_table("facility_alerts")
    op.drop_table("credit_usage_transactions")
    op.drop_table("credit_facilities")
