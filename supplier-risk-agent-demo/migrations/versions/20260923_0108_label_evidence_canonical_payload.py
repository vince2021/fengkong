"""Persist versioned canonical evidence payloads for new tenant outcome labels.

Revision ID: 20260923_0108
Revises: 20260923_0107
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260923_0108"
down_revision = "20260923_0107"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenant_outcome_labels", sa.Column("evidence_schema_version", sa.String(64), nullable=True))
    op.add_column("tenant_outcome_labels", sa.Column("canonical_evidence_json", sa.JSON(), nullable=True))
    op.create_index("ix_tenant_outcome_labels_evidence_schema_version", "tenant_outcome_labels", ["evidence_schema_version"])


def downgrade() -> None:
    op.drop_index("ix_tenant_outcome_labels_evidence_schema_version", table_name="tenant_outcome_labels")
    op.drop_column("tenant_outcome_labels", "canonical_evidence_json")
    op.drop_column("tenant_outcome_labels", "evidence_schema_version")
