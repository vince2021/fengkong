from __future__ import annotations

import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from alembic import command
from alembic.config import Config


class TenantOutcomeMigrationTest(unittest.TestCase):
    def test_upgrade_and_downgrade(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "migration.db"
            config = Config(str(root / "alembic.ini"))
            config.set_main_option("script_location", str(root / "migrations"))
            config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
            command.upgrade(config, "20260919_0098")
            with sqlite3.connect(path) as connection:
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertIn("tenant_outcome_labels", tables)
                self.assertIn("tenant_supervised_evaluations", tables)
                self.assertIn("tenant_outcome_import_batches", tables)
                self.assertIn("tenant_outcome_label_definitions", tables)
                self.assertIn("tenant_supervised_upgrade_decisions", tables)
                label_columns = {row[1] for row in connection.execute("PRAGMA table_info('tenant_outcome_labels')")}
                evaluation_columns = {row[1] for row in connection.execute("PRAGMA table_info('tenant_supervised_evaluations')")}
                self.assertTrue({"record_status", "supersedes_label_id", "superseded_by_label_id", "import_batch_id", "label_definition_id", "label_definition_version", "label_definition_hash"}.issubset(label_columns))
                self.assertTrue({"status", "governance_decision", "row_version", "review_comment", "label_definition_id", "label_definition_version", "label_definition_hash"}.issubset(evaluation_columns))
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            command.downgrade(config, "20260917_0097")
            with sqlite3.connect(path) as connection:
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertIn("tenant_outcome_labels", tables)
                self.assertIn("tenant_supervised_evaluations", tables)
                self.assertIn("tenant_outcome_import_batches", tables)
                self.assertNotIn("tenant_outcome_label_definitions", tables)
                self.assertNotIn("tenant_supervised_upgrade_decisions", tables)
                self.assertNotIn("label_definition_id", {row[1] for row in connection.execute("PRAGMA table_info('tenant_outcome_labels')")})
                self.assertNotIn("label_definition_id", {row[1] for row in connection.execute("PRAGMA table_info('tenant_supervised_evaluations')")})
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_supervised_validation_binding_roundtrip(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "migration-0099.db"
            config = Config(str(root / "alembic.ini"))
            config.set_main_option("script_location", str(root / "migrations"))
            config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
            command.upgrade(config, "20260921_0099")
            with sqlite3.connect(path) as connection:
                columns = {row[1] for row in connection.execute("PRAGMA table_info('model_changes')")}
                self.assertTrue({"supervised_validation_evidence_json", "supervised_validation_binding_hash"}.issubset(columns))
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            command.downgrade(config, "20260919_0098")
            with sqlite3.connect(path) as connection:
                columns = {row[1] for row in connection.execute("PRAGMA table_info('model_changes')")}
                self.assertNotIn("supervised_validation_evidence_json", columns)
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_canonical_label_evidence_roundtrip(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "migration-0108.db"
            config = Config(str(root / "alembic.ini"))
            config.set_main_option("script_location", str(root / "migrations"))
            config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
            command.upgrade(config, "20260923_0108")
            with sqlite3.connect(path) as connection:
                columns = {row[1] for row in connection.execute("PRAGMA table_info('tenant_outcome_labels')")}
                self.assertTrue({"evidence_schema_version", "canonical_evidence_json"}.issubset(columns))
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            command.downgrade(config, "20260923_0107")
            with sqlite3.connect(path) as connection:
                columns = {row[1] for row in connection.execute("PRAGMA table_info('tenant_outcome_labels')")}
                self.assertNotIn("evidence_schema_version", columns)
                self.assertNotIn("canonical_evidence_json", columns)
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_tenant_monitoring_run_binding_roundtrip(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "migration-0109.db"
            config = Config(str(root / "alembic.ini"))
            config.set_main_option("script_location", str(root / "migrations"))
            config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
            command.upgrade(config, "20260924_0109")
            with sqlite3.connect(path) as connection:
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertIn("tenant_monitoring_runs", tables)
                run_columns = {row[1] for row in connection.execute("PRAGMA table_info('tenant_monitoring_runs')")}
                evaluation_columns = {row[1] for row in connection.execute("PRAGMA table_info('tenant_supervised_evaluations')")}
                self.assertTrue({"tenant_id", "policy_id", "observed_from", "observed_to", "label_watermark_json", "evidence_hash"}.issubset(run_columns))
                self.assertTrue({"tenant_monitoring_run_id", "tenant_monitoring_evidence_hash"}.issubset(evaluation_columns))
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            command.downgrade(config, "20260923_0108")
            with sqlite3.connect(path) as connection:
                self.assertNotIn("tenant_monitoring_runs", {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")})
                self.assertNotIn("tenant_monitoring_run_id", {row[1] for row in connection.execute("PRAGMA table_info('tenant_supervised_evaluations')")})
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_tenant_monitoring_run_governance_roundtrip(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "migration-0110.db"
            config = Config(str(root / "alembic.ini"))
            config.set_main_option("script_location", str(root / "migrations"))
            config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
            command.upgrade(config, "20260924_0110")
            with sqlite3.connect(path) as connection:
                columns = {row[1] for row in connection.execute("PRAGMA table_info('tenant_monitoring_runs')")}
                self.assertTrue({"governance_status", "submitted_by", "reviewed_by", "retracted_by", "retraction_reason", "row_version"}.issubset(columns))
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            command.downgrade(config, "20260924_0109")
            with sqlite3.connect(path) as connection:
                columns = {row[1] for row in connection.execute("PRAGMA table_info('tenant_monitoring_runs')")}
                self.assertNotIn("governance_status", columns)
                self.assertNotIn("row_version", columns)
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_tenant_monitoring_diff_case_roundtrip(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "migration-0111.db"
            config = Config(str(root / "alembic.ini"))
            config.set_main_option("script_location", str(root / "migrations"))
            config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
            command.upgrade(config, "20260924_0111")
            with sqlite3.connect(path) as connection:
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertIn("tenant_monitoring_diff_cases", tables)
                columns = {row[1] for row in connection.execute("PRAGMA table_info('tenant_monitoring_diff_cases')")}
                self.assertTrue({
                    "base_run_id", "against_run_id", "diff_hash", "comparison_json", "severity", "assigned_to",
                    "due_at", "recompute_status", "recomputed_run_id", "recomputed_diff_hash", "disposition",
                    "conclusion", "resolved_by", "row_version",
                }.issubset(columns))
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            command.downgrade(config, "20260924_0110")
            with sqlite3.connect(path) as connection:
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertNotIn("tenant_monitoring_diff_cases", tables)
                self.assertIn("tenant_monitoring_runs", tables)
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_model_risk_review_delegation_roundtrip(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "migration-0113.db"
            config = Config(str(root / "alembic.ini"))
            config.set_main_option("script_location", str(root / "migrations"))
            config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
            command.upgrade(config, "20260927_0113")
            with sqlite3.connect(path) as connection:
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertIn("model_risk_review_delegations", tables)
                columns = {row[1] for row in connection.execute("PRAGMA table_info('model_risk_review_delegations')")}
                self.assertTrue({
                    "tenant_id", "principal_subject", "delegate_subject", "assigned_role", "starts_at", "ends_at",
                    "status", "reason", "revoked_by", "revoked_at", "revocation_reason", "row_version",
                }.issubset(columns))
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            command.downgrade(config, "20260926_0112")
            with sqlite3.connect(path) as connection:
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertNotIn("model_risk_review_delegations", tables)
                self.assertIn("model_risk_review_assignments", tables)
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_tenant_notification_delivery_roundtrip(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "migration-0114.db"
            config = Config(str(root / "alembic.ini"))
            config.set_main_option("script_location", str(root / "migrations"))
            config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
            command.upgrade(config, "20260927_0114")
            with sqlite3.connect(path) as connection:
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertTrue({"tenant_notification_channels", "tenant_notification_deliveries"}.issubset(tables))
                channel_columns = {row[1] for row in connection.execute("PRAGMA table_info('tenant_notification_channels')")}
                delivery_columns = {row[1] for row in connection.execute("PRAGMA table_info('tenant_notification_deliveries')")}
                self.assertTrue({
                    "tenant_id", "endpoint_url", "secret_reference", "subscribed_categories_json",
                    "minimum_severity", "sandbox_status_sequence_json", "row_version",
                }.issubset(channel_columns))
                self.assertTrue({
                    "tenant_id", "channel_id", "notification_id", "idempotency_key", "payload_hash",
                    "channel_config_hash", "signature", "delivery_history_json", "receipt_json", "row_version",
                }.issubset(delivery_columns))
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            command.downgrade(config, "20260927_0113")
            with sqlite3.connect(path) as connection:
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertNotIn("tenant_notification_channels", tables)
                self.assertNotIn("tenant_notification_deliveries", tables)
                self.assertIn("model_risk_review_delegations", tables)
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

if __name__ == "__main__":
    unittest.main()
