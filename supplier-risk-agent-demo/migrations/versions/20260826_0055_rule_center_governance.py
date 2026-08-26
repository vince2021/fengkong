"""rule_center: add governed scheduled activation

Revision ID: 20260826_0055
Revises: 20260825_0054
Create Date: 2026-08-26
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260826_0055"
down_revision = "20260825_0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    with op.batch_alter_table("model_changes") as batch_op:
        batch_op.add_column(sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index("ix_model_changes_effective_at", ["effective_at"], unique=False)

    if bind.dialect.name == "postgresql":
        op.create_index(
            "uq_rule_center_change_one_scheduled",
            "model_changes",
            ["entity_type", "template_key"],
            unique=True,
            postgresql_where=sa.text("status = 'scheduled' AND entity_type IN ('rule', 'rule_set', 'pipeline')"),
        )
    else:
        op.create_index(
            "uq_rule_center_change_one_scheduled",
            "model_changes",
            ["entity_type", "template_key"],
            unique=True,
            sqlite_where=sa.text("status = 'scheduled' AND entity_type IN ('rule', 'rule_set', 'pipeline')"),
        )


def downgrade() -> None:
    op.drop_index("uq_rule_center_change_one_scheduled", table_name="model_changes")
    with op.batch_alter_table("model_changes") as batch_op:
        batch_op.drop_index("ix_model_changes_effective_at")
        batch_op.drop_column("effective_at")
