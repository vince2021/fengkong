"""add governed scorecard definitions

Revision ID: 20260831_0062
Revises: 20260828_0061
"""
from alembic import op
import sqlalchemy as sa

revision = "20260831_0062"
down_revision = "20260828_0061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scorecard_definitions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="published"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("change_id", sa.String(36), sa.ForeignKey("model_changes.id"), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_by_name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("code", "version", name="uq_scorecard_code_version"),
    )
    op.create_index("ix_scorecard_definitions_code", "scorecard_definitions", ["code"])
    op.create_index("ix_scorecard_definitions_status", "scorecard_definitions", ["status"])
    op.create_index("ix_scorecard_definitions_is_active", "scorecard_definitions", ["is_active"])
    op.create_index("ix_scorecard_definitions_config_hash", "scorecard_definitions", ["config_hash"])
    op.create_index("ix_scorecard_definitions_change_id", "scorecard_definitions", ["change_id"])
    op.create_index("uq_scorecard_single_active", "scorecard_definitions", ["code", "is_active"], unique=True, sqlite_where=sa.text("is_active = 1"), postgresql_where=sa.text("is_active = true"))


def downgrade() -> None:
    op.drop_table("scorecard_definitions")
