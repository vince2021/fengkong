from __future__ import annotations

import json
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
def database_at_0090():
    with TemporaryDirectory() as directory:
        path = Path(directory) / "platform.db"
        url = f"sqlite:///{path}"
        config = Config(str(PROJECT_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
        config.set_main_option("sqlalchemy.url", url)
        with patch.dict(os.environ, {"DATABASE_URL": url}):
            command.upgrade(config, "20260915_0090")
            yield config, path


def test_0091_product_package_and_entitlement_roundtrip() -> None:
    with database_at_0090() as (config, path):
        command.upgrade(config, "20260915_0091")
        with sqlite3.connect(path) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert {"product_packages", "tenant_entitlements"}.issubset(tables)
            connection.execute("INSERT INTO tenants(id,name,deployment_mode,status,data_region,row_version) VALUES('tenant-migration','迁移测试','saas','active','cn',1)")
            connection.execute(
                "INSERT INTO product_packages(id,code,version,name,description,status,is_active,environment_scopes_json,asset_catalog_json,quotas_json,expiry_policy,config_hash,change_reason,created_by,created_by_name,row_version) "
                "VALUES('package-1','PRO',1,'专业版','迁移产品包','published',1,?,?,?,?,?,'迁移测试','maker','maker',1)",
                (json.dumps(["production"]), json.dumps([]), json.dumps({"qps_limit": 20}), "block", "a" * 64),
            )
            connection.execute(
                "INSERT INTO tenant_entitlements(id,tenant_id,product_package_id,package_code,package_version,package_config_hash,package_snapshot_json,effective_quotas_json,initialized_assets_json,status,starts_at,expires_at,change_reason,created_by,created_by_name,row_version) "
                "VALUES('entitlement-1','tenant-migration','package-1','PRO',1,?,?,?,?, 'active','2026-01-01','2027-01-01','迁移测试','maker','maker',1)",
                ("a" * 64, json.dumps({}), json.dumps({"qps_limit": 20}), json.dumps([])),
            )
            connection.commit()
            foreign_keys = {(row[2], row[3], row[4]) for row in connection.execute("PRAGMA foreign_key_list(tenant_entitlements)")}
            assert ("tenants", "tenant_id", "id") in foreign_keys
            assert ("product_packages", "product_package_id", "id") in foreign_keys
            indexes = {row[1] for row in connection.execute("PRAGMA index_list(tenant_entitlements)")}
            assert "uq_tenant_entitlement_one_active" in indexes

        command.downgrade(config, "20260915_0090")
        with sqlite3.connect(path) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert "product_packages" not in tables
            assert "tenant_entitlements" not in tables
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
