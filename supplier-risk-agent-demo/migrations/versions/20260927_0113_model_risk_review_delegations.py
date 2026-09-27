"""Add model-risk review responsibility delegations.

Revision ID: 20260927_0113
Revises: 20260926_0112
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260927_0113"
down_revision = "20260926_0112"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_risk_review_delegations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("principal_subject", sa.String(128), nullable=False),
        sa.Column("principal_name", sa.String(255), nullable=False),
        sa.Column("delegate_subject", sa.String(128), nullable=False),
        sa.Column("delegate_name", sa.String(255), nullable=False),
        sa.Column("assigned_role", sa.String(64), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_by_name", sa.String(255), nullable=False),
        sa.Column("revoked_by", sa.String(128), nullable=True),
        sa.Column("revoked_by_name", sa.String(255), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.Text(), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('active', 'revoked')", name="ck_model_risk_review_delegation_status"),
        sa.CheckConstraint("principal_subject <> delegate_subject", name="ck_model_risk_review_delegation_distinct_members"),
        sa.CheckConstraint("ends_at > starts_at", name="ck_model_risk_review_delegation_window"),
    )
    for column in ("tenant_id", "principal_subject", "delegate_subject", "assigned_role", "starts_at", "ends_at", "status"):
        op.create_index(f"ix_model_risk_review_delegations_{column}", "model_risk_review_delegations", [column])
    op.create_index(
        "ix_model_risk_review_delegation_principal_window", "model_risk_review_delegations",
        ["tenant_id", "principal_subject", "assigned_role", "status", "starts_at", "ends_at"],
    )
    op.create_index(
        "ix_model_risk_review_delegation_delegate_window", "model_risk_review_delegations",
        ["tenant_id", "delegate_subject", "status", "starts_at", "ends_at"],
    )


def downgrade() -> None:
    op.drop_table("model_risk_review_delegations")
