"""Add tenant model-risk policies and acceptance register.

Revision ID: 20260922_0104
Revises: 20260922_0103
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260922_0104"
down_revision = "20260922_0103"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_model_risk_policies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("levels_json", sa.JSON(), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("change_reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_by_name", sa.String(128), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(128), nullable=True),
        sa.Column("reviewed_by_name", sa.String(128), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "version", name="uq_tenant_model_risk_policy_version"),
        sa.CheckConstraint("status IN ('draft', 'pending_review', 'published', 'rejected', 'retired')", name="ck_tenant_model_risk_policy_status"),
    )
    op.create_index("ix_tenant_model_risk_policy_tenant_id", "tenant_model_risk_policies", ["tenant_id"])
    op.create_index("ix_tenant_model_risk_policy_config_hash", "tenant_model_risk_policies", ["config_hash"])
    op.create_index("ix_tenant_model_risk_policy_status", "tenant_model_risk_policies", ["status"])
    op.create_index("ix_tenant_model_risk_policy_is_active", "tenant_model_risk_policies", ["is_active"])
    op.create_index("ix_tenant_model_risk_policy_created_by", "tenant_model_risk_policies", ["created_by"])
    op.create_index("ix_tenant_model_risk_policy_created_at", "tenant_model_risk_policies", ["created_at"])
    op.create_index("ix_tenant_model_risk_policy_tenant_status", "tenant_model_risk_policies", ["tenant_id", "status", "version"])
    op.create_index(
        "uq_tenant_model_risk_policy_active", "tenant_model_risk_policies", ["tenant_id"], unique=True,
        sqlite_where=sa.text("is_active = 1"), postgresql_where=sa.text("is_active IS TRUE"),
    )

    op.create_table(
        "model_risk_acceptances",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("model_change_id", sa.String(36), sa.ForeignKey("model_changes.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("policy_id", sa.String(36), sa.ForeignKey("tenant_model_risk_policies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("policy_config_hash", sa.String(64), nullable=False),
        sa.Column("evidence_binding_hash", sa.String(64), nullable=False),
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
        sa.CheckConstraint("risk_level IN ('low', 'medium', 'high')", name="ck_model_risk_acceptance_level"),
        sa.CheckConstraint("status IN ('pending', 'accepted', 'revoked')", name="ck_model_risk_acceptance_status"),
    )
    for column in ("tenant_id", "model_change_id", "policy_id", "policy_config_hash", "evidence_binding_hash", "risk_level", "status", "created_by", "accepted_at", "review_due_at", "created_at"):
        op.create_index(f"ix_model_risk_acceptances_{column}", "model_risk_acceptances", [column])
    op.create_index("ix_model_risk_acceptance_change_status", "model_risk_acceptances", ["tenant_id", "model_change_id", "status"])
    op.create_index(
        "uq_model_risk_acceptance_active_change", "model_risk_acceptances", ["tenant_id", "model_change_id"], unique=True,
        sqlite_where=sa.text("status IN ('pending', 'accepted')"), postgresql_where=sa.text("status IN ('pending', 'accepted')"),
    )


def downgrade() -> None:
    op.drop_table("model_risk_acceptances")
    op.drop_table("tenant_model_risk_policies")
