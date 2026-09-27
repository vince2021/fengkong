"""Add governed model validation report issuance records.

Revision ID: 20260922_0101
Revises: 20260922_0100
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260922_0101"
down_revision = "20260922_0100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_validation_report_issuances",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("model_change_id", sa.String(36), sa.ForeignKey("model_changes.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("report_template_version", sa.String(64), nullable=False),
        sa.Column("report_hash", sa.String(64), nullable=False),
        sa.Column("evidence_binding_hash", sa.String(64), nullable=False),
        sa.Column("package_json", sa.JSON(), nullable=False),
        sa.Column("package_hash", sa.String(64), nullable=False),
        sa.Column("signature_algorithm", sa.String(64), nullable=False, server_default="SHA-256-CANONICAL-JSON"),
        sa.Column("signature", sa.String(64), nullable=False),
        sa.Column("issued_by", sa.String(128), nullable=False),
        sa.Column("issued_by_name", sa.String(128), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_by", sa.String(128), nullable=True),
        sa.Column("revoked_by_name", sa.String(128), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.Text(), nullable=True),
        sa.Column("supersedes_issuance_id", sa.String(36), sa.ForeignKey("model_validation_report_issuances.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("reissue_reason", sa.Text(), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("signature", name="uq_model_validation_issuance_signature"),
        sa.UniqueConstraint("supersedes_issuance_id", name="uq_model_validation_issuance_supersedes"),
    )
    op.create_index("ix_model_validation_issuance_tenant_id", "model_validation_report_issuances", ["tenant_id"])
    op.create_index("ix_model_validation_issuance_change_issued", "model_validation_report_issuances", ["model_change_id", "issued_at"])
    op.create_index("ix_model_validation_issuance_report_hash", "model_validation_report_issuances", ["report_hash"])
    op.create_index("ix_model_validation_issuance_evidence_binding_hash", "model_validation_report_issuances", ["evidence_binding_hash"])
    op.create_index("ix_model_validation_issuance_package_hash", "model_validation_report_issuances", ["package_hash"])
    op.create_index("ix_model_validation_issuance_issued_by", "model_validation_report_issuances", ["issued_by"])
    op.create_index("ix_model_validation_issuance_issued_at", "model_validation_report_issuances", ["issued_at"])
    op.create_index("ix_model_validation_issuance_revoked_by", "model_validation_report_issuances", ["revoked_by"])
    op.create_index("ix_model_validation_issuance_revoked_at", "model_validation_report_issuances", ["revoked_at"])
    op.create_index("ix_model_validation_issuance_supersedes", "model_validation_report_issuances", ["supersedes_issuance_id"])
    op.create_index(
        "uq_model_validation_issuance_active_change_report",
        "model_validation_report_issuances", ["model_change_id", "report_hash"], unique=True,
        sqlite_where=sa.text("revoked_at IS NULL"), postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("model_validation_report_issuances")
