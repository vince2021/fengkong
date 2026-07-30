from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest

import backend.database as database
from backend.authority_policy_repository import (
    AuthorityPolicyRepository,
    _activation_scheduler_health,
    authority_policy_scheduler_run_key,
)
from backend.db_models import AuthorityPolicyActivationRunRecord
from backend.jobs.authority_policy_activation import (
    SCHEDULER_SUBJECT,
    run_authority_policy_activation,
)
from backend.repository import clear_persistent_data
from tests.database_support import IsolatedTestDatabase


class AuthorityPolicySchedulerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.test_database = IsolatedTestDatabase()
        cls.test_database.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.test_database.stop()

    def setUp(self) -> None:
        with database.SessionLocal() as session:
            clear_persistent_data(session)

    def test_scheduler_run_key_uses_stable_utc_bucket(self) -> None:
        first = authority_policy_scheduler_run_key(
            datetime(2026, 7, 26, 12, 57, 59, tzinfo=timezone.utc),
            5,
        )
        repeated = authority_policy_scheduler_run_key(
            datetime(2026, 7, 26, 20, 59, 1, tzinfo=timezone(timedelta(hours=8))),
            5,
        )
        self.assertEqual(first, "authority-policy-scheduler:20260726T1255Z:5m")
        self.assertEqual(repeated, first)
        cross_hour_before = authority_policy_scheduler_run_key(
            datetime(1970, 1, 1, 0, 59, 59, tzinfo=timezone.utc),
            7,
        )
        cross_hour_after = authority_policy_scheduler_run_key(
            datetime(1970, 1, 1, 1, 0, 1, tzinfo=timezone.utc),
            7,
        )
        self.assertEqual(cross_hour_before, "authority-policy-scheduler:19700101T0056Z:7m")
        self.assertEqual(cross_hour_after, cross_hour_before)
        with self.assertRaisesRegex(ValueError, "1—60"):
            authority_policy_scheduler_run_key(interval_minutes=0)

    def test_scheduler_job_is_idempotent_and_visible_in_health_status(self) -> None:
        run_at = datetime(2026, 7, 26, 13, 2, 40, tzinfo=timezone.utc)
        with database.SessionLocal() as session:
            first = run_authority_policy_activation(session, run_at)
        with database.SessionLocal() as session:
            repeated = run_authority_policy_activation(session, run_at + timedelta(minutes=1))
            status = AuthorityPolicyRepository(session).activation_status(now=run_at + timedelta(minutes=1))
            persisted = session.get(AuthorityPolicyActivationRunRecord, first["run"]["id"])

        self.assertFalse(first["idempotent"])
        self.assertTrue(repeated["idempotent"])
        self.assertEqual(repeated["run"]["id"], first["run"]["id"])
        self.assertEqual(persisted.actor_subject, SCHEDULER_SUBJECT)
        self.assertEqual(persisted.trigger_type, "scheduler")
        self.assertEqual(status["scheduler_health"]["state"], "idle")
        self.assertEqual(status["scheduler_health"]["last_scheduler_run"]["id"], first["run"]["id"])
        self.assertEqual(status["scheduler_health"]["next_expected_scan_at"], "2026-07-26T13:07:40+00:00")
        with database.SessionLocal() as session:
            with self.assertRaisesRegex(ValueError, "manual 或 scheduler"):
                AuthorityPolicyRepository(session).activate_due(
                    "invalid-trigger",
                    "非法触发测试",
                    now=run_at,
                    run_key="authority-policy-invalid-trigger",
                    trigger_type="batch",
                )

    def test_scheduler_health_distinguishes_attention_overdue_and_blocked(self) -> None:
        checked_at = datetime(2026, 7, 26, 13, 0, tzinfo=timezone.utc)
        future_schedule = SimpleNamespace(effective_at=checked_at + timedelta(hours=2))
        overdue_schedule = SimpleNamespace(effective_at=checked_at - timedelta(minutes=17))

        attention = _activation_scheduler_health(future_schedule, None, 0, checked_at, 5)
        overdue = _activation_scheduler_health(overdue_schedule, None, 0, checked_at, 5)
        blocked = _activation_scheduler_health(overdue_schedule, None, 2, checked_at, 5)

        self.assertEqual(attention["state"], "attention")
        self.assertEqual(overdue["state"], "overdue")
        self.assertEqual(overdue["overdue_seconds"], 17 * 60)
        self.assertEqual(blocked["state"], "blocked")
        self.assertIn("2 个", blocked["message"])


if __name__ == "__main__":
    unittest.main()
