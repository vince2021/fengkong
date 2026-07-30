"""Add versioned credit authority policies.

Revision ID: 20260726_0035
Revises: 20260726_0034
"""

from alembic import op
import sqlalchemy as sa


revision = "20260726_0035"
down_revision = "20260726_0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "credit_authority_policies" not in inspector.get_table_names():
        op.create_table(
            "credit_authority_policies",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("policy_version", sa.String(length=128), nullable=False),
            sa.Column("base_policy_version", sa.String(length=128), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("config_json", sa.JSON(), nullable=False),
            sa.Column("config_hash", sa.String(length=64), nullable=False),
            sa.Column("change_reason", sa.Text(), nullable=False),
            sa.Column("created_by", sa.String(length=128), nullable=False),
            sa.Column("created_by_name", sa.String(length=128), nullable=False),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reviewed_by", sa.String(length=128), nullable=True),
            sa.Column("reviewed_by_name", sa.String(length=128), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("review_comment", sa.Text(), nullable=True),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("policy_version", name="uq_authority_policy_version"),
        )
    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes("credit_authority_policies")}
    if "ix_authority_policies_status_created" not in indexes:
        op.create_index("ix_authority_policies_status_created", "credit_authority_policies", ["status", "created_at"])
    if "ix_credit_authority_policies_policy_version" not in indexes:
        op.create_index("ix_credit_authority_policies_policy_version", "credit_authority_policies", ["policy_version"])
    if "ix_credit_authority_policies_status" not in indexes:
        op.create_index("ix_credit_authority_policies_status", "credit_authority_policies", ["status"])
    if "ix_credit_authority_policies_config_hash" not in indexes:
        op.create_index("ix_credit_authority_policies_config_hash", "credit_authority_policies", ["config_hash"])
    if "ix_credit_authority_policies_created_by" not in indexes:
        op.create_index("ix_credit_authority_policies_created_by", "credit_authority_policies", ["created_by"])
    if "ix_credit_authority_policies_is_active" not in indexes:
        op.create_index("ix_credit_authority_policies_is_active", "credit_authority_policies", ["is_active"])
    if "ix_credit_authority_policies_created_at" not in indexes:
        op.create_index("ix_credit_authority_policies_created_at", "credit_authority_policies", ["created_at"])
    if "uq_authority_policies_one_active" not in indexes:
        op.create_index(
            "uq_authority_policies_one_active",
            "credit_authority_policies",
            ["is_active"],
            unique=True,
            sqlite_where=sa.text("is_active = 1"),
            postgresql_where=sa.text("is_active IS TRUE"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "credit_authority_policies" in sa.inspect(bind).get_table_names():
        op.drop_table("credit_authority_policies")
