from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from alembic import command
from alembic.config import Config


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def database_at_0092():
    with TemporaryDirectory() as directory:
        path = Path(directory) / "platform.db"
        url = f"sqlite:///{path}"
        config = Config(str(PROJECT_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
        config.set_main_option("sqlalchemy.url", url)
        with patch.dict(os.environ, {"DATABASE_URL": url}):
            command.upgrade(config, "20260915_0092")
            yield config, path


def test_0093_entitlement_lifecycle_roundtrip() -> None:
    with database_at_0092() as (config, path):
        command.upgrade(config, "20260916_0093")
        with sqlite3.connect(path) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert "tenant_entitlement_lifecycle_runs" in tables
            entitlement_columns = {row[1] for row in connection.execute("PRAGMA table_info(tenant_entitlements)")}
            assert "expired_at" in entitlement_columns
            indexes = list(connection.execute("PRAGMA index_list(tenant_entitlement_lifecycle_runs)"))
            assert any(
                row[2] == 1
                and [column[2] for column in connection.execute(f"PRAGMA index_info('{row[1]}')")] == ["run_key"]
                for row in indexes
            )
            foreign_keys = {(row[2], row[3], row[4]) for row in connection.execute("PRAGMA foreign_key_list(tenant_entitlement_lifecycle_runs)")}
            assert ("tenant_entitlement_lifecycle_runs", "retry_of_run_id", "id") in foreign_keys
            assert ("tenant_entitlement_lifecycle_runs", "resolved_by_run_id", "id") in foreign_keys

        command.downgrade(config, "20260915_0092")
        with sqlite3.connect(path) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert "tenant_entitlement_lifecycle_runs" not in tables
            entitlement_columns = {row[1] for row in connection.execute("PRAGMA table_info(tenant_entitlements)")}
            assert "expired_at" not in entitlement_columns
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
