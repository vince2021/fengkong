"""Add reviewed enterprise indicator observations.

Revision ID: 20260720_0026
Revises: 20260720_0025
"""

from alembic import op
import sqlalchemy as sa


revision = "20260720_0026"
down_revision = "20260720_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "enterprise_indicator_observations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("counterparty_id", sa.String(length=128), nullable=False),
        sa.Column("indicator_id", sa.String(length=128), nullable=False),
        sa.Column("indicator_name", sa.String(length=255), nullable=False),
        sa.Column("values_json", sa.JSON(), nullable=False),
        sa.Column("values_hash", sa.String(length=64), nullable=False),
        sa.Column("evidence_document_id", sa.String(length=36), sa.ForeignKey("documents.id"), nullable=True),
        sa.Column("evidence_reference", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending_review", nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_by_name", sa.String(length=128), nullable=False),
        sa.Column("reviewed_by", sa.String(length=128), nullable=True),
        sa.Column("reviewed_by_name", sa.String(length=128), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("row_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    for name, columns in [
        ("ix_enterprise_indicator_observations_counterparty_id", ["counterparty_id"]),
        ("ix_enterprise_indicator_observations_indicator_id", ["indicator_id"]),
        ("ix_enterprise_indicator_observations_values_hash", ["values_hash"]),
        ("ix_enterprise_indicator_observations_evidence_document_id", ["evidence_document_id"]),
        ("ix_enterprise_indicator_observations_observed_at", ["observed_at"]),
        ("ix_enterprise_indicator_observations_status", ["status"]),
        ("ix_enterprise_indicator_observations_created_by", ["created_by"]),
        ("ix_enterprise_indicator_observations_reviewed_by", ["reviewed_by"]),
        ("ix_enterprise_indicator_observations_reviewed_at", ["reviewed_at"]),
        ("ix_enterprise_indicator_observations_created_at", ["created_at"]),
        ("ix_indicator_observations_counterparty_indicator", ["counterparty_id", "indicator_id", "created_at"]),
    ]:
        op.create_index(name, "enterprise_indicator_observations", columns, unique=False)
    op.create_index(
        "uq_indicator_observations_pending",
        "enterprise_indicator_observations",
        ["counterparty_id", "indicator_id"],
        unique=True,
        sqlite_where=sa.text("status = 'pending_review'"),
        postgresql_where=sa.text("status = 'pending_review'"),
    )


def downgrade() -> None:
    op.drop_table("enterprise_indicator_observations")
