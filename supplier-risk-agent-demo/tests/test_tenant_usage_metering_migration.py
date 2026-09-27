from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from alembic import command
from alembic.config import Config


def test_0095_tenant_usage_metering_roundtrip() -> None:
    root = Path(__file__).resolve().parents[1]
    with TemporaryDirectory() as directory:
        path = Path(directory) / "platform.db"
        url = f"sqlite:///{path}"
        config = Config(str(root / "alembic.ini"))
        config.set_main_option("script_location", str(root / "migrations"))
        config.set_main_option("sqlalchemy.url", url)
        with patch.dict(os.environ, {"DATABASE_URL": url}):
            command.upgrade(config, "20260916_0094")
            command.upgrade(config, "20260917_0095")
            with sqlite3.connect(path) as connection:
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                assert {"tenant_usage_daily_records", "tenant_usage_statements"} <= tables
                assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            command.downgrade(config, "20260916_0094")
            with sqlite3.connect(path) as connection:
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                assert "tenant_usage_daily_records" not in tables
                assert "tenant_usage_statements" not in tables
                assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
