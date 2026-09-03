"""add personal scorecard monitoring saved views

Revision ID: 20260902_0072
Revises: 20260902_0071
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260902_0072"
down_revision = "20260902_0071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scorecard_monitoring_saved_views",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_subject", sa.String(128), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("filters_json", sa.JSON(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("owner_subject", "name", name="uq_scorecard_monitoring_saved_view_owner_name"),
    )
    for column in ("owner_subject", "is_default", "created_at"):
        op.create_index(f"ix_scorecard_monitoring_saved_views_{column}", "scorecard_monitoring_saved_views", [column])
    op.create_index(
        "uq_scorecard_monitoring_saved_view_owner_default", "scorecard_monitoring_saved_views", ["owner_subject"], unique=True,
        sqlite_where=sa.text("is_default = 1"), postgresql_where=sa.text("is_default = true"),
    )


def downgrade() -> None:
    op.drop_index("uq_scorecard_monitoring_saved_view_owner_default", table_name="scorecard_monitoring_saved_views")
    for column in reversed(("owner_subject", "is_default", "created_at")):
        op.drop_index(f"ix_scorecard_monitoring_saved_views_{column}", table_name="scorecard_monitoring_saved_views")
    op.drop_table("scorecard_monitoring_saved_views")
