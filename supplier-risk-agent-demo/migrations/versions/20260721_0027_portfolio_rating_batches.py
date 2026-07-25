"""Add traceable portfolio rating batches.

Revision ID: 20260721_0027
Revises: 20260720_0026
"""

from alembic import op
import sqlalchemy as sa


revision = "20260721_0027"
down_revision = "20260720_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("portfolio_rating_batches"):
        return
    op.create_table(
        "portfolio_rating_batches",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("batch_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("template_key", sa.String(length=64), nullable=False),
        sa.Column("model_version", sa.String(length=128), nullable=False),
        sa.Column("model_snapshot_id", sa.String(length=36), sa.ForeignKey("model_snapshots.id"), nullable=True),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("success_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("results_json", sa.JSON(), nullable=False),
        sa.Column("skipped_json", sa.JSON(), nullable=False),
        sa.Column("result_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_by_name", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    for name, columns, unique in [
        ("ix_portfolio_rating_batches_batch_key", ["batch_key"], True),
        ("ix_portfolio_rating_batches_template_key", ["template_key"], False),
        ("ix_portfolio_rating_batches_model_version", ["model_version"], False),
        ("ix_portfolio_rating_batches_model_snapshot_id", ["model_snapshot_id"], False),
        ("ix_portfolio_rating_batches_scope_type", ["scope_type"], False),
        ("ix_portfolio_rating_batches_status", ["status"], False),
        ("ix_portfolio_rating_batches_result_hash", ["result_hash"], False),
        ("ix_portfolio_rating_batches_created_by", ["created_by"], False),
        ("ix_portfolio_rating_batches_created_at", ["created_at"], False),
        ("ix_portfolio_batches_template_created", ["template_key", "created_at"], False),
    ]:
        op.create_index(name, "portfolio_rating_batches", columns, unique=unique)


def downgrade() -> None:
    op.drop_table("portfolio_rating_batches")
