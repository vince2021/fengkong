"""add renewal document carryover lineage

Revision ID: 20260731_0045
Revises: 20260731_0044
"""

from alembic import op
import sqlalchemy as sa


revision = "20260731_0045"
down_revision = "20260731_0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("documents")}
    foreign_keys = {foreign_key["name"] for foreign_key in inspector.get_foreign_keys("documents")}
    unique_constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("documents")}
    with op.batch_alter_table("documents") as batch:
        if "source_document_id" not in columns:
            batch.add_column(sa.Column("source_document_id", sa.String(length=36), nullable=True))
        if "fk_documents_source_document" not in foreign_keys:
            batch.create_foreign_key(
                "fk_documents_source_document",
                "documents",
                ["source_document_id"],
                ["id"],
            )
        if "carried_over_by" not in columns:
            batch.add_column(sa.Column("carried_over_by", sa.String(length=128), nullable=True))
        if "carried_over_at" not in columns:
            batch.add_column(sa.Column("carried_over_at", sa.DateTime(timezone=True), nullable=True))
        if "uq_documents_case_source_document" not in unique_constraints:
            batch.create_unique_constraint(
                "uq_documents_case_source_document",
                ["case_id", "source_document_id"],
            )
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("documents")}
    if "ix_documents_source_document_id" not in indexes:
        op.create_index("ix_documents_source_document_id", "documents", ["source_document_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes("documents")}
    if "ix_documents_source_document_id" in indexes:
        op.drop_index("ix_documents_source_document_id", table_name="documents")
    columns = {column["name"] for column in inspector.get_columns("documents")}
    foreign_keys = {foreign_key["name"] for foreign_key in inspector.get_foreign_keys("documents")}
    unique_constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("documents")}
    with op.batch_alter_table("documents") as batch:
        if "uq_documents_case_source_document" in unique_constraints:
            batch.drop_constraint("uq_documents_case_source_document", type_="unique")
        if "fk_documents_source_document" in foreign_keys:
            batch.drop_constraint("fk_documents_source_document", type_="foreignkey")
        if "carried_over_at" in columns:
            batch.drop_column("carried_over_at")
        if "carried_over_by" in columns:
            batch.drop_column("carried_over_by")
        if "source_document_id" in columns:
            batch.drop_column("source_document_id")
