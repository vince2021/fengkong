"""add tenant asset catalog and governed override versions

Revision ID: 20260908_0088
Revises: 20260908_0087
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260908_0088"
down_revision = "20260908_0087"
branch_labels = None
depends_on = None


ASSET_TYPES = "'indicator', 'scorecard', 'model', 'rule', 'rule_set', 'pipeline'"


def upgrade() -> None:
    op.create_table(
        "tenant_asset_bindings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("asset_type", sa.String(length=32), nullable=False),
        sa.Column("asset_code", sa.String(length=128), nullable=False),
        sa.Column("binding_mode", sa.String(length=32), nullable=False),
        sa.Column("pinned_version", sa.String(length=128), nullable=True),
        sa.Column("allow_tenant_override", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("resolved_scope", sa.String(length=32), nullable=True),
        sa.Column("resolved_asset_id", sa.String(length=36), nullable=True),
        sa.Column("resolved_version", sa.String(length=128), nullable=True),
        sa.Column("resolved_config_hash", sa.String(length=64), nullable=True),
        sa.Column("change_reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_by_name", sa.String(length=128), nullable=False),
        sa.Column("updated_by", sa.String(length=128), nullable=False),
        sa.Column("updated_by_name", sa.String(length=128), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint(f"asset_type IN ({ASSET_TYPES})", name="ck_tenant_asset_binding_type"),
        sa.CheckConstraint("binding_mode IN ('inherit_active', 'pinned')", name="ck_tenant_asset_binding_mode"),
        sa.CheckConstraint("status IN ('active', 'suspended')", name="ck_tenant_asset_binding_status"),
        sa.CheckConstraint(
            "(binding_mode = 'pinned' AND pinned_version IS NOT NULL) "
            "OR (binding_mode = 'inherit_active' AND pinned_version IS NULL)",
            name="ck_tenant_asset_binding_pin",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "asset_type", "asset_code", name="uq_tenant_asset_binding"),
    )
    op.create_index("ix_tenant_asset_bindings_tenant_id", "tenant_asset_bindings", ["tenant_id"])
    op.create_index("ix_tenant_asset_bindings_asset_type", "tenant_asset_bindings", ["asset_type"])
    op.create_index("ix_tenant_asset_bindings_asset_code", "tenant_asset_bindings", ["asset_code"])
    op.create_index("ix_tenant_asset_bindings_status", "tenant_asset_bindings", ["status"])
    op.create_index("ix_tenant_asset_binding_tenant_status", "tenant_asset_bindings", ["tenant_id", "status", "asset_type"])

    op.create_table(
        "tenant_asset_overrides",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("asset_type", sa.String(length=32), nullable=False),
        sa.Column("asset_code", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("base_asset_id", sa.String(length=36), nullable=False),
        sa.Column("base_version", sa.String(length=128), nullable=False),
        sa.Column("base_config_hash", sa.String(length=64), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
        sa.CheckConstraint(f"asset_type IN ({ASSET_TYPES})", name="ck_tenant_asset_override_type"),
        sa.CheckConstraint(
            "status IN ('draft', 'pending_review', 'published', 'rejected', 'retired')",
            name="ck_tenant_asset_override_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "asset_type", "asset_code", "version", name="uq_tenant_asset_override_version"),
    )
    op.create_index("ix_tenant_asset_overrides_tenant_id", "tenant_asset_overrides", ["tenant_id"])
    op.create_index("ix_tenant_asset_overrides_asset_type", "tenant_asset_overrides", ["asset_type"])
    op.create_index("ix_tenant_asset_overrides_asset_code", "tenant_asset_overrides", ["asset_code"])
    op.create_index("ix_tenant_asset_overrides_config_hash", "tenant_asset_overrides", ["config_hash"])
    op.create_index("ix_tenant_asset_overrides_status", "tenant_asset_overrides", ["status"])
    op.create_index("ix_tenant_asset_overrides_is_active", "tenant_asset_overrides", ["is_active"])
    op.create_index("ix_tenant_asset_override_tenant_status", "tenant_asset_overrides", ["tenant_id", "status", "asset_type"])
    op.create_index(
        "uq_tenant_asset_override_one_active",
        "tenant_asset_overrides",
        ["tenant_id", "asset_type", "asset_code"],
        unique=True,
        sqlite_where=sa.text("is_active = 1"),
        postgresql_where=sa.text("is_active IS TRUE"),
    )

def downgrade() -> None:
    op.drop_table("tenant_asset_overrides")
    op.drop_table("tenant_asset_bindings")
