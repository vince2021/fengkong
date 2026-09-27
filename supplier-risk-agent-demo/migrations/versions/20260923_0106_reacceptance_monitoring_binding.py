"""Bind in-service reacceptance to immutable monitoring evidence.

Revision ID: 20260923_0106
Revises: 20260923_0105
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260923_0106"
down_revision = "20260923_0105"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("model_risk_reacceptances") as batch:
        batch.add_column(sa.Column("monitoring_run_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("monitoring_evidence_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("label_evidence_id", sa.String(128), nullable=True))
        batch.create_foreign_key(
            "fk_model_risk_reacceptance_monitoring_run", "model_monitoring_runs", ["monitoring_run_id"], ["id"], ondelete="RESTRICT"
        )
        for column in ("monitoring_run_id", "monitoring_evidence_hash", "label_evidence_id"):
            batch.create_index(f"ix_model_risk_reacceptances_{column}", [column])


def downgrade() -> None:
    with op.batch_alter_table("model_risk_reacceptances") as batch:
        for column in ("monitoring_run_id", "monitoring_evidence_hash", "label_evidence_id"):
            batch.drop_index(f"ix_model_risk_reacceptances_{column}")
        batch.drop_constraint("fk_model_risk_reacceptance_monitoring_run", type_="foreignkey")
        batch.drop_column("label_evidence_id")
        batch.drop_column("monitoring_evidence_hash")
        batch.drop_column("monitoring_run_id")
