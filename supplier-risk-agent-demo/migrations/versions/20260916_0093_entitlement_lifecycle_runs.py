"""add tenant entitlement lifecycle execution ledger

Revision ID: 20260916_0093
Revises: 20260915_0092
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260916_0093"
down_revision = "20260915_0092"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenant_entitlements", sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_tenant_entitlements_expired_at", "tenant_entitlements", ["expired_at"])
    op.create_table(
        "tenant_entitlement_lifecycle_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_key", sa.String(length=160), nullable=False),
        sa.Column("trigger_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("scan_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_count", sa.Integer(), nullable=False),
        sa.Column("expired_count", sa.Integer(), nullable=False),
        sa.Column("superseded_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("results_json", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("incident_status", sa.String(length=32), nullable=False),
        sa.Column("acknowledged_by", sa.String(length=128), nullable=True),
        sa.Column("acknowledged_by_name", sa.String(length=128), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledgement_note", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.String(length=128), nullable=True),
        sa.Column("resolved_by_name", sa.String(length=128), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("retry_of_run_id", sa.String(length=36), nullable=True),
        sa.Column("resolved_by_run_id", sa.String(length=36), nullable=True),
        sa.Column("actor_subject", sa.String(length=128), nullable=False),
        sa.Column("actor_name", sa.String(length=128), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("trigger_type IN ('scheduler', 'manual', 'retry')", name="ck_tenant_entitlement_lifecycle_trigger"),
        sa.CheckConstraint("status IN ('no_due', 'completed', 'partial', 'failed')", name="ck_tenant_entitlement_lifecycle_status"),
        sa.CheckConstraint("incident_status IN ('not_applicable', 'open', 'acknowledged', 'resolved')", name="ck_tenant_entitlement_lifecycle_incident"),
        sa.ForeignKeyConstraint(["retry_of_run_id"], ["tenant_entitlement_lifecycle_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["resolved_by_run_id"], ["tenant_entitlement_lifecycle_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_key", name="uq_tenant_entitlement_lifecycle_run_key"),
    )
    for column in ("run_key", "trigger_type", "status", "scan_at", "evidence_hash", "incident_status", "retry_of_run_id", "created_at"):
        op.create_index(f"ix_tenant_entitlement_lifecycle_runs_{column}", "tenant_entitlement_lifecycle_runs", [column])
    op.create_index("ix_tenant_entitlement_lifecycle_status_created", "tenant_entitlement_lifecycle_runs", ["status", "created_at"])
    op.create_index("ix_tenant_entitlement_lifecycle_incident_created", "tenant_entitlement_lifecycle_runs", ["incident_status", "created_at"])


def downgrade() -> None:
    op.drop_table("tenant_entitlement_lifecycle_runs")
    op.drop_index("ix_tenant_entitlements_expired_at", table_name="tenant_entitlements")
    op.drop_column("tenant_entitlements", "expired_at")
