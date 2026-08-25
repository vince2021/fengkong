"""add indicator factory definitions

Revision ID: 20260806_0053
Revises: 20260806_0052
"""

from alembic import op
import sqlalchemy as sa


revision = "20260806_0053"
down_revision = "20260806_0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = inspector.get_table_names()

    if "model_changes" in table_names:
        columns = {column["name"] for column in inspector.get_columns("model_changes")}
        unique_constraints = {
            constraint["name"]: constraint
            for constraint in inspector.get_unique_constraints("model_changes")
        }
        current_unique = unique_constraints.get("uq_model_change_candidate_version")
        expected_columns = {"entity_type", "template_key", "candidate_version"}
        needs_scoped_unique = (
            current_unique is None
            or set(current_unique.get("column_names") or []) != expected_columns
        )
        if "entity_type" not in columns or needs_scoped_unique:
            with op.batch_alter_table("model_changes") as batch_op:
                if "entity_type" not in columns:
                    batch_op.add_column(
                        sa.Column(
                            "entity_type",
                            sa.String(length=32),
                            nullable=False,
                            server_default="model",
                        )
                    )
                    batch_op.create_index(
                        "ix_model_changes_entity_type", ["entity_type"], unique=False
                    )
                if needs_scoped_unique:
                    if current_unique is not None:
                        batch_op.drop_constraint(
                            "uq_model_change_candidate_version", type_="unique"
                        )
                    batch_op.create_unique_constraint(
                        "uq_model_change_candidate_version",
                        ["entity_type", "template_key", "candidate_version"],
                    )

    if "indicator_definitions" not in table_names:
        op.create_table(
            "indicator_definitions",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("code", sa.String(length=128), nullable=False),
            sa.Column("name", sa.String(length=256), nullable=False),
            sa.Column("category", sa.String(length=64), nullable=False),
            sa.Column("layer", sa.String(length=16), nullable=False),
            sa.Column("data_type", sa.String(length=16), nullable=False),
            sa.Column("field_path", sa.String(length=512), nullable=True),
            sa.Column("expression", sa.Text(), nullable=True),
            sa.Column("dependencies", sa.JSON(), nullable=True),
            sa.Column("scoring_json", sa.JSON(), nullable=False),
            sa.Column("max_score", sa.Numeric(precision=10, scale=2), nullable=False),
            sa.Column(
                "default_weight", sa.Numeric(precision=10, scale=2), nullable=False
            ),
            sa.Column("source_references", sa.JSON(), nullable=True),
            sa.Column("seed_source", sa.String(length=32), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("row_version", sa.Integer(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by", sa.String(length=128), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "code", "version", name="uq_indicator_code_version"
            ),
        )
        op.create_index(
            "ix_indicator_definitions_code",
            "indicator_definitions",
            ["code"],
            unique=False,
        )
        op.create_index(
            "ix_indicator_definitions_category",
            "indicator_definitions",
            ["category"],
            unique=False,
        )
        op.create_index(
            "ix_indicator_definitions_is_active",
            "indicator_definitions",
            ["is_active"],
            unique=False,
        )
        if bind.dialect.name == "postgresql":
            op.create_index(
                "uq_indicator_single_active",
                "indicator_definitions",
                ["code", "is_active"],
                unique=True,
                postgresql_where=sa.text("is_active = true"),
            )
        else:
            op.create_index(
                "uq_indicator_single_active",
                "indicator_definitions",
                ["code", "is_active"],
                unique=True,
                sqlite_where=sa.text("is_active = 1"),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = inspector.get_table_names()

    if "indicator_definitions" in table_names:
        op.drop_table("indicator_definitions")

    if "model_changes" in table_names:
        columns = {column["name"] for column in inspector.get_columns("model_changes")}
        if "entity_type" in columns:
            with op.batch_alter_table("model_changes") as batch_op:
                index_names = {
                    index["name"]
                    for index in inspector.get_indexes("model_changes")
                }
                if "ix_model_changes_entity_type" in index_names:
                    batch_op.drop_index("ix_model_changes_entity_type")
                batch_op.drop_constraint(
                    "uq_model_change_candidate_version", type_="unique"
                )
                batch_op.create_unique_constraint(
                    "uq_model_change_candidate_version",
                    ["template_key", "candidate_version"],
                )
                batch_op.drop_column("entity_type")
