"""Add tenant notification channels and outbound delivery evidence.

Revision ID: 20260927_0114
Revises: 20260927_0113
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260927_0114"
down_revision = "20260927_0113"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_notification_channels",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("channel_type", sa.String(32), nullable=False, server_default="webhook"),
        sa.Column("delivery_mode", sa.String(32), nullable=False, server_default="sandbox"),
        sa.Column("endpoint_url", sa.String(2000), nullable=False),
        sa.Column("secret_reference", sa.String(256), nullable=False),
        sa.Column("subscribed_categories_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("recipient_roles_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("minimum_severity", sa.String(16), nullable=False, server_default="warning"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("require_receipt", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sandbox_status_sequence_json", sa.JSON(), nullable=False, server_default="[200]"),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_by_name", sa.String(255), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "name", name="uq_tenant_notification_channel_name"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_tenant_notification_channel_tenant_id"),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_tenant_notification_channel_status"),
        sa.CheckConstraint("channel_type IN ('webhook')", name="ck_tenant_notification_channel_type"),
        sa.CheckConstraint("delivery_mode IN ('sandbox', 'live')", name="ck_tenant_notification_channel_mode"),
        sa.CheckConstraint("minimum_severity IN ('info', 'warning', 'critical')", name="ck_tenant_notification_channel_severity"),
        sa.CheckConstraint("max_attempts BETWEEN 1 AND 10", name="ck_tenant_notification_channel_attempts"),
        sa.CheckConstraint("timeout_seconds BETWEEN 1 AND 30", name="ck_tenant_notification_channel_timeout"),
    )
    op.create_index("ix_tenant_notification_channels_tenant_id", "tenant_notification_channels", ["tenant_id"])
    op.create_index("ix_tenant_notification_channels_status", "tenant_notification_channels", ["status"])
    op.create_index("ix_tenant_notification_channels_created_at", "tenant_notification_channels", ["created_at"])
    op.create_index(
        "ix_tenant_notification_channel_status", "tenant_notification_channels", ["tenant_id", "status", "created_at"]
    )

    op.create_table(
        "tenant_notification_deliveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_id", sa.String(36), nullable=False),
        sa.Column("notification_id", sa.String(36), sa.ForeignKey("notifications.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("idempotency_key", sa.String(512), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("endpoint_url", sa.String(2000), nullable=False),
        sa.Column("delivery_mode", sa.String(32), nullable=False),
        sa.Column("secret_reference", sa.String(256), nullable=False),
        sa.Column("require_receipt", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("transport_config_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("channel_config_hash", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("signature_timestamp", sa.String(32), nullable=False),
        sa.Column("signature", sa.String(64), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_history_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("receipt_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("manual_redelivery_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["tenant_id", "channel_id"],
            ["tenant_notification_channels.tenant_id", "tenant_notification_channels.id"],
            name="fk_tenant_notification_delivery_channel",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_notification_delivery_key"),
        sa.CheckConstraint(
            "status IN ('pending', 'retry_scheduled', 'delivered', 'dead_letter', 'cancelled')",
            name="ck_tenant_notification_delivery_status",
        ),
        sa.CheckConstraint("delivery_mode IN ('sandbox', 'live')", name="ck_tenant_notification_delivery_mode"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_tenant_notification_delivery_attempts"),
        sa.CheckConstraint("max_attempts BETWEEN 1 AND 10", name="ck_tenant_notification_delivery_max_attempts"),
    )
    for column in ("tenant_id", "channel_id", "notification_id", "event_type", "channel_config_hash", "payload_hash", "status", "next_attempt_at", "created_at"):
        op.create_index(f"ix_tenant_notification_deliveries_{column}", "tenant_notification_deliveries", [column])
    op.create_index(
        "ix_tenant_notification_delivery_status", "tenant_notification_deliveries",
        ["tenant_id", "status", "next_attempt_at"],
    )
    op.create_index(
        "ix_tenant_notification_delivery_notification", "tenant_notification_deliveries",
        ["tenant_id", "notification_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("tenant_notification_deliveries")
    op.drop_table("tenant_notification_channels")
