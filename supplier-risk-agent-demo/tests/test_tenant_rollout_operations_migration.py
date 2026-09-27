from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from alembic import command
from alembic.config import Config


def test_0094_rollout_operations_roundtrip() -> None:
    root = Path(__file__).resolve().parents[1]
    with TemporaryDirectory() as directory:
        path = Path(directory) / "platform.db"
        url = f"sqlite:///{path}"
        config = Config(str(root / "alembic.ini"))
        config.set_main_option("script_location", str(root / "migrations"))
        config.set_main_option("sqlalchemy.url", url)
        with patch.dict(os.environ, {"DATABASE_URL": url}):
            command.upgrade(config, "20260916_0093")
            command.upgrade(config, "20260916_0094")
            with sqlite3.connect(path) as connection:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(tenant_rollout_policies)")}
                assert {"incident_status", "incident_evaluation_id", "resolution_requested_by", "resolved_at"} <= columns
                assert "tenant_rollout_scans" in {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            command.downgrade(config, "20260916_0093")
            with sqlite3.connect(path) as connection:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(tenant_rollout_policies)")}
                assert "incident_status" not in columns
                assert "tenant_rollout_scans" not in {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
