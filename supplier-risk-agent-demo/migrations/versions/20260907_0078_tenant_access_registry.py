"""add persistent tenant access registry

Revision ID: 20260907_0078
Revises: 20260907_0077
"""
from alembic import op
import sqlalchemy as sa


revision = "20260907_0078"
down_revision = "20260907_0077"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("deployment_mode", sa.String(32), nullable=False, server_default="saas"),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("data_region", sa.String(64), nullable=False, server_default="cn"),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("deployment_mode IN ('saas', 'dedicated')", name="ck_tenant_deployment_mode"),
        sa.CheckConstraint("status IN ('active', 'suspended', 'disabled')", name="ck_tenant_status"),
    )
    op.create_index("ix_tenants_deployment_mode", "tenants", ["deployment_mode"])
    op.create_index("ix_tenants_status", "tenants", ["status"])

    op.create_table(
        "tenant_memberships",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("roles_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('active', 'suspended', 'revoked')", name="ck_tenant_membership_status"),
        sa.UniqueConstraint("tenant_id", "subject", name="uq_tenant_membership_subject"),
    )
    op.create_index("ix_tenant_memberships_tenant_id", "tenant_memberships", ["tenant_id"])
    op.create_index("ix_tenant_memberships_subject", "tenant_memberships", ["subject"])
    op.create_index("ix_tenant_memberships_status", "tenant_memberships", ["status"])
    op.create_index("ix_tenant_memberships_expires_at", "tenant_memberships", ["expires_at"])
    op.create_index("ix_tenant_membership_tenant_status", "tenant_memberships", ["tenant_id", "status"])

    op.create_table(
        "api_clients",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", sa.String(128), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("key_id", sa.String(128), nullable=False),
        sa.Column("key_fingerprint", sa.String(255), nullable=False),
        sa.Column("secret_reference", sa.String(256), nullable=True),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("qps_limit", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("concurrent_job_limit", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("daily_item_quota", sa.Integer(), nullable=False, server_default="10000"),
        sa.Column("allowed_cidrs_json", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('active', 'disabled', 'revoked')", name="ck_api_client_status"),
        sa.CheckConstraint("qps_limit > 0", name="ck_api_client_qps_positive"),
        sa.CheckConstraint("concurrent_job_limit > 0", name="ck_api_client_concurrency_positive"),
        sa.CheckConstraint("daily_item_quota > 0", name="ck_api_client_daily_quota_positive"),
        sa.UniqueConstraint("tenant_id", "client_id", name="uq_api_client_tenant_client"),
    )
    op.create_index("ix_api_clients_tenant_id", "api_clients", ["tenant_id"])
    op.create_index("ix_api_clients_client_id", "api_clients", ["client_id"])
    op.create_index("ix_api_clients_status", "api_clients", ["status"])
    op.create_index("ix_api_clients_expires_at", "api_clients", ["expires_at"])
    op.create_index("ix_api_client_tenant_status", "api_clients", ["tenant_id", "status"])


def downgrade() -> None:
    op.drop_table("api_clients")
    op.drop_table("tenant_memberships")
    op.drop_table("tenants")
