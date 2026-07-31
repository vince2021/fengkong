"""add governed authority evidence anchor replacement

Revision ID: 20260730_0043
Revises: 20260726_0042
"""

from alembic import op
import sqlalchemy as sa


revision = "20260730_0043"
down_revision = "20260726_0042"
branch_labels = None
depends_on = None


TABLE = "authority_policy_evidence_anchors"
OLD_UNIQUE = "uq_authority_evidence_anchor_policy_package"
ACTIVE_UNIQUE = "uq_authority_evidence_anchor_active_policy_package"
SUPERSEDES_UNIQUE = "uq_authority_evidence_anchor_supersedes"
SUPERSEDES_FK = "fk_authority_evidence_anchor_supersedes"
SUPERSEDES_INDEX = "ix_authority_policy_evidence_anchors_supersedes_anchor_id"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns(TABLE)}
    unique_constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints(TABLE)
        if constraint.get("name")
    }
    with op.batch_alter_table(TABLE) as batch:
        if "supersedes_anchor_id" not in columns:
            batch.add_column(
                sa.Column("supersedes_anchor_id", sa.String(length=36), nullable=True)
            )
        if "replacement_reason" not in columns:
            batch.add_column(sa.Column("replacement_reason", sa.Text(), nullable=True))
        if OLD_UNIQUE in unique_constraints:
            batch.drop_constraint(OLD_UNIQUE, type_="unique")
        if SUPERSEDES_UNIQUE not in unique_constraints:
            batch.create_unique_constraint(
                SUPERSEDES_UNIQUE,
                ["supersedes_anchor_id"],
            )
        batch.create_foreign_key(
            SUPERSEDES_FK,
            TABLE,
            ["supersedes_anchor_id"],
            ["id"],
        )

    indexes = {
        index["name"]
        for index in sa.inspect(bind).get_indexes(TABLE)
    }
    if SUPERSEDES_INDEX not in indexes:
        op.create_index(SUPERSEDES_INDEX, TABLE, ["supersedes_anchor_id"])
    if ACTIVE_UNIQUE not in indexes:
        op.create_index(
            ACTIVE_UNIQUE,
            TABLE,
            ["policy_id", "package_hash"],
            unique=True,
            sqlite_where=sa.text("revoked_at IS NULL"),
            postgresql_where=sa.text("revoked_at IS NULL"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {
        index["name"]
        for index in sa.inspect(bind).get_indexes(TABLE)
    }
    for name in [ACTIVE_UNIQUE, SUPERSEDES_INDEX]:
        if name in indexes:
            op.drop_index(name, table_name=TABLE)

    unique_constraints = {
        constraint["name"]
        for constraint in sa.inspect(bind).get_unique_constraints(TABLE)
        if constraint.get("name")
    }
    with op.batch_alter_table(TABLE) as batch:
        if SUPERSEDES_UNIQUE in unique_constraints:
            batch.drop_constraint(SUPERSEDES_UNIQUE, type_="unique")
        batch.drop_constraint(SUPERSEDES_FK, type_="foreignkey")
        for name in ["replacement_reason", "supersedes_anchor_id"]:
            batch.drop_column(name)
        batch.create_unique_constraint(
            OLD_UNIQUE,
            ["policy_id", "package_hash"],
        )
