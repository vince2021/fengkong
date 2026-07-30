"""add immutable authority policy evidence anchors

Revision ID: 20260726_0041
Revises: 20260726_0040
"""

from alembic import op
import sqlalchemy as sa


revision = "20260726_0041"
down_revision = "20260726_0040"
branch_labels = None
depends_on = None


TABLE = "authority_policy_evidence_anchors"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in inspector.get_table_names():
        op.create_table(
            TABLE,
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("policy_id", sa.String(length=36), nullable=False),
            sa.Column("policy_version", sa.String(length=128), nullable=False),
            sa.Column("schema_version", sa.String(length=64), nullable=False),
            sa.Column("package_json", sa.JSON(), nullable=False),
            sa.Column("package_hash", sa.String(length=64), nullable=False),
            sa.Column("anchor_hash", sa.String(length=64), nullable=False),
            sa.Column("integrity_passed", sa.Boolean(), nullable=False),
            sa.Column("issued_by", sa.String(length=128), nullable=False),
            sa.Column("issued_by_name", sa.String(length=128), nullable=False),
            sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["policy_id"], ["credit_authority_policies.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("anchor_hash", name="uq_authority_policy_evidence_anchors_anchor_hash"),
            sa.UniqueConstraint("policy_id", "package_hash", name="uq_authority_evidence_anchor_policy_package"),
        )
    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes(TABLE)}
    index_specs = {
        "ix_authority_evidence_anchors_policy_issued": ["policy_id", "issued_at"],
        "ix_authority_policy_evidence_anchors_policy_id": ["policy_id"],
        "ix_authority_policy_evidence_anchors_policy_version": ["policy_version"],
        "ix_authority_policy_evidence_anchors_package_hash": ["package_hash"],
        "ix_authority_policy_evidence_anchors_integrity_passed": ["integrity_passed"],
        "ix_authority_policy_evidence_anchors_issued_by": ["issued_by"],
        "ix_authority_policy_evidence_anchors_issued_at": ["issued_at"],
    }
    for name, columns in index_specs.items():
        if name not in indexes:
            op.create_index(name, TABLE, columns)
    _normalize_redundant_unique_index(
        bind,
        "credit_authority_policies",
        "ix_credit_authority_policies_policy_version",
        ["policy_version"],
    )
    _normalize_redundant_unique_index(
        bind,
        "authority_policy_activation_runs",
        "ix_authority_policy_activation_runs_run_key",
        ["run_key"],
    )


def downgrade() -> None:
    op.drop_table(TABLE)


def _normalize_redundant_unique_index(
    bind,
    table_name: str,
    index_name: str,
    columns: list[str],
) -> None:
    """Keep uniqueness in the named table constraint and make its lookup index non-unique."""
    index = next(
        (
            item
            for item in sa.inspect(bind).get_indexes(table_name)
            if item["name"] == index_name
        ),
        None,
    )
    if index and index.get("unique"):
        op.drop_index(index_name, table_name=table_name)
        op.create_index(index_name, table_name, columns)
