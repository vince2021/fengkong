"""rule_center: add rule_definitions, rule_set_definitions, decision_pipeline_definitions

Revision ID: 20260825_0054
Revises: 20260806_0053
Create Date: 2026-08-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260825_0054"
down_revision = "20260806_0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    op.create_table(
        "rule_definitions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("rule_type", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("conditions_json", sa.JSON(), nullable=False),
        sa.Column("condition_relation", sa.String(length=8), nullable=False, server_default="all"),
        sa.Column("actions_json", sa.JSON(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="999"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", "version", name="uq_rule_code_version"),
    )
    op.create_index("ix_rule_definitions_code", "rule_definitions", ["code"], unique=False)
    op.create_index("ix_rule_definitions_rule_type", "rule_definitions", ["rule_type"], unique=False)
    op.create_index("ix_rule_definitions_is_active", "rule_definitions", ["is_active"], unique=False)
    if bind.dialect.name == "postgresql":
        op.create_index(
            "uq_rule_single_active",
            "rule_definitions",
            ["code", "is_active"],
            unique=True,
            postgresql_where=sa.text("is_active = true"),
        )
    else:
        op.create_index(
            "uq_rule_single_active",
            "rule_definitions",
            ["code", "is_active"],
            unique=True,
            sqlite_where=sa.text("is_active = 1"),
        )

    op.create_table(
        "rule_set_definitions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("rule_codes", sa.JSON(), nullable=False),
        sa.Column("evaluation_strategy", sa.String(length=32), nullable=False, server_default="most_restrictive"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", "version", name="uq_rule_set_code_version"),
    )
    op.create_index("ix_rule_set_definitions_code", "rule_set_definitions", ["code"], unique=False)
    op.create_index("ix_rule_set_definitions_is_active", "rule_set_definitions", ["is_active"], unique=False)
    if bind.dialect.name == "postgresql":
        op.create_index(
            "uq_rule_set_single_active",
            "rule_set_definitions",
            ["code", "is_active"],
            unique=True,
            postgresql_where=sa.text("is_active = true"),
        )
    else:
        op.create_index(
            "uq_rule_set_single_active",
            "rule_set_definitions",
            ["code", "is_active"],
            unique=True,
            sqlite_where=sa.text("is_active = 1"),
        )

    op.create_table(
        "decision_pipeline_definitions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("stages_json", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", "version", name="uq_pipeline_code_version"),
    )
    op.create_index("ix_decision_pipeline_definitions_code", "decision_pipeline_definitions", ["code"], unique=False)
    op.create_index("ix_decision_pipeline_definitions_is_active", "decision_pipeline_definitions", ["is_active"], unique=False)
    if bind.dialect.name == "postgresql":
        op.create_index(
            "uq_pipeline_single_active",
            "decision_pipeline_definitions",
            ["code", "is_active"],
            unique=True,
            postgresql_where=sa.text("is_active = true"),
        )
    else:
        op.create_index(
            "uq_pipeline_single_active",
            "decision_pipeline_definitions",
            ["code", "is_active"],
            unique=True,
            sqlite_where=sa.text("is_active = 1"),
        )


def downgrade() -> None:
    op.drop_table("decision_pipeline_definitions")
    op.drop_table("rule_set_definitions")
    op.drop_table("rule_definitions")
