"""add governed authority evidence anchor revocation

Revision ID: 20260726_0042
Revises: 20260726_0041
"""

from alembic import op
import sqlalchemy as sa


revision = "20260726_0042"
down_revision = "20260726_0041"
branch_labels = None
depends_on = None


TABLE = "authority_policy_evidence_anchors"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns(TABLE)}
    additions = [
        ("revoked_by", sa.Column("revoked_by", sa.String(length=128), nullable=True)),
        ("revoked_by_name", sa.Column("revoked_by_name", sa.String(length=128), nullable=True)),
        ("revoked_at", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True)),
        ("revocation_reason", sa.Column("revocation_reason", sa.Text(), nullable=True)),
        ("row_version", sa.Column("row_version", sa.Integer(), nullable=False, server_default="1")),
    ]
    with op.batch_alter_table(TABLE) as batch:
        for name, column in additions:
            if name not in columns:
                batch.add_column(column)

    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes(TABLE)}
    index_specs = {
        "ix_authority_policy_evidence_anchors_revoked_by": ["revoked_by"],
        "ix_authority_policy_evidence_anchors_revoked_at": ["revoked_at"],
    }
    for name, index_columns in index_specs.items():
        if name not in indexes:
            op.create_index(name, TABLE, index_columns)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes(TABLE)}
    for name in [
        "ix_authority_policy_evidence_anchors_revoked_at",
        "ix_authority_policy_evidence_anchors_revoked_by",
    ]:
        if name in indexes:
            op.drop_index(name, table_name=TABLE)
    columns = {column["name"] for column in sa.inspect(bind).get_columns(TABLE)}
    with op.batch_alter_table(TABLE) as batch:
        for name in [
            "row_version",
            "revocation_reason",
            "revoked_at",
            "revoked_by_name",
            "revoked_by",
        ]:
            if name in columns:
                batch.drop_column(name)
