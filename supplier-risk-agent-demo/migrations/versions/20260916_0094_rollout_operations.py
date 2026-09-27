"""Add rollout scan ledger and circuit-breaker incident workflow.

Revision ID: 20260916_0094
Revises: 20260916_0093
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260916_0094"
down_revision = "20260916_0093"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tenant_rollout_policies") as batch:
        batch.add_column(sa.Column("incident_status", sa.String(32), nullable=False, server_default="not_applicable"))
        for name, column_type in (
            ("incident_evaluation_id", sa.String(36)), ("acknowledged_by", sa.String(128)),
            ("acknowledged_at", sa.DateTime(timezone=True)), ("acknowledgement_note", sa.Text()),
            ("resolution_requested_by", sa.String(128)), ("resolution_requested_at", sa.DateTime(timezone=True)),
            ("resolution_note", sa.Text()), ("resolved_by", sa.String(128)),
            ("resolved_at", sa.DateTime(timezone=True)),
        ):
            batch.add_column(sa.Column(name, column_type, nullable=True))
        batch.create_index("ix_tenant_rollout_policies_incident_status", ["incident_status"])
    op.create_table(
        "tenant_rollout_scans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_key", sa.String(160), nullable=False),
        sa.Column("tenant_id", sa.String(128), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("trigger_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("scan_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("results_json", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("status IN ('no_due', 'completed', 'partial', 'failed')", name="ck_tenant_rollout_scan_status"),
        sa.UniqueConstraint("run_key", name="uq_tenant_rollout_scan_key"),
    )
    op.create_index("ix_tenant_rollout_scans_run_key", "tenant_rollout_scans", ["run_key"])
    op.create_index("ix_tenant_rollout_scan_scope_created", "tenant_rollout_scans", ["tenant_id", "created_at"])


def downgrade() -> None:
    op.drop_table("tenant_rollout_scans")
    with op.batch_alter_table("tenant_rollout_policies") as batch:
        batch.drop_index("ix_tenant_rollout_policies_incident_status")
        for name in (
            "resolved_at", "resolved_by", "resolution_note", "resolution_requested_at",
            "resolution_requested_by", "acknowledgement_note", "acknowledged_at",
            "acknowledged_by", "incident_evaluation_id", "incident_status",
        ):
            batch.drop_column(name)
