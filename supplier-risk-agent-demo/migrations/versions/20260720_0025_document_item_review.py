"""Add item-by-item document review workflow.

Revision ID: 20260720_0025
Revises: 20260720_0024
"""

from alembic import op
import sqlalchemy as sa


revision = "20260720_0025"
down_revision = "20260720_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {column["name"] for column in inspector.get_columns("documents")}
    additions = [
        ("checklist_json", sa.JSON(), sa.text("'[]'"), False),
        ("review_status", sa.String(length=32), sa.text("'pending_review'"), False),
        ("review_comment", sa.Text(), None, True),
        ("reviewed_by", sa.String(length=128), None, True),
        ("reviewed_by_name", sa.String(length=128), None, True),
        ("reviewed_at", sa.DateTime(timezone=True), None, True),
        ("row_version", sa.Integer(), sa.text("1"), False),
    ]
    for name, type_, default, nullable in additions:
        if name not in existing:
            op.add_column("documents", sa.Column(name, type_, server_default=default, nullable=nullable))

    index_names = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("documents")}
    for name, columns in [
        ("ix_documents_review_status", ["review_status"]),
        ("ix_documents_reviewed_by", ["reviewed_by"]),
        ("ix_documents_reviewed_at", ["reviewed_at"]),
    ]:
        if name not in index_names:
            op.create_index(name, "documents", columns, unique=False)


def downgrade() -> None:
    for name in ["ix_documents_reviewed_at", "ix_documents_reviewed_by", "ix_documents_review_status"]:
        op.drop_index(name, table_name="documents")
    for name in ["row_version", "reviewed_at", "reviewed_by_name", "reviewed_by", "review_comment", "review_status", "checklist_json"]:
        op.drop_column("documents", name)
