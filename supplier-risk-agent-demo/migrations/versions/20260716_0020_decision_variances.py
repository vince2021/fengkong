"""Add approval decision variance register.

Revision ID: 20260716_0020
Revises: 20260716_0019
"""

from alembic import op
import sqlalchemy as sa


revision = "20260716_0020"
down_revision = "20260716_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "decision_variances",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("case_id", sa.String(length=128), nullable=False),
        sa.Column("counterparty_id", sa.String(length=128), nullable=False),
        sa.Column("counterparty_name", sa.String(length=255), nullable=False),
        sa.Column("rating_run_id", sa.String(length=36), nullable=True),
        sa.Column("model_snapshot_id", sa.String(length=36), nullable=True),
        sa.Column("direction", sa.String(length=32), nullable=False),
        sa.Column("materiality", sa.String(length=32), nullable=False),
        sa.Column("recommendation_json", sa.JSON(), nullable=False),
        sa.Column("decision_json", sa.JSON(), nullable=False),
        sa.Column("variance_json", sa.JSON(), nullable=False),
        sa.Column("reason_category", sa.String(length=64), nullable=True),
        sa.Column("reason_detail", sa.Text(), nullable=True),
        sa.Column("compensating_controls", sa.JSON(), nullable=False),
        sa.Column("decided_by", sa.String(length=128), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["approval_cases.case_id"]),
        sa.ForeignKeyConstraint(["rating_run_id"], ["rating_runs.id"]),
        sa.ForeignKeyConstraint(["model_snapshot_id"], ["model_snapshots.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", name="uq_decision_variance_case"),
    )
    op.create_index("ix_decision_variances_case_id", "decision_variances", ["case_id"], unique=True)
    op.create_index("ix_decision_variances_counterparty_id", "decision_variances", ["counterparty_id"], unique=False)
    op.create_index("ix_decision_variances_rating_run_id", "decision_variances", ["rating_run_id"], unique=False)
    op.create_index("ix_decision_variances_model_snapshot_id", "decision_variances", ["model_snapshot_id"], unique=False)
    op.create_index("ix_decision_variances_direction", "decision_variances", ["direction"], unique=False)
    op.create_index("ix_decision_variances_materiality", "decision_variances", ["materiality"], unique=False)
    op.create_index("ix_decision_variances_reason_category", "decision_variances", ["reason_category"], unique=False)
    op.create_index("ix_decision_variances_decided_by", "decision_variances", ["decided_by"], unique=False)
    op.create_index("ix_decision_variances_decided_at", "decision_variances", ["decided_at"], unique=False)
    op.create_index("ix_decision_variances_direction_materiality", "decision_variances", ["direction", "materiality", "decided_at"], unique=False)


def downgrade() -> None:
    op.drop_table("decision_variances")
