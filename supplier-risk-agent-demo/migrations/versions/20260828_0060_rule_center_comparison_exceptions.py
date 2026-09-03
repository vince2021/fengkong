"""rule_center: add comparison gates and governed exceptions

Revision ID: 20260828_0060
Revises: 20260826_0059
Create Date: 2026-08-28
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260828_0060"
down_revision = "20260826_0059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("rule_center_replay_comparison_runs") as batch:
        batch.add_column(sa.Column("gate_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
    op.create_table(
        "rule_center_replay_comparison_exceptions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("comparison_run_id", sa.String(length=36), sa.ForeignKey("rule_center_replay_comparison_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("comparison_evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("business_impact", sa.Text(), nullable=False),
        sa.Column("compensating_controls", sa.Text(), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("requested_by", sa.String(length=128), nullable=False),
        sa.Column("requested_by_name", sa.String(length=128), nullable=False),
        sa.Column("reviewed_by", sa.String(length=128), nullable=True),
        sa.Column("reviewed_by_name", sa.String(length=128), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    for name in ("comparison_run_id", "comparison_evidence_hash", "status", "valid_until", "request_hash", "requested_by", "created_at"):
        op.create_index(f"ix_rule_center_replay_comparison_exceptions_{name}", "rule_center_replay_comparison_exceptions", [name])
    op.create_index("ix_replay_comparison_exception_run_created", "rule_center_replay_comparison_exceptions", ["comparison_run_id", "created_at"])


def downgrade() -> None:
    op.drop_table("rule_center_replay_comparison_exceptions")
    with op.batch_alter_table("rule_center_replay_comparison_runs") as batch:
        batch.drop_column("gate_json")
