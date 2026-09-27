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
def database_at_0091():
    with TemporaryDirectory() as directory:
        path = Path(directory) / "platform.db"
        url = f"sqlite:///{path}"
        config = Config(str(PROJECT_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
        config.set_main_option("sqlalchemy.url", url)
        with patch.dict(os.environ, {"DATABASE_URL": url}):
            command.upgrade(config, "20260915_0091")
            yield config, path


def test_0092_tenant_rollout_roundtrip() -> None:
    with database_at_0091() as (config, path):
        command.upgrade(config, "20260915_0092")
        with sqlite3.connect(path) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert {"tenant_rollout_policies", "tenant_routing_decisions", "tenant_rollout_evaluations"}.issubset(tables)
            policy_indexes = {row[1] for row in connection.execute("PRAGMA index_list(tenant_rollout_policies)")}
            assert "uq_tenant_rollout_one_active_model" in policy_indexes
            routing_indexes = {row[1] for row in connection.execute("PRAGMA index_list(tenant_routing_decisions)")}
            assert "ix_tenant_routing_policy_arm_created" in routing_indexes
            policy_foreign_keys = {(row[2], row[3], row[4]) for row in connection.execute("PRAGMA foreign_key_list(tenant_rollout_policies)")}
            assert ("tenants", "tenant_id", "id") in policy_foreign_keys
            assert ("rule_center_replay_comparison_runs", "comparison_run_id", "id") in policy_foreign_keys
            routing_foreign_keys = {(row[2], row[3], row[4]) for row in connection.execute("PRAGMA foreign_key_list(tenant_routing_decisions)")}
            assert ("tenant_rollout_policies", "policy_id", "id") in routing_foreign_keys

        command.downgrade(config, "20260915_0091")
        with sqlite3.connect(path) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert "tenant_rollout_policies" not in tables
            assert "tenant_routing_decisions" not in tables
            assert "tenant_rollout_evaluations" not in tables
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
