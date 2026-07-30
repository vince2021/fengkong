from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from backend.document_correction_sla import correction_sla_snapshot, correction_sla_window


class DocumentCorrectionSlaTest(unittest.TestCase):
    def test_open_and_resubmitted_windows_assign_expected_roles(self) -> None:
        started_at = datetime(2026, 7, 25, 8, 0, tzinfo=timezone.utc)
        open_role, open_started, open_due = correction_sla_window("open", started_at)
        review_role, review_started, review_due = correction_sla_window("resubmitted", started_at)

        self.assertEqual(open_role, "relationship_manager")
        self.assertEqual(open_started, started_at)
        self.assertEqual(open_due, started_at + timedelta(hours=48))
        self.assertEqual(review_role, "risk_manager")
        self.assertEqual(review_started, started_at)
        self.assertEqual(review_due, started_at + timedelta(hours=24))

    def test_snapshot_covers_warning_overdue_escalation_and_stop(self) -> None:
        now = datetime(2026, 7, 25, 8, 0, tzinfo=timezone.utc)
        self.assertEqual(correction_sla_snapshot("open", now + timedelta(hours=13), now)["sla_status"], "normal")
        self.assertEqual(correction_sla_snapshot("open", now + timedelta(hours=12), now)["sla_status"], "due_soon")
        self.assertEqual(correction_sla_snapshot("open", now - timedelta(minutes=1), now)["sla_status"], "overdue")
        self.assertEqual(correction_sla_snapshot("open", now - timedelta(hours=4), now)["sla_status"], "escalated")
        self.assertEqual(correction_sla_snapshot("closed", now, now), {"sla_status": "stopped", "remaining_seconds": 0})


if __name__ == "__main__":
    unittest.main()
