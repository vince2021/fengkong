from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
from alembic import command
from alembic.config import Config


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REVISION = "20260915_0090"


@contextmanager
def database_at_0089():
    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "platform.db"
        url = f"sqlite:///{database_path}"
        config = Config(str(PROJECT_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
        config.set_main_option("sqlalchemy.url", url)
        with patch.dict(os.environ, {"DATABASE_URL": url}):
            command.upgrade(config, "20260915_0089")
            yield config, database_path


def insert_tenant(connection: sqlite3.Connection, tenant_id: str) -> None:
    connection.execute(
        "INSERT OR IGNORE INTO tenants(id,name,deployment_mode,status,data_region,row_version) "
        "VALUES(?,?, 'saas','active','cn',1)",
        (tenant_id, tenant_id),
    )


def insert_legacy_dataset(connection: sqlite3.Connection, dataset_id: str, code: str) -> None:
    connection.execute(
        "INSERT INTO rule_center_replay_datasets"
        "(id,code,name,description,status,created_by,created_by_name) "
        "VALUES(?,?,?,'migration fixture','active','test','test')",
        (dataset_id, code, code),
    )
    connection.execute(
        "INSERT INTO rule_center_replay_dataset_snapshots"
        "(id,dataset_id,version,source_name,schema_version,as_of_date,evidence_reference,"
        "data_classification,field_mapping_json,label_field,observed_at_field,sample_count,"
        "samples_json,coverage_json,source_hash,content_hash,created_by,created_by_name) "
        "VALUES(?,?,1,'fixture','1','2026-06-30','test://migration','synthetic','{}',NULL,NULL,1,?,?,?,?,'test','test')",
        (
            f"snapshot-{dataset_id}",
            dataset_id,
            json.dumps([{"sample": {"id": dataset_id, "name": code, "counterparty_type": "supplier"}}]),
            json.dumps({"overall_field_coverage_rate": 1}),
            f"source-{dataset_id}".ljust(64, "0")[:64],
            f"content-{dataset_id}".ljust(64, "0")[:64],
        ),
    )


def test_0090_roundtrip_backfills_tenant_and_rehashes_snapshot() -> None:
    with database_at_0089() as (config, database_path):
        with sqlite3.connect(database_path) as connection:
            insert_tenant(connection, "tenant-demo-hengxin")
            insert_legacy_dataset(connection, "dataset-primary", "MIGRATION-HISTORY")
            previous_hash = connection.execute(
                "SELECT content_hash FROM rule_center_replay_dataset_snapshots"
            ).fetchone()[0]
            connection.commit()

        command.upgrade(config, REVISION)
        with sqlite3.connect(database_path) as connection:
            row = connection.execute(
                "SELECT tenant_id,content_hash FROM rule_center_replay_dataset_snapshots"
            ).fetchone()
            assert row[0] == "tenant-demo-hengxin"
            assert row[1] != previous_hash
            foreign_keys = connection.execute(
                "PRAGMA foreign_key_list(rule_center_replay_dataset_snapshots)"
            ).fetchall()
            grouped = {(item[2], item[3], item[4]) for item in foreign_keys}
            assert ("rule_center_replay_datasets", "tenant_id", "tenant_id") in grouped
            assert ("rule_center_replay_datasets", "dataset_id", "id") in grouped

        command.downgrade(config, "20260915_0089")
        with sqlite3.connect(database_path) as connection:
            columns = {
                row[1] for row in connection.execute(
                    "PRAGMA table_info(rule_center_replay_datasets)"
                ).fetchall()
            }
            assert "tenant_id" not in columns
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_0090_downgrade_rejects_cross_tenant_duplicate_dataset_codes() -> None:
    with database_at_0089() as (config, database_path):
        with sqlite3.connect(database_path) as connection:
            insert_tenant(connection, "tenant-demo-hengxin")
            insert_tenant(connection, "tenant-demo-alt")
            connection.commit()
        command.upgrade(config, REVISION)
        with sqlite3.connect(database_path) as connection:
            connection.execute(
                "INSERT INTO rule_center_replay_datasets"
                "(id,tenant_id,code,name,description,status,created_by,created_by_name) "
                "VALUES('dataset-a','tenant-demo-hengxin','SHARED','A','A','active','test','test')"
            )
            connection.execute(
                "INSERT INTO rule_center_replay_datasets"
                "(id,tenant_id,code,name,description,status,created_by,created_by_name) "
                "VALUES('dataset-b','tenant-demo-alt','SHARED','B','B','active','test','test')"
            )
            connection.commit()

        with pytest.raises(RuntimeError, match="tenant-scoped code 'SHARED'"):
            command.downgrade(config, "20260915_0089")
