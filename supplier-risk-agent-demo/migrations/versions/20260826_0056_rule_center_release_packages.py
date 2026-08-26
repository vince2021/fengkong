"""rule_center: add atomic release packages

Revision ID: 20260826_0056
Revises: 20260826_0055
Create Date: 2026-08-26
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260826_0056"
down_revision = "20260826_0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rule_center_release_packages",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("dependency_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("impact_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_by_name", sa.String(length=128), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(length=128), nullable=True),
        sa.Column("reviewed_by_name", sa.String(length=128), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_rule_center_release_packages_status", "rule_center_release_packages", ["status"])
    op.create_index("ix_rule_center_release_packages_config_hash", "rule_center_release_packages", ["config_hash"])
    op.create_index("ix_rule_center_release_packages_created_by", "rule_center_release_packages", ["created_by"])
    op.create_index("ix_rule_center_release_packages_created_at", "rule_center_release_packages", ["created_at"])

    op.create_table(
        "rule_center_release_package_members",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("package_id", sa.String(length=36), sa.ForeignKey("rule_center_release_packages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("change_id", sa.String(length=36), sa.ForeignKey("model_changes.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("asset_type", sa.String(length=32), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("candidate_version", sa.String(length=128), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("package_id", "change_id", name="uq_rule_center_package_change"),
        sa.UniqueConstraint("package_id", "asset_type", "code", name="uq_rule_center_package_asset"),
    )
    op.create_index("ix_rule_center_release_package_members_package_id", "rule_center_release_package_members", ["package_id"])
    op.create_index("ix_rule_center_release_package_members_change_id", "rule_center_release_package_members", ["change_id"])
    op.create_index("ix_rule_center_release_package_members_asset_type", "rule_center_release_package_members", ["asset_type"])
    op.create_index("ix_rule_center_release_package_members_code", "rule_center_release_package_members", ["code"])


def downgrade() -> None:
    op.drop_table("rule_center_release_package_members")
    op.drop_table("rule_center_release_packages")
