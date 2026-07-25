"""Add governed model changes and release history.

Revision ID: 20260714_0008
Revises: 20260714_0007
"""

from alembic import op
import sqlalchemy as sa


revision = "20260714_0008"
down_revision = "20260714_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_changes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("template_key", sa.String(length=64), nullable=False),
        sa.Column("base_version", sa.String(length=128), nullable=False),
        sa.Column("candidate_version", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("validation_json", sa.JSON(), nullable=False),
        sa.Column("impact_json", sa.JSON(), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_by_name", sa.String(length=128), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(length=128), nullable=True),
        sa.Column("reviewed_by_name", sa.String(length=128), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_key", "candidate_version", name="uq_model_change_candidate_version"),
    )
    op.create_index("ix_model_changes_template_key", "model_changes", ["template_key"])
    op.create_index("ix_model_changes_status", "model_changes", ["status"])
    op.create_index("ix_model_changes_created_by", "model_changes", ["created_by"])
    op.create_index("ix_model_changes_created_at", "model_changes", ["created_at"])
    op.create_index("ix_model_changes_template_status_created", "model_changes", ["template_key", "status", "created_at"])

    op.create_table(
        "model_releases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("template_key", sa.String(length=64), nullable=False),
        sa.Column("model_version", sa.String(length=128), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("source_change_id", sa.String(length=36), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("published_by", sa.String(length=128), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["source_change_id"], ["model_changes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_key", "model_version", name="uq_model_release_version"),
    )
    op.create_index("ix_model_releases_template_key", "model_releases", ["template_key"])
    op.create_index("ix_model_releases_model_version", "model_releases", ["model_version"])
    op.create_index("ix_model_releases_source_change_id", "model_releases", ["source_change_id"])
    op.create_index("ix_model_releases_is_active", "model_releases", ["is_active"])
    op.create_index("ix_model_releases_config_hash", "model_releases", ["config_hash"])
    op.create_index("ix_model_releases_published_at", "model_releases", ["published_at"])
    op.create_index("ix_model_releases_template_active", "model_releases", ["template_key", "is_active", "published_at"])


def downgrade() -> None:
    op.drop_table("model_releases")
    op.drop_table("model_changes")
