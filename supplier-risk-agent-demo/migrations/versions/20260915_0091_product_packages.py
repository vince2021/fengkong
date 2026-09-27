"""add governed product packages and tenant entitlement ledger

Revision ID: 20260915_0091
Revises: 20260915_0090
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260915_0091"
down_revision = "20260915_0090"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_packages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("environment_scopes_json", sa.JSON(), nullable=False),
        sa.Column("asset_catalog_json", sa.JSON(), nullable=False),
        sa.Column("quotas_json", sa.JSON(), nullable=False),
        sa.Column("expiry_policy", sa.String(length=32), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_by_name", sa.String(length=128), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(length=128), nullable=True),
        sa.Column("reviewed_by_name", sa.String(length=128), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("status IN ('draft', 'pending_review', 'published', 'rejected', 'retired')", name="ck_product_package_status"),
        sa.CheckConstraint("expiry_policy = 'block'", name="ck_product_package_expiry_policy"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", "version", name="uq_product_package_code_version"),
    )
    op.create_index("ix_product_packages_code", "product_packages", ["code"])
    op.create_index("ix_product_packages_status", "product_packages", ["status"])
    op.create_index("ix_product_packages_is_active", "product_packages", ["is_active"])
    op.create_index("ix_product_packages_config_hash", "product_packages", ["config_hash"])
    op.create_index("ix_product_package_code_status", "product_packages", ["code", "status", "version"])
    op.create_index(
        "uq_product_package_one_active", "product_packages", ["code"], unique=True,
        sqlite_where=sa.text("is_active = 1"), postgresql_where=sa.text("is_active IS TRUE"),
    )

    op.create_table(
        "tenant_entitlements",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("product_package_id", sa.String(length=36), nullable=False),
        sa.Column("package_code", sa.String(length=128), nullable=False),
        sa.Column("package_version", sa.Integer(), nullable=False),
        sa.Column("package_config_hash", sa.String(length=64), nullable=False),
        sa.Column("package_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("effective_quotas_json", sa.JSON(), nullable=False),
        sa.Column("initialized_assets_json", sa.JSON(), nullable=False),
        sa.Column("activation_hash", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_by_name", sa.String(length=128), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(length=128), nullable=True),
        sa.Column("reviewed_by_name", sa.String(length=128), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("status IN ('draft', 'pending_review', 'scheduled', 'active', 'suspended', 'expired', 'terminated')", name="ck_tenant_entitlement_status"),
        sa.CheckConstraint("expires_at > starts_at", name="ck_tenant_entitlement_window"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_package_id"], ["product_packages.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tenant_entitlements_tenant_id", "tenant_entitlements", ["tenant_id"])
    op.create_index("ix_tenant_entitlements_product_package_id", "tenant_entitlements", ["product_package_id"])
    op.create_index("ix_tenant_entitlements_package_code", "tenant_entitlements", ["package_code"])
    op.create_index("ix_tenant_entitlements_activation_hash", "tenant_entitlements", ["activation_hash"])
    op.create_index("ix_tenant_entitlements_status", "tenant_entitlements", ["status"])
    op.create_index("ix_tenant_entitlements_starts_at", "tenant_entitlements", ["starts_at"])
    op.create_index("ix_tenant_entitlements_expires_at", "tenant_entitlements", ["expires_at"])
    op.create_index("ix_tenant_entitlement_tenant_status", "tenant_entitlements", ["tenant_id", "status", "starts_at", "expires_at"])
    op.create_index(
        "uq_tenant_entitlement_one_active", "tenant_entitlements", ["tenant_id"], unique=True,
        sqlite_where=sa.text("status = 'active'"), postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_table("tenant_entitlements")
    op.drop_table("product_packages")
