"""Add model-risk review operations workbench persistence.

Revision ID: 20260926_0112
Revises: 20260924_0111
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260926_0112"
down_revision = "20260924_0111"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_risk_review_assignments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_id", sa.String(192), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("assigned_role", sa.String(64), nullable=False),
        sa.Column("assigned_to", sa.String(128), nullable=True),
        sa.Column("assigned_to_name", sa.String(255), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("assigned_by", sa.String(128), nullable=False),
        sa.Column("assigned_by_name", sa.String(255), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "item_id", name="uq_model_risk_review_assignment_item"),
    )
    op.create_index("ix_model_risk_review_assignments_tenant_id", "model_risk_review_assignments", ["tenant_id"])
    op.create_index("ix_model_risk_review_assignments_item_id", "model_risk_review_assignments", ["item_id"])
    op.create_index("ix_model_risk_review_assignments_source", "model_risk_review_assignments", ["source"])
    op.create_index("ix_model_risk_review_assignments_assigned_to", "model_risk_review_assignments", ["assigned_to"])
    op.create_index("ix_model_risk_review_assignment_tenant_owner", "model_risk_review_assignments", ["tenant_id", "assigned_to"])
    op.create_index("ix_model_risk_review_assignment_tenant_role", "model_risk_review_assignments", ["tenant_id", "assigned_role"])

    op.create_table(
        "model_risk_review_saved_views",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_subject", sa.String(128), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("filters_json", sa.JSON(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "owner_subject", "name", name="uq_model_risk_review_view_owner_name"),
    )
    op.create_index("ix_model_risk_review_saved_views_tenant_id", "model_risk_review_saved_views", ["tenant_id"])
    op.create_index("ix_model_risk_review_saved_views_owner_subject", "model_risk_review_saved_views", ["owner_subject"])
    op.create_index("ix_model_risk_review_saved_views_is_default", "model_risk_review_saved_views", ["is_default"])
    op.create_index(
        "uq_model_risk_review_view_owner_default", "model_risk_review_saved_views",
        ["tenant_id", "owner_subject"], unique=True,
        sqlite_where=sa.text("is_default = 1"), postgresql_where=sa.text("is_default = true"),
    )

    op.create_table(
        "model_risk_review_sla_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("template_key", sa.String(64), nullable=True),
        sa.Column("counts_json", sa.JSON(), nullable=False),
        sa.Column("source_counts_json", sa.JSON(), nullable=False),
        sa.Column("owner_counts_json", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "snapshot_date", "template_key", name="uq_model_risk_review_sla_snapshot_bucket"),
    )
    op.create_index("ix_model_risk_review_sla_snapshots_tenant_id", "model_risk_review_sla_snapshots", ["tenant_id"])
    op.create_index("ix_model_risk_review_sla_snapshots_snapshot_date", "model_risk_review_sla_snapshots", ["snapshot_date"])
    op.create_index("ix_model_risk_review_sla_snapshots_template_key", "model_risk_review_sla_snapshots", ["template_key"])
    op.create_index("ix_model_risk_review_sla_snapshot_tenant_date", "model_risk_review_sla_snapshots", ["tenant_id", "snapshot_date"])


def downgrade() -> None:
    op.drop_table("model_risk_review_sla_snapshots")
    op.drop_index("uq_model_risk_review_view_owner_default", table_name="model_risk_review_saved_views")
    op.drop_table("model_risk_review_saved_views")
    for name in (
        "ix_model_risk_review_assignment_tenant_role", "ix_model_risk_review_assignment_tenant_owner",
        "ix_model_risk_review_assignments_assigned_to", "ix_model_risk_review_assignments_source",
        "ix_model_risk_review_assignments_item_id", "ix_model_risk_review_assignments_tenant_id",
    ):
        op.drop_index(name, table_name="model_risk_review_assignments")
    op.drop_table("model_risk_review_assignments")
