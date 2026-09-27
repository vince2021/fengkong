"""isolate replay evidence and freeze resolved assets by tenant

Revision ID: 20260915_0090
Revises: 20260915_0089
"""
from __future__ import annotations

import hashlib
import json

from alembic import op
import sqlalchemy as sa


revision = "20260915_0090"
down_revision = "20260915_0089"
branch_labels = None
depends_on = None


LEGACY_TENANT_ID = "tenant-demo-hengxin"
DATASETS = "rule_center_replay_datasets"
SNAPSHOTS = "rule_center_replay_dataset_snapshots"
REPLAYS = "rule_center_replay_runs"
COMPARISONS = "rule_center_replay_comparison_runs"
EXCEPTIONS = "rule_center_replay_comparison_exceptions"
NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}


def _hash(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json(value: object, default):
    if value is None:
        return default
    if isinstance(value, str):
        return json.loads(value)
    return value


def _replace_hashes(value: object, replacements: dict[str, str]) -> object:
    if isinstance(value, dict):
        return {key: _replace_hashes(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_hashes(item, replacements) for item in value]
    return replacements.get(value, value) if isinstance(value, str) else value


def _fk_name(table: str, columns: list[str]) -> str | None:
    for constraint in sa.inspect(op.get_bind()).get_foreign_keys(table):
        if constraint.get("constrained_columns") == columns:
            return constraint.get("name") or NAMING_CONVENTION["fk"] % {
                "table_name": table,
                "column_0_name": columns[0],
                "referred_table_name": constraint["referred_table"],
            }
    return None


def _drop_unique(batch, table: str, name: str) -> None:
    names = {
        item.get("name")
        for item in sa.inspect(op.get_bind()).get_unique_constraints(table)
    }
    if name in names:
        batch.drop_constraint(name, type_="unique")


def _snapshot_payload(row: sa.RowMapping, *, include_tenant: bool) -> dict:
    payload = {
        "dataset_id": row["dataset_id"],
        "version": row["version"],
        "source_name": row["source_name"],
        "schema_version": row["schema_version"],
        "as_of_date": row["as_of_date"],
        "evidence_reference": row["evidence_reference"],
        "data_classification": row["data_classification"],
        "field_mapping": _json(row["field_mapping_json"], {}),
        "label_field": row["label_field"],
        "observed_at_field": row["observed_at_field"],
        "samples": _json(row["samples_json"], []),
        "coverage": _json(row["coverage_json"], {}),
        "source_hash": row["source_hash"],
    }
    if include_tenant:
        payload = {"tenant_id": row["tenant_id"], **payload}
    return payload


def _legacy_comparison_assets(row: sa.RowMapping) -> dict:
    def side(name: str) -> dict:
        model = {
            "asset_type": "model",
            "key": row[f"{name}_model_key"],
            "version": row[f"{name}_model_version"],
            "source_scope": "historical_replay_pin",
        }
        pipeline = None
        if row[f"{name}_pipeline_code"] != "LEGACY-SCORECARD":
            pipeline = {
                "asset_type": "pipeline",
                "code": row[f"{name}_pipeline_code"],
                "version": row[f"{name}_pipeline_version"],
                "source_scope": "historical_replay_pin",
            }
        payload = {
            "model": model,
            "scorecard": None,
            "pipeline": pipeline,
            "rule_sets": [],
            "rules": [],
            "degraded_reason": "historical_pre_asset_resolution",
        }
        payload["resolution_hash"] = _hash(payload)
        return payload

    payload = {
        "schema_version": "tenant-replay-comparison-assets-v1",
        "tenant_id": row["tenant_id"],
        "champion": side("champion"),
        "challenger": side("challenger"),
        "capture_status": "historical_backfill",
    }
    payload["resolution_hash"] = _hash({
        "tenant_id": row["tenant_id"],
        "champion": payload["champion"]["resolution_hash"],
        "challenger": payload["challenger"]["resolution_hash"],
    })
    return payload


def _legacy_replay_assets(row: sa.RowMapping) -> dict:
    model = {
        "asset_type": "model",
        "key": row["model_key"],
        "version": row["model_version"],
        "source_scope": "historical_replay_pin",
    }
    payload = {
        "schema_version": "tenant-release-package-replay-assets-v1",
        "tenant_id": row["tenant_id"],
        "baseline": {
            "model": model,
            "scorecard": None,
            "pipeline": None,
            "rule_sets": [],
            "rules": [],
            "degraded_reason": "historical_pre_asset_resolution",
        },
        "candidate": {
            "model": model,
            "scorecard": None,
            "pipeline": {
                "asset_type": "pipeline",
                "code": row["pipeline_code"],
                "source_scope": "historical_replay_pin",
            },
            "rule_sets": [],
            "rules": [],
            "degraded_reason": "historical_pre_asset_resolution",
        },
        "package_config_hash": row["package_config_hash"],
        "capture_status": "historical_backfill",
    }
    payload["resolution_hash"] = _hash(payload)
    return payload


def _comparison_hash(row: sa.RowMapping, assets: dict, assets_hash: str, *, include_tenant: bool) -> str:
    payload = {
        "dataset_snapshot_id": row["dataset_snapshot_id"],
        "dataset_snapshot_hash": row["dataset_snapshot_hash"],
        "champion": {
            "model_key": row["champion_model_key"],
            "model_version": row["champion_model_version"],
            "pipeline_code": row["champion_pipeline_code"],
            "pipeline_version": row["champion_pipeline_version"],
        },
        "challenger": {
            "model_key": row["challenger_model_key"],
            "model_version": row["challenger_model_version"],
            "pipeline_code": row["challenger_pipeline_code"],
            "pipeline_version": row["challenger_pipeline_version"],
        },
        "segment_field": row["segment_field"],
        "evidence_level": row["evidence_level"],
        "config": _json(row["config_json"], {}),
        "metrics": _json(row["metrics_json"], {}),
        "details": _json(row["details_json"], []),
        "gate": _json(row["gate_json"], None),
    }
    if row["challenger_change_id"]:
        payload.update({
            "challenger_change_id": row["challenger_change_id"],
            "challenger_config_hash": row["challenger_config_hash"],
        })
    if include_tenant:
        payload = {
            "tenant_id": row["tenant_id"],
            **payload,
            "assets": assets,
            "assets_hash": assets_hash,
        }
    return _hash(payload)


def _replay_hash(row: sa.RowMapping, assets: dict, assets_hash: str, *, include_tenant: bool) -> str:
    payload = {
        "package_id": row["package_id"],
        "package_config_hash": row["package_config_hash"],
        "dataset_snapshot_id": row["dataset_snapshot_id"],
        "dataset_snapshot_hash": row["dataset_snapshot_hash"],
        "model_key": row["model_key"],
        "model_version": row["model_version"],
        "pipeline_code": row["pipeline_code"],
        "sample_ids": [item.get("counterparty_id") for item in _json(row["details_json"], [])],
        "thresholds": _json(row["thresholds_json"], {}),
        "metrics": _json(row["metrics_json"], {}),
        "details": _json(row["details_json"], []),
        "gate": _json(row["gate_json"], {}),
    }
    if include_tenant:
        payload = {
            "tenant_id": row["tenant_id"],
            **payload,
            "assets": assets,
            "assets_hash": assets_hash,
        }
    return _hash(payload)


def _backfill_and_rehash() -> None:
    connection = op.get_bind()
    metadata = sa.MetaData()
    snapshots = sa.Table(SNAPSHOTS, metadata, autoload_with=connection)
    hash_replacements: dict[str, str] = {}
    snapshot_tenants: dict[str, str] = {}
    for row in connection.execute(sa.select(snapshots)).mappings():
        new_hash = _hash(_snapshot_payload(row, include_tenant=True))
        hash_replacements[row["content_hash"]] = new_hash
        snapshot_tenants[row["id"]] = row["tenant_id"]
        connection.execute(
            snapshots.update().where(snapshots.c.id == row["id"]).values(content_hash=new_hash)
        )

    if sa.inspect(connection).has_table("scorecard_development_runs"):
        runs = sa.Table("scorecard_development_runs", metadata, autoload_with=connection)
        for row in connection.execute(sa.select(runs)).mappings():
            report = _replace_hashes(_json(row["report_json"], {}), hash_replacements)
            values = {
                "dataset_snapshot_hash": hash_replacements.get(row["dataset_snapshot_hash"], row["dataset_snapshot_hash"]),
                "validation_snapshot_hash": hash_replacements.get(row["validation_snapshot_hash"], row["validation_snapshot_hash"]),
                "oot_snapshot_hash": hash_replacements.get(row["oot_snapshot_hash"], row["oot_snapshot_hash"]),
                "report_json": report,
            }
            evidence = {
                "scorecard_asset_id": row["scorecard_asset_id"],
                "scorecard_code": row["scorecard_code"],
                "scorecard_version": row["scorecard_version"],
                "scorecard_config_hash": row["scorecard_config_hash"],
                "dataset_snapshot_id": row["dataset_snapshot_id"],
                "dataset_snapshot_hash": values["dataset_snapshot_hash"],
                "label_policy": _json(row["label_policy_json"], {}),
                "report": report,
                "validation_snapshot_id": row["validation_snapshot_id"],
                "validation_snapshot_hash": values["validation_snapshot_hash"],
                "oot_snapshot_id": row["oot_snapshot_id"],
                "oot_snapshot_hash": values["oot_snapshot_hash"],
            }
            if row["validation_policy_id"]:
                evidence.update({
                    "validation_policy_id": row["validation_policy_id"],
                    "validation_policy_hash": row["validation_policy_hash"],
                })
            values["evidence_hash"] = _hash(evidence)
            connection.execute(runs.update().where(runs.c.id == row["id"]).values(**values))

    if sa.inspect(connection).has_table("credit_calibration_runs"):
        runs = sa.Table("credit_calibration_runs", metadata, autoload_with=connection)
        for row in connection.execute(sa.select(runs)).mappings():
            report = _replace_hashes(_json(row["report_json"], {}), hash_replacements)
            snapshot = dict(report.get("snapshot") or {})
            snapshot["tenant_id"] = snapshot_tenants.get(row["dataset_snapshot_id"])
            report["snapshot"] = snapshot
            report["evidence_hash"] = _hash({
                key: value for key, value in report.items()
                if key not in {"generated_at", "evidence_hash"}
            })
            connection.execute(runs.update().where(runs.c.id == row["id"]).values(
                dataset_snapshot_hash=hash_replacements.get(row["dataset_snapshot_hash"], row["dataset_snapshot_hash"]),
                report_json=report,
                evidence_hash=report["evidence_hash"],
            ))

    comparisons = sa.Table(COMPARISONS, metadata, autoload_with=connection)
    comparison_updates: dict[str, tuple[str, str, str]] = {}
    for row in connection.execute(sa.select(comparisons)).mappings():
        values = dict(row)
        values["dataset_snapshot_hash"] = hash_replacements.get(row["dataset_snapshot_hash"], row["dataset_snapshot_hash"])
        assets = _legacy_comparison_assets(values)
        assets_hash = _hash(assets)
        evidence_hash = _comparison_hash(values, assets, assets_hash, include_tenant=True)
        comparison_updates[row["id"]] = (values["tenant_id"], evidence_hash, assets_hash)
        connection.execute(comparisons.update().where(comparisons.c.id == row["id"]).values(
            dataset_snapshot_hash=values["dataset_snapshot_hash"], asset_snapshot_json=assets,
            assets_hash=assets_hash, evidence_hash=evidence_hash,
        ))

    replays = sa.Table(REPLAYS, metadata, autoload_with=connection)
    for row in connection.execute(sa.select(replays)).mappings():
        values = dict(row)
        values["dataset_snapshot_hash"] = hash_replacements.get(row["dataset_snapshot_hash"], row["dataset_snapshot_hash"])
        assets = _legacy_replay_assets(values)
        assets_hash = _hash(assets)
        connection.execute(replays.update().where(replays.c.id == row["id"]).values(
            dataset_snapshot_hash=values["dataset_snapshot_hash"], asset_snapshot_json=assets,
            assets_hash=assets_hash, evidence_hash=_replay_hash(values, assets, assets_hash, include_tenant=True),
        ))

    exceptions = sa.Table(EXCEPTIONS, metadata, autoload_with=connection)
    for row in connection.execute(sa.select(exceptions)).mappings():
        tenant_id, comparison_hash, _ = comparison_updates[row["comparison_run_id"]]
        request_hash = _hash({
            "tenant_id": tenant_id,
            "comparison_run_id": row["comparison_run_id"],
            "comparison_evidence_hash": comparison_hash,
            "reason": row["reason"],
            "business_impact": row["business_impact"],
            "compensating_controls": row["compensating_controls"],
            "valid_until": row["valid_until"],
        })
        connection.execute(exceptions.update().where(exceptions.c.id == row["id"]).values(
            comparison_evidence_hash=comparison_hash, request_hash=request_hash,
        ))

    if sa.inspect(connection).has_table("model_changes"):
        changes = sa.Table("model_changes", metadata, autoload_with=connection)
        scorecard_runs = sa.Table("scorecard_development_runs", metadata, autoload_with=connection)
        scorecard_hashes = {
            row["id"]: row["evidence_hash"]
            for row in connection.execute(sa.select(scorecard_runs)).mappings()
        } if sa.inspect(connection).has_table("scorecard_development_runs") else {}
        calibration_runs = sa.Table("credit_calibration_runs", metadata, autoload_with=connection)
        calibration_reports = {
            row["id"]: _json(row["report_json"], {})
            for row in connection.execute(sa.select(calibration_runs)).mappings()
        } if sa.inspect(connection).has_table("credit_calibration_runs") else {}
        for row in connection.execute(sa.select(changes)).mappings():
            values = {}
            comparison_binding = _replace_hashes(_json(row["comparison_evidence_json"], {}), hash_replacements)
            if comparison_binding:
                update = comparison_updates.get(comparison_binding.get("comparison_run_id"))
                if update:
                    comparison_binding.update({
                        "tenant_id": update[0],
                        "comparison_evidence_hash": update[1],
                        "assets_hash": update[2],
                    })
                    unsigned = dict(comparison_binding)
                    unsigned.pop("binding_hash", None)
                    comparison_binding["binding_hash"] = _hash(unsigned)
                values["comparison_evidence_json"] = comparison_binding
            scorecard = _replace_hashes(_json(row["scorecard_validation_evidence_json"], {}), hash_replacements)
            if scorecard:
                run_id = scorecard.get("validation_run_id")
                scorecard["tenant_id"] = snapshot_tenants.get(scorecard.get("dataset_snapshot_id"))
                if run_id in scorecard_hashes:
                    scorecard["evidence_hash"] = scorecard_hashes[run_id]
                values.update({
                    "scorecard_validation_evidence_json": scorecard,
                    "scorecard_validation_binding_hash": _hash(scorecard),
                })
            calibration = _replace_hashes(_json(row["calibration_evidence_json"], {}), hash_replacements)
            if calibration:
                run_id = calibration.get("calibration_run_id")
                if run_id in calibration_reports:
                    calibration["analysis"] = calibration_reports[run_id]
                values.update({
                    "calibration_evidence_json": calibration,
                    "calibration_evidence_binding_hash": _hash(calibration),
                })
            if values:
                connection.execute(changes.update().where(changes.c.id == row["id"]).values(**values))


def upgrade() -> None:
    op.get_bind().execute(sa.text(
        "INSERT INTO tenants (id, name, deployment_mode, status, data_region, row_version) "
        "SELECT :id, :name, 'saas', 'active', 'cn', 1 "
        "WHERE NOT EXISTS (SELECT 1 FROM tenants WHERE id = :id)"
    ), {"id": LEGACY_TENANT_ID, "name": "恒信演示租户"})
    for table in (DATASETS, SNAPSHOTS, REPLAYS, COMPARISONS, EXCEPTIONS):
        op.add_column(table, sa.Column("tenant_id", sa.String(128), nullable=True))
        op.execute(sa.text(f"UPDATE {table} SET tenant_id = :tenant_id WHERE tenant_id IS NULL").bindparams(tenant_id=LEGACY_TENANT_ID))
    for table in (REPLAYS, COMPARISONS):
        op.add_column(table, sa.Column("asset_snapshot_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
        op.add_column(table, sa.Column("assets_hash", sa.String(64), nullable=False, server_default="0" * 64))

    with op.batch_alter_table(COMPARISONS) as batch:
        batch.alter_column("champion_pipeline_version", existing_type=sa.Integer(), type_=sa.String(128), existing_nullable=True)
        batch.alter_column("challenger_pipeline_version", existing_type=sa.Integer(), type_=sa.String(128), existing_nullable=True)

    _backfill_and_rehash()

    with op.batch_alter_table(DATASETS, naming_convention=NAMING_CONVENTION) as batch:
        _drop_unique(batch, DATASETS, "uq_rule_center_replay_dataset_code")
        batch.alter_column("tenant_id", existing_type=sa.String(128), nullable=False)
        batch.create_foreign_key("fk_replay_dataset_tenant", "tenants", ["tenant_id"], ["id"], ondelete="CASCADE")
        batch.create_unique_constraint("uq_rule_center_replay_dataset_tenant_id", ["tenant_id", "id"])
        batch.create_unique_constraint("uq_rule_center_replay_dataset_tenant_code", ["tenant_id", "code"])
    op.drop_index("ix_rule_center_replay_datasets_code", table_name=DATASETS)
    op.create_index("ix_rule_center_replay_datasets_code", DATASETS, ["code"])
    op.create_index("ix_rule_center_replay_datasets_tenant_id", DATASETS, ["tenant_id"])
    op.create_index("ix_rule_center_replay_dataset_tenant_status", DATASETS, ["tenant_id", "status", "created_at"])

    snapshot_fk = _fk_name(SNAPSHOTS, ["dataset_id"])
    with op.batch_alter_table(SNAPSHOTS, naming_convention=NAMING_CONVENTION) as batch:
        _drop_unique(batch, SNAPSHOTS, "uq_rule_center_replay_dataset_version")
        _drop_unique(batch, SNAPSHOTS, "uq_rule_center_replay_dataset_source")
        if snapshot_fk:
            batch.drop_constraint(snapshot_fk, type_="foreignkey")
        batch.alter_column("tenant_id", existing_type=sa.String(128), nullable=False)
        batch.create_foreign_key("fk_replay_snapshot_tenant", "tenants", ["tenant_id"], ["id"], ondelete="CASCADE")
        batch.create_foreign_key("fk_rule_center_replay_snapshot_tenant_dataset", DATASETS, ["tenant_id", "dataset_id"], ["tenant_id", "id"], ondelete="CASCADE")
        batch.create_unique_constraint("uq_rule_center_replay_snapshot_tenant_id", ["tenant_id", "id"])
        batch.create_unique_constraint("uq_rule_center_replay_dataset_version", ["tenant_id", "dataset_id", "version"])
        batch.create_unique_constraint("uq_rule_center_replay_dataset_source", ["tenant_id", "dataset_id", "source_hash"])
    op.drop_index("ix_rule_center_replay_snapshot_dataset_created", table_name=SNAPSHOTS)
    op.create_index("ix_rule_center_replay_dataset_snapshots_tenant_id", SNAPSHOTS, ["tenant_id"])
    op.create_index("ix_rule_center_replay_snapshot_tenant_dataset_created", SNAPSHOTS, ["tenant_id", "dataset_id", "created_at"])

    for table, old_columns, fk_name, tenant_fk, composite_fk, target, ondelete in (
        (REPLAYS, ["dataset_snapshot_id"], "fk_rule_center_replay_snapshot", "fk_replay_run_tenant", "fk_rule_center_replay_run_tenant_snapshot", SNAPSHOTS, "RESTRICT"),
        (COMPARISONS, ["dataset_snapshot_id"], None, "fk_replay_comparison_tenant", "fk_rule_center_replay_comparison_tenant_snapshot", SNAPSHOTS, "RESTRICT"),
        (EXCEPTIONS, ["comparison_run_id"], None, "fk_replay_exception_tenant", "fk_replay_comparison_exception_tenant_run", COMPARISONS, "CASCADE"),
    ):
        old_fk = fk_name or _fk_name(table, old_columns)
        with op.batch_alter_table(table, naming_convention=NAMING_CONVENTION) as batch:
            if old_fk:
                batch.drop_constraint(old_fk, type_="foreignkey")
            batch.alter_column("tenant_id", existing_type=sa.String(128), nullable=False)
            batch.create_foreign_key(tenant_fk, "tenants", ["tenant_id"], ["id"], ondelete="CASCADE")
            batch.create_foreign_key(composite_fk, target, ["tenant_id", old_columns[0]], ["tenant_id", "id"], ondelete=ondelete)

    with op.batch_alter_table(COMPARISONS) as batch:
        batch.create_unique_constraint("uq_rule_center_replay_comparison_tenant_id", ["tenant_id", "id"])

    for table in (REPLAYS, COMPARISONS, EXCEPTIONS):
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
    op.drop_index("ix_rule_center_replay_package_created", table_name=REPLAYS)
    op.create_index("ix_rule_center_replay_tenant_package_created", REPLAYS, ["tenant_id", "package_id", "created_at"])
    op.drop_index("ix_rule_center_replay_comparison_snapshot_created", table_name=COMPARISONS)
    op.create_index("ix_rule_center_replay_comparison_tenant_snapshot_created", COMPARISONS, ["tenant_id", "dataset_snapshot_id", "created_at"])
    op.drop_index("ix_replay_comparison_exception_run_created", table_name=EXCEPTIONS)
    op.create_index("ix_replay_comparison_exception_tenant_run_created", EXCEPTIONS, ["tenant_id", "comparison_run_id", "created_at"])
    op.create_index("ix_rule_center_replay_runs_assets_hash", REPLAYS, ["assets_hash"])
    op.create_index("ix_rule_center_replay_comparison_runs_assets_hash", COMPARISONS, ["assets_hash"])
    for table in (REPLAYS, COMPARISONS):
        with op.batch_alter_table(table) as batch:
            batch.alter_column("asset_snapshot_json", server_default=None)
            batch.alter_column("assets_hash", server_default=None)


def _validate_downgrade() -> None:
    duplicate = op.get_bind().execute(sa.text(
        f"SELECT code FROM {DATASETS} GROUP BY code HAVING COUNT(*) > 1 LIMIT 1"
    )).first()
    if duplicate:
        raise RuntimeError(
            f"Cannot downgrade replay datasets: tenant-scoped code {duplicate[0]!r} "
            "is duplicated and cannot satisfy the previous global uniqueness rule"
        )


def downgrade() -> None:
    _validate_downgrade()
    connection = op.get_bind()
    metadata = sa.MetaData()
    snapshots = sa.Table(SNAPSHOTS, metadata, autoload_with=connection)
    replacements = {}
    for row in connection.execute(sa.select(snapshots)).mappings():
        old_hash = row["content_hash"]
        new_hash = _hash(_snapshot_payload(row, include_tenant=False))
        replacements[old_hash] = new_hash
        connection.execute(snapshots.update().where(snapshots.c.id == row["id"]).values(content_hash=new_hash))

    comparisons = sa.Table(COMPARISONS, metadata, autoload_with=connection)
    for row in connection.execute(sa.select(comparisons)).mappings():
        values = dict(row)
        values["dataset_snapshot_hash"] = replacements.get(row["dataset_snapshot_hash"], row["dataset_snapshot_hash"])
        connection.execute(comparisons.update().where(comparisons.c.id == row["id"]).values(
            dataset_snapshot_hash=values["dataset_snapshot_hash"],
            evidence_hash=_comparison_hash(values, {}, "", include_tenant=False),
        ))
    replays = sa.Table(REPLAYS, metadata, autoload_with=connection)
    for row in connection.execute(sa.select(replays)).mappings():
        values = dict(row)
        values["dataset_snapshot_hash"] = replacements.get(row["dataset_snapshot_hash"], row["dataset_snapshot_hash"])
        connection.execute(replays.update().where(replays.c.id == row["id"]).values(
            dataset_snapshot_hash=values["dataset_snapshot_hash"],
            evidence_hash=_replay_hash(values, {}, "", include_tenant=False),
        ))

    for name, table in (
        ("ix_rule_center_replay_runs_assets_hash", REPLAYS),
        ("ix_rule_center_replay_comparison_runs_assets_hash", COMPARISONS),
        ("ix_rule_center_replay_tenant_package_created", REPLAYS),
        ("ix_rule_center_replay_comparison_tenant_snapshot_created", COMPARISONS),
        ("ix_replay_comparison_exception_tenant_run_created", EXCEPTIONS),
        ("ix_rule_center_replay_snapshot_tenant_dataset_created", SNAPSHOTS),
        ("ix_rule_center_replay_dataset_tenant_status", DATASETS),
    ):
        op.drop_index(name, table_name=table)
    for table in (REPLAYS, COMPARISONS, EXCEPTIONS):
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
    op.drop_index("ix_rule_center_replay_dataset_snapshots_tenant_id", table_name=SNAPSHOTS)
    op.drop_index("ix_rule_center_replay_datasets_tenant_id", table_name=DATASETS)

    with op.batch_alter_table(EXCEPTIONS) as batch:
        batch.drop_constraint("fk_replay_comparison_exception_tenant_run", type_="foreignkey")
        batch.drop_constraint("fk_replay_exception_tenant", type_="foreignkey")
        batch.create_foreign_key("fk_replay_exception_comparison_run", COMPARISONS, ["comparison_run_id"], ["id"], ondelete="CASCADE")
        batch.drop_column("tenant_id")
    with op.batch_alter_table(COMPARISONS) as batch:
        batch.drop_constraint("uq_rule_center_replay_comparison_tenant_id", type_="unique")
        batch.drop_constraint("fk_rule_center_replay_comparison_tenant_snapshot", type_="foreignkey")
        batch.drop_constraint("fk_replay_comparison_tenant", type_="foreignkey")
        batch.create_foreign_key("fk_replay_comparison_snapshot", SNAPSHOTS, ["dataset_snapshot_id"], ["id"], ondelete="RESTRICT")
        batch.alter_column("champion_pipeline_version", existing_type=sa.String(128), type_=sa.Integer(), existing_nullable=True)
        batch.alter_column("challenger_pipeline_version", existing_type=sa.String(128), type_=sa.Integer(), existing_nullable=True)
        batch.drop_column("assets_hash")
        batch.drop_column("asset_snapshot_json")
        batch.drop_column("tenant_id")
    with op.batch_alter_table(REPLAYS) as batch:
        batch.drop_constraint("fk_rule_center_replay_run_tenant_snapshot", type_="foreignkey")
        batch.drop_constraint("fk_replay_run_tenant", type_="foreignkey")
        batch.create_foreign_key("fk_rule_center_replay_snapshot", SNAPSHOTS, ["dataset_snapshot_id"], ["id"], ondelete="RESTRICT")
        batch.drop_column("assets_hash")
        batch.drop_column("asset_snapshot_json")
        batch.drop_column("tenant_id")
    with op.batch_alter_table(SNAPSHOTS) as batch:
        batch.drop_constraint("uq_rule_center_replay_snapshot_tenant_id", type_="unique")
        batch.drop_constraint("uq_rule_center_replay_dataset_version", type_="unique")
        batch.drop_constraint("uq_rule_center_replay_dataset_source", type_="unique")
        batch.drop_constraint("fk_rule_center_replay_snapshot_tenant_dataset", type_="foreignkey")
        batch.drop_constraint("fk_replay_snapshot_tenant", type_="foreignkey")
        batch.create_foreign_key("fk_replay_snapshot_dataset", DATASETS, ["dataset_id"], ["id"], ondelete="CASCADE")
        batch.create_unique_constraint("uq_rule_center_replay_dataset_version", ["dataset_id", "version"])
        batch.create_unique_constraint("uq_rule_center_replay_dataset_source", ["dataset_id", "source_hash"])
        batch.drop_column("tenant_id")
    with op.batch_alter_table(DATASETS) as batch:
        batch.drop_constraint("uq_rule_center_replay_dataset_tenant_id", type_="unique")
        batch.drop_constraint("uq_rule_center_replay_dataset_tenant_code", type_="unique")
        batch.drop_constraint("fk_replay_dataset_tenant", type_="foreignkey")
        batch.create_unique_constraint("uq_rule_center_replay_dataset_code", ["code"])
        batch.drop_column("tenant_id")

    op.create_index("ix_rule_center_replay_snapshot_dataset_created", SNAPSHOTS, ["dataset_id", "created_at"])
    op.create_index("ix_rule_center_replay_package_created", REPLAYS, ["package_id", "created_at"])
    op.create_index("ix_rule_center_replay_comparison_snapshot_created", COMPARISONS, ["dataset_snapshot_id", "created_at"])
    op.create_index("ix_replay_comparison_exception_run_created", EXCEPTIONS, ["comparison_run_id", "created_at"])
    op.drop_index("ix_rule_center_replay_datasets_code", table_name=DATASETS)
    op.create_index("ix_rule_center_replay_datasets_code", DATASETS, ["code"], unique=True)
