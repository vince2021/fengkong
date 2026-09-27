from __future__ import annotations

import unittest

import backend.database as database
from backend.db_models import ModelSnapshotRecord
from backend.repository import ApprovalCaseRepository, AuditRepository, RatingRunRepository, clear_persistent_data
from rating.approval_workflow import create_approval_case
from rating.scorecard import rate_counterparty
from rating.template_resolver import resolve_template
import json
from pathlib import Path
from tests.database_support import IsolatedTestDatabase


class PersistenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.test_database = IsolatedTestDatabase()
        cls.test_database.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.test_database.stop()

    def setUp(self) -> None:
        self.session = database.SessionLocal()
        clear_persistent_data(self.session)
        base = Path(__file__).resolve().parents[1]
        self.counterparty = json.loads((base / "data" / "counterparties.json").read_text(encoding="utf-8"))[0]
        templates = json.loads((base / "data" / "model_templates.json").read_text(encoding="utf-8"))["templates"]
        self.config = resolve_template("general", templates)

    def tearDown(self) -> None:
        self.session.close()

    def test_approval_case_is_persistent_and_audited(self) -> None:
        repository = ApprovalCaseRepository(self.session)
        tenant_id = "tenant-demo-hengxin"
        case = repository.save(tenant_id, create_approval_case(self.counterparty), actor="客户经理", event_type="approval_case_created")
        loaded = repository.get(tenant_id, case["case_id"])
        events = AuditRepository(self.session).list(tenant_id, case["case_id"])

        self.assertEqual(loaded["counterparty_id"], self.counterparty["id"])
        self.assertEqual(loaded["row_version"], 1)
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]["event_hash"])

    def test_rating_run_binds_input_model_and_result_snapshots(self) -> None:
        result = rate_counterparty(self.counterparty, self.config)
        repository = RatingRunRepository(self.session)
        tenant_id = "tenant-demo-hengxin"
        run = repository.save_run(tenant_id, self.counterparty, "general", self.config, result)
        loaded = repository.get(tenant_id, run["id"])

        self.assertEqual(loaded["input"]["id"], self.counterparty["id"])
        self.assertEqual(loaded["result"]["total_score"], result["total_score"])
        self.assertTrue(loaded["model_snapshot_id"])
        self.assertTrue(loaded["result_hash"])
        snapshot = self.session.get(ModelSnapshotRecord, loaded["model_snapshot_id"])
        self.assertIn("risk_screening_policy", snapshot.config_json)
        self.assertTrue(snapshot.config_json["risk_screening_policy"]["rules"])


if __name__ == "__main__":
    unittest.main()
