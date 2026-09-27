"""Add tenant-native monitoring snapshots for supervised evaluation binding.

Revision ID: 20260924_0109
Revises: 20260923_0108
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260924_0109"
down_revision = "20260923_0108"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_monitoring_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("policy_id", sa.String(36), nullable=False),
        sa.Column("run_key", sa.String(160), nullable=False),
        sa.Column("model_key", sa.String(64), nullable=False),
        sa.Column("model_version", sa.String(128), nullable=False),
        sa.Column("observed_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dataset_id", sa.String(160), nullable=False),
        sa.Column("evidence_level", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="completed"),
        sa.Column("label_definition_id", sa.String(36), nullable=True),
        sa.Column("label_definition_version", sa.Integer(), nullable=True),
        sa.Column("label_definition_hash", sa.String(64), nullable=True),
        sa.Column("label_watermark_json", sa.JSON(), nullable=False),
        sa.Column("monitoring_json", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_by_name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "policy_id"], ["tenant_rollout_policies.tenant_id", "tenant_rollout_policies.id"], ondelete="RESTRICT", name="fk_tenant_monitoring_run_tenant_policy"),
        sa.ForeignKeyConstraint(["label_definition_id"], ["tenant_outcome_label_definitions.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("status IN ('completed', 'failed', 'cancelled')", name="ck_tenant_monitoring_run_status"),
        sa.CheckConstraint("evidence_level IN ('supervised', 'non_supervised')", name="ck_tenant_monitoring_run_evidence_level"),
        sa.UniqueConstraint("tenant_id", "run_key", name="uq_tenant_monitoring_run_key"),
    )
    for column in ("tenant_id", "policy_id", "run_key", "model_key", "model_version", "observed_from", "observed_to", "evidence_level", "status", "label_definition_id", "label_definition_hash", "evidence_hash", "created_at"):
        op.create_index(f"ix_tenant_monitoring_runs_{column}", "tenant_monitoring_runs", [column])
    op.create_index("ix_tenant_monitoring_run_policy_window", "tenant_monitoring_runs", ["tenant_id", "policy_id", "observed_to", "created_at"])

    with op.batch_alter_table("tenant_supervised_evaluations") as batch:
        batch.add_column(sa.Column("tenant_monitoring_run_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("tenant_monitoring_evidence_hash", sa.String(64), nullable=True))
        batch.create_foreign_key("fk_tenant_supervised_evaluation_monitoring_run", "tenant_monitoring_runs", ["tenant_monitoring_run_id"], ["id"], ondelete="RESTRICT")
        batch.create_index("ix_tenant_supervised_evaluations_tenant_monitoring_run_id", ["tenant_monitoring_run_id"])
        batch.create_index("ix_tenant_supervised_evaluations_tenant_monitoring_evidence_hash", ["tenant_monitoring_evidence_hash"])


def downgrade() -> None:
    with op.batch_alter_table("tenant_supervised_evaluations") as batch:
        batch.drop_index("ix_tenant_supervised_evaluations_tenant_monitoring_evidence_hash")
        batch.drop_index("ix_tenant_supervised_evaluations_tenant_monitoring_run_id")
        batch.drop_constraint("fk_tenant_supervised_evaluation_monitoring_run", type_="foreignkey")
        batch.drop_column("tenant_monitoring_evidence_hash")
        batch.drop_column("tenant_monitoring_run_id")
    op.drop_index("ix_tenant_monitoring_run_policy_window", table_name="tenant_monitoring_runs")
    for column in ("tenant_id", "policy_id", "run_key", "model_key", "model_version", "observed_from", "observed_to", "evidence_level", "status", "label_definition_id", "label_definition_hash", "evidence_hash", "created_at"):
        op.drop_index(f"ix_tenant_monitoring_runs_{column}", table_name="tenant_monitoring_runs")
    op.drop_table("tenant_monitoring_runs")
