"""Add sealed credit decision reports.

Revision ID: 20260716_0019
Revises: 20260716_0018
"""

from alembic import op
import sqlalchemy as sa


revision = "20260716_0019"
down_revision = "20260716_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credit_reports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("report_no", sa.String(length=128), nullable=False),
        sa.Column("case_id", sa.String(length=128), nullable=False),
        sa.Column("counterparty_id", sa.String(length=128), nullable=False),
        sa.Column("report_version", sa.Integer(), nullable=False),
        sa.Column("report_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("pdf_sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["approval_cases.case_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "report_version", name="uq_credit_report_case_version"),
        sa.UniqueConstraint("case_id", "snapshot_hash", name="uq_credit_report_case_snapshot"),
        sa.UniqueConstraint("object_key"),
    )
    op.create_index("ix_credit_reports_report_no", "credit_reports", ["report_no"], unique=True)
    op.create_index("ix_credit_reports_case_id", "credit_reports", ["case_id"], unique=False)
    op.create_index("ix_credit_reports_counterparty_id", "credit_reports", ["counterparty_id"], unique=False)
    op.create_index("ix_credit_reports_report_type", "credit_reports", ["report_type"], unique=False)
    op.create_index("ix_credit_reports_status", "credit_reports", ["status"], unique=False)
    op.create_index("ix_credit_reports_snapshot_hash", "credit_reports", ["snapshot_hash"], unique=False)
    op.create_index("ix_credit_reports_pdf_sha256", "credit_reports", ["pdf_sha256"], unique=False)
    op.create_index("ix_credit_reports_created_by", "credit_reports", ["created_by"], unique=False)
    op.create_index("ix_credit_reports_created_at", "credit_reports", ["created_at"], unique=False)
    op.create_index("ix_credit_reports_case_version", "credit_reports", ["case_id", "report_version"], unique=False)


def downgrade() -> None:
    op.drop_table("credit_reports")
