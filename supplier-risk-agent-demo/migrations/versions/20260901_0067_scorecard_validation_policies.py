"""add governed scorecard validation policy templates

Revision ID: 20260901_0067
Revises: 20260901_0066
"""
from alembic import op
import sqlalchemy as sa


revision = "20260901_0067"
down_revision = "20260901_0066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scorecard_validation_policies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("applicable_scorecard_codes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("thresholds_json", sa.JSON(), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_by_name", sa.String(128), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(128), nullable=True),
        sa.Column("reviewed_by_name", sa.String(128), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("code", "version", name="uq_scorecard_validation_policy_code_version"),
    )
    for name, columns in (
        ("ix_scorecard_validation_policies_code", ["code"]),
        ("ix_scorecard_validation_policies_status", ["status"]),
        ("ix_scorecard_validation_policies_is_active", ["is_active"]),
        ("ix_scorecard_validation_policies_is_default", ["is_default"]),
        ("ix_scorecard_validation_policies_config_hash", ["config_hash"]),
        ("ix_scorecard_validation_policies_created_by", ["created_by"]),
        ("ix_scorecard_validation_policies_reviewed_by", ["reviewed_by"]),
        ("ix_scorecard_validation_policies_created_at", ["created_at"]),
    ):
        op.create_index(name, "scorecard_validation_policies", columns)
    op.create_index(
        "uq_scorecard_validation_policy_single_active", "scorecard_validation_policies", ["code", "is_active"],
        unique=True, sqlite_where=sa.text("is_active = 1"), postgresql_where=sa.text("is_active = true"),
    )
    with op.batch_alter_table("scorecard_development_runs") as batch:
        batch.add_column(sa.Column("validation_policy_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("validation_policy_hash", sa.String(64), nullable=True))
        batch.create_foreign_key(
            "fk_scorecard_development_validation_policy", "scorecard_validation_policies",
            ["validation_policy_id"], ["id"], ondelete="RESTRICT",
        )
    op.create_index("ix_scorecard_development_runs_validation_policy_id", "scorecard_development_runs", ["validation_policy_id"])
    op.create_index("ix_scorecard_development_runs_validation_policy_hash", "scorecard_development_runs", ["validation_policy_hash"])


def downgrade() -> None:
    op.drop_index("ix_scorecard_development_runs_validation_policy_hash", table_name="scorecard_development_runs")
    op.drop_index("ix_scorecard_development_runs_validation_policy_id", table_name="scorecard_development_runs")
    with op.batch_alter_table("scorecard_development_runs") as batch:
        batch.drop_constraint("fk_scorecard_development_validation_policy", type_="foreignkey")
        batch.drop_column("validation_policy_hash")
        batch.drop_column("validation_policy_id")
    op.drop_table("scorecard_validation_policies")
