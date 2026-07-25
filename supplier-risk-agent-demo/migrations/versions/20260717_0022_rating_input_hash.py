"""Add integrity hash for persisted rating inputs.

Revision ID: 20260717_0022
Revises: 20260717_0021
"""

from __future__ import annotations

import hashlib
import json

from alembic import op
import sqlalchemy as sa


revision = "20260717_0022"
down_revision = "20260717_0021"
branch_labels = None
depends_on = None


def _content_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def upgrade() -> None:
    op.add_column("rating_runs", sa.Column("input_hash", sa.String(length=64), nullable=True))

    bind = op.get_bind()
    rating_runs = sa.table(
        "rating_runs",
        sa.column("id", sa.String(length=36)),
        sa.column("input_json", sa.JSON()),
        sa.column("input_hash", sa.String(length=64)),
    )
    rows = bind.execute(sa.select(rating_runs.c.id, rating_runs.c.input_json)).mappings()
    for row in rows:
        bind.execute(
            rating_runs.update()
            .where(rating_runs.c.id == row["id"])
            .values(input_hash=_content_hash(row["input_json"]))
        )

    with op.batch_alter_table("rating_runs") as batch_op:
        batch_op.alter_column("input_hash", existing_type=sa.String(length=64), nullable=False)
        batch_op.create_index("ix_rating_runs_input_hash", ["input_hash"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("rating_runs") as batch_op:
        batch_op.drop_index("ix_rating_runs_input_hash")
        batch_op.drop_column("input_hash")
