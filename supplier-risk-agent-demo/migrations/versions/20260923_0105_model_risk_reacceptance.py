"""Add in-service model risk reacceptance register.

Revision ID: 20260923_0105
Revises: 20260922_0104
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260923_0105"
down_revision = "20260922_0104"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_risk_reacceptances",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("model_release_id", sa.String(36), sa.ForeignKey("model_releases.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("model_change_id", sa.String(36), sa.ForeignKey("model_changes.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("prior_acceptance_id", sa.String(36), sa.ForeignKey("model_risk_acceptances.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("policy_id", sa.String(36), sa.ForeignKey("tenant_model_risk_policies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("policy_config_hash", sa.String(64), nullable=False),
        sa.Column("source_evidence_binding_hash", sa.String(64), nullable=False),
        sa.Column("release_config_hash", sa.String(64), nullable=False),
        sa.Column("operational_evidence_json", sa.JSON(), nullable=False),
        sa.Column("operational_evidence_hash", sa.String(64), nullable=False),
        sa.Column("risk_level", sa.String(16), nullable=False),
        sa.Column("required_roles_json", sa.JSON(), nullable=False),
        sa.Column("approvals_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_by_name", sa.String(128), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.String(128), nullable=True),
        sa.Column("revoked_by_name", sa.String(128), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.Text(), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("risk_level IN ('low', 'medium', 'high')", name="ck_model_risk_reacceptance_level"),
        sa.CheckConstraint("status IN ('pending', 'accepted', 'revoked')", name="ck_model_risk_reacceptance_status"),
    )
    for column in ("tenant_id", "model_release_id", "model_change_id", "prior_acceptance_id", "policy_id", "policy_config_hash", "source_evidence_binding_hash", "release_config_hash", "operational_evidence_hash", "risk_level", "status", "created_by", "accepted_at", "review_due_at", "created_at"):
        op.create_index(f"ix_model_risk_reacceptances_{column}", "model_risk_reacceptances", [column])
    op.create_index("ix_model_risk_reacceptance_release_status", "model_risk_reacceptances", ["tenant_id", "model_release_id", "status"])
    op.create_index("uq_model_risk_reacceptance_active_release", "model_risk_reacceptances", ["tenant_id", "model_release_id"], unique=True,
                    sqlite_where=sa.text("status IN ('pending', 'accepted')"), postgresql_where=sa.text("status IN ('pending', 'accepted')"))


def downgrade() -> None:
    op.drop_table("model_risk_reacceptances")
