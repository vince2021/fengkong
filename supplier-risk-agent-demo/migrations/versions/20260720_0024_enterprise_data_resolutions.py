"""Add enterprise data conflict resolution workflow.

Revision ID: 20260720_0024
Revises: 20260717_0023
"""

from alembic import op
import sqlalchemy as sa


revision = "20260720_0024"
down_revision = "20260717_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("enterprise_data_resolutions"):
        return
    op.create_table(
        "enterprise_data_resolutions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("counterparty_id", sa.String(length=128), nullable=False),
        sa.Column("field_path", sa.String(length=512), nullable=False),
        sa.Column("selected_field_id", sa.String(length=36), nullable=False),
        sa.Column("selected_value_json", sa.JSON(), nullable=False),
        sa.Column("selected_value_hash", sa.String(length=64), nullable=False),
        sa.Column("candidate_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("reason_category", sa.String(length=64), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_by_name", sa.String(length=128), nullable=False),
        sa.Column("reviewed_by", sa.String(length=128), nullable=True),
        sa.Column("reviewed_by_name", sa.String(length=128), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["selected_field_id"], ["enterprise_data_fields.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, columns in [
        ("ix_enterprise_data_resolutions_counterparty_id", ["counterparty_id"]),
        ("ix_enterprise_data_resolutions_field_path", ["field_path"]),
        ("ix_enterprise_data_resolutions_selected_field_id", ["selected_field_id"]),
        ("ix_enterprise_data_resolutions_selected_value_hash", ["selected_value_hash"]),
        ("ix_enterprise_data_resolutions_candidate_snapshot_hash", ["candidate_snapshot_hash"]),
        ("ix_enterprise_data_resolutions_reason_category", ["reason_category"]),
        ("ix_enterprise_data_resolutions_status", ["status"]),
        ("ix_enterprise_data_resolutions_created_by", ["created_by"]),
        ("ix_enterprise_data_resolutions_reviewed_by", ["reviewed_by"]),
        ("ix_enterprise_data_resolutions_reviewed_at", ["reviewed_at"]),
        ("ix_enterprise_data_resolutions_created_at", ["created_at"]),
        ("ix_enterprise_data_resolutions_counterparty_path", ["counterparty_id", "field_path", "created_at"]),
    ]:
        op.create_index(name, "enterprise_data_resolutions", columns, unique=False)
    op.create_index(
        "uq_enterprise_data_pending_resolution",
        "enterprise_data_resolutions",
        ["counterparty_id", "field_path"],
        unique=True,
        sqlite_where=sa.text("status = 'pending_review'"),
        postgresql_where=sa.text("status = 'pending_review'"),
    )


def downgrade() -> None:
    op.drop_table("enterprise_data_resolutions")
