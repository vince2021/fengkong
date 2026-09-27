"""Add tenant outcome batch, correction lineage, and evaluation review.

Revision ID: 20260917_0097
Revises: 20260917_0096
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260917_0097"
down_revision = "20260917_0096"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_outcome_import_batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("policy_id", sa.String(36), nullable=False),
        sa.Column("import_key", sa.String(160), nullable=False),
        sa.Column("source", sa.String(128), nullable=False),
        sa.Column("label_definition", sa.String(128), nullable=False),
        sa.Column("expected_count", sa.Integer(), nullable=False),
        sa.Column("received_count", sa.Integer(), nullable=False),
        sa.Column("created_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("idempotent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("corrected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("results_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_by_name", sa.String(128), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("status IN ('processing', 'completed', 'completed_with_exceptions', 'failed')", name="ck_tenant_outcome_import_status"),
        sa.ForeignKeyConstraint(["tenant_id", "policy_id"], ["tenant_rollout_policies.tenant_id", "tenant_rollout_policies.id"], name="fk_tenant_outcome_import_tenant_policy", ondelete="RESTRICT"),
        sa.UniqueConstraint("tenant_id", "import_key", name="uq_tenant_outcome_import_key"),
    )
    for column in ("tenant_id", "policy_id", "import_key", "payload_hash", "status", "evidence_hash", "created_at"):
        op.create_index(f"ix_tenant_outcome_import_batches_{column}", "tenant_outcome_import_batches", [column])
    op.create_index("ix_tenant_outcome_import_policy_created", "tenant_outcome_import_batches", ["tenant_id", "policy_id", "created_at"])

    with op.batch_alter_table("tenant_outcome_labels") as batch:
        batch.drop_constraint("uq_tenant_outcome_label_route_definition", type_="unique")
        batch.add_column(sa.Column("import_batch_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("record_status", sa.String(32), nullable=False, server_default="active"))
        batch.add_column(sa.Column("supersedes_label_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("superseded_by_label_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("correction_reason", sa.Text(), nullable=True))
        batch.add_column(sa.Column("corrected_by", sa.String(128), nullable=True))
        batch.add_column(sa.Column("corrected_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_check_constraint("ck_tenant_outcome_label_record_status", "record_status IN ('active', 'superseded')")
        batch.create_foreign_key("fk_tenant_outcome_label_import_batch", "tenant_outcome_import_batches", ["import_batch_id"], ["id"], ondelete="RESTRICT")
        batch.create_foreign_key("fk_tenant_outcome_label_supersedes", "tenant_outcome_labels", ["supersedes_label_id"], ["id"], ondelete="RESTRICT")
        batch.create_foreign_key("fk_tenant_outcome_label_superseded_by", "tenant_outcome_labels", ["superseded_by_label_id"], ["id"], ondelete="RESTRICT")
    for column in ("import_batch_id", "record_status", "supersedes_label_id", "superseded_by_label_id"):
        op.create_index(f"ix_tenant_outcome_labels_{column}", "tenant_outcome_labels", [column])
    op.create_index(
        "uq_tenant_outcome_label_active_definition",
        "tenant_outcome_labels",
        ["tenant_id", "routing_decision_id", "label_definition"],
        unique=True,
        sqlite_where=sa.text("record_status = 'active'"),
        postgresql_where=sa.text("record_status = 'active'"),
    )

    with op.batch_alter_table("tenant_supervised_evaluations") as batch:
        batch.add_column(sa.Column("status", sa.String(32), nullable=False, server_default="draft"))
        batch.add_column(sa.Column("governance_decision", sa.String(32), nullable=True))
        batch.add_column(sa.Column("submitted_by", sa.String(128), nullable=True))
        batch.add_column(sa.Column("submitted_by_name", sa.String(128), nullable=True))
        batch.add_column(sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("reviewed_by", sa.String(128), nullable=True))
        batch.add_column(sa.Column("reviewed_by_name", sa.String(128), nullable=True))
        batch.add_column(sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("review_comment", sa.Text(), nullable=True))
        batch.add_column(sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"))
        batch.create_check_constraint("ck_tenant_supervised_evaluation_status", "status IN ('draft', 'pending_review', 'approved', 'rejected')")
        batch.create_check_constraint("ck_tenant_supervised_evaluation_decision", "governance_decision IS NULL OR governance_decision IN ('retain_champion', 'promote_candidate', 'reject_candidate', 'continue_observation')")
    op.create_index("ix_tenant_supervised_evaluations_status", "tenant_supervised_evaluations", ["status"])


def downgrade() -> None:
    op.drop_index("ix_tenant_supervised_evaluations_status", table_name="tenant_supervised_evaluations")
    with op.batch_alter_table("tenant_supervised_evaluations") as batch:
        batch.drop_constraint("ck_tenant_supervised_evaluation_decision", type_="check")
        batch.drop_constraint("ck_tenant_supervised_evaluation_status", type_="check")
        for column in ("row_version", "review_comment", "reviewed_at", "reviewed_by_name", "reviewed_by", "submitted_at", "submitted_by_name", "submitted_by", "governance_decision", "status"):
            batch.drop_column(column)

    op.drop_index("uq_tenant_outcome_label_active_definition", table_name="tenant_outcome_labels")
    for column in ("superseded_by_label_id", "supersedes_label_id", "record_status", "import_batch_id"):
        op.drop_index(f"ix_tenant_outcome_labels_{column}", table_name="tenant_outcome_labels")
    op.execute("DELETE FROM tenant_outcome_labels WHERE record_status = 'superseded'")
    with op.batch_alter_table("tenant_outcome_labels") as batch:
        batch.drop_constraint("fk_tenant_outcome_label_superseded_by", type_="foreignkey")
        batch.drop_constraint("fk_tenant_outcome_label_supersedes", type_="foreignkey")
        batch.drop_constraint("fk_tenant_outcome_label_import_batch", type_="foreignkey")
        batch.drop_constraint("ck_tenant_outcome_label_record_status", type_="check")
        for column in ("corrected_at", "corrected_by", "correction_reason", "superseded_by_label_id", "supersedes_label_id", "record_status", "import_batch_id"):
            batch.drop_column(column)
        batch.create_unique_constraint("uq_tenant_outcome_label_route_definition", ["tenant_id", "routing_decision_id", "label_definition"])

    op.drop_table("tenant_outcome_import_batches")
