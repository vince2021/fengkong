"""rule_center: add immutable replay dataset snapshots

Revision ID: 20260826_0058
Revises: 20260826_0057
Create Date: 2026-08-26
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260826_0058"
down_revision = "20260826_0057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rule_center_replay_datasets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_by_name", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("code", name="uq_rule_center_replay_dataset_code"),
    )
    op.create_index("ix_rule_center_replay_datasets_code", "rule_center_replay_datasets", ["code"], unique=True)
    op.create_index("ix_rule_center_replay_datasets_status", "rule_center_replay_datasets", ["status"])
    op.create_index("ix_rule_center_replay_datasets_created_by", "rule_center_replay_datasets", ["created_by"])
    op.create_index("ix_rule_center_replay_datasets_created_at", "rule_center_replay_datasets", ["created_at"])

    op.create_table(
        "rule_center_replay_dataset_snapshots",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("dataset_id", sa.String(length=36), sa.ForeignKey("rule_center_replay_datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source_name", sa.String(length=256), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("evidence_reference", sa.Text(), nullable=False),
        sa.Column("data_classification", sa.String(length=32), nullable=False),
        sa.Column("field_mapping_json", sa.JSON(), nullable=False),
        sa.Column("label_field", sa.String(length=256), nullable=True),
        sa.Column("observed_at_field", sa.String(length=256), nullable=True),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("samples_json", sa.JSON(), nullable=False),
        sa.Column("coverage_json", sa.JSON(), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_by_name", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("dataset_id", "version", name="uq_rule_center_replay_dataset_version"),
        sa.UniqueConstraint("dataset_id", "source_hash", name="uq_rule_center_replay_dataset_source"),
        sa.UniqueConstraint("content_hash", name="uq_rule_center_replay_snapshot_content_hash"),
    )
    op.create_index("ix_rule_center_replay_dataset_snapshots_dataset_id", "rule_center_replay_dataset_snapshots", ["dataset_id"])
    op.create_index("ix_rule_center_replay_dataset_snapshots_as_of_date", "rule_center_replay_dataset_snapshots", ["as_of_date"])
    op.create_index("ix_rule_center_replay_dataset_snapshots_source_hash", "rule_center_replay_dataset_snapshots", ["source_hash"])
    op.create_index("ix_rule_center_replay_dataset_snapshots_content_hash", "rule_center_replay_dataset_snapshots", ["content_hash"], unique=True)
    op.create_index("ix_rule_center_replay_dataset_snapshots_created_by", "rule_center_replay_dataset_snapshots", ["created_by"])
    op.create_index("ix_rule_center_replay_dataset_snapshots_created_at", "rule_center_replay_dataset_snapshots", ["created_at"])
    op.create_index("ix_rule_center_replay_snapshot_dataset_created", "rule_center_replay_dataset_snapshots", ["dataset_id", "created_at"])

    with op.batch_alter_table("rule_center_replay_runs") as batch:
        batch.add_column(sa.Column("dataset_snapshot_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("dataset_snapshot_hash", sa.String(length=64), nullable=True))
        batch.create_foreign_key("fk_rule_center_replay_snapshot", "rule_center_replay_dataset_snapshots", ["dataset_snapshot_id"], ["id"], ondelete="RESTRICT")
        batch.create_index("ix_rule_center_replay_runs_dataset_snapshot_id", ["dataset_snapshot_id"])
        batch.create_index("ix_rule_center_replay_runs_dataset_snapshot_hash", ["dataset_snapshot_hash"])


def downgrade() -> None:
    with op.batch_alter_table("rule_center_replay_runs") as batch:
        batch.drop_index("ix_rule_center_replay_runs_dataset_snapshot_hash")
        batch.drop_index("ix_rule_center_replay_runs_dataset_snapshot_id")
        batch.drop_constraint("fk_rule_center_replay_snapshot", type_="foreignkey")
        batch.drop_column("dataset_snapshot_hash")
        batch.drop_column("dataset_snapshot_id")
    op.drop_table("rule_center_replay_dataset_snapshots")
    op.drop_table("rule_center_replay_datasets")
