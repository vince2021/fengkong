"""freeze tenant runtime asset evidence on executions

Revision ID: 20260915_0089
Revises: 20260908_0088
"""
from __future__ import annotations

import hashlib
import json

from alembic import op
import sqlalchemy as sa


revision = "20260915_0089"
down_revision = "20260908_0088"
branch_labels = None
depends_on = None


TABLES = ("rating_runs", "portfolio_rating_batches", "decision_jobs")


def _hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _legacy_snapshot(kind: str, row: sa.RowMapping, model: sa.RowMapping | None = None) -> dict:
    model_evidence = {
        "asset_type": "model",
        "key": row.get("template_key"),
        "version": row.get("model_version") or (model.get("model_version") if model else None),
        "asset_id": row.get("model_snapshot_id"),
        "config_hash": model.get("config_hash") if model else None,
        "source_scope": "legacy_model_snapshot",
    }
    payload = {
        "schema_version": "tenant-runtime-assets-v1",
        "capture_status": "historical_backfill",
        "execution_type": kind,
        "model": model_evidence,
        "scorecard": None,
        "pipeline": None,
        "rule_sets": [],
        "rules": [],
        "degraded_reason": "historical_pre_tenant_resolution",
    }
    payload["resolution_hash"] = _hash(payload)
    return payload


def upgrade() -> None:
    zero_hash = "0" * 64
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("asset_snapshot_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
            batch.add_column(sa.Column("assets_hash", sa.String(length=64), nullable=False, server_default=zero_hash))
        op.create_index(f"ix_{table}_assets_hash", table, ["assets_hash"])

    connection = op.get_bind()
    metadata = sa.MetaData()
    snapshots = sa.Table("model_snapshots", metadata, autoload_with=connection)
    snapshot_map = {row["id"]: row for row in connection.execute(sa.select(snapshots)).mappings()}

    for table_name, kind in (
        ("rating_runs", "rating"),
        ("portfolio_rating_batches", "portfolio_rating"),
    ):
        table = sa.Table(table_name, metadata, autoload_with=connection)
        for row in connection.execute(sa.select(table)).mappings():
            snapshot = _legacy_snapshot(kind, row, snapshot_map.get(row.get("model_snapshot_id")))
            connection.execute(
                table.update().where(table.c.id == row["id"]).values(
                    asset_snapshot_json=snapshot,
                    assets_hash=_hash(snapshot),
                )
            )

    jobs = sa.Table("decision_jobs", metadata, autoload_with=connection)
    for row in connection.execute(sa.select(jobs)).mappings():
        snapshot = {
            "schema_version": "tenant-runtime-assets-v1",
            "capture_status": "historical_unresolved",
            "execution_type": "decision_job",
            "job_id": row["id"],
            "degraded_reason": "historical_pre_tenant_resolution",
        }
        snapshot["resolution_hash"] = _hash(snapshot)
        connection.execute(
            jobs.update().where(jobs.c.id == row["id"]).values(
                asset_snapshot_json=snapshot,
                assets_hash=_hash(snapshot),
            )
        )

    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.alter_column("asset_snapshot_json", server_default=None)
            batch.alter_column("assets_hash", server_default=None)


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_index(f"ix_{table}_assets_hash", table_name=table)
        with op.batch_alter_table(table) as batch:
            batch.drop_column("assets_hash")
            batch.drop_column("asset_snapshot_json")
