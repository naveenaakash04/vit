"""Focused Stage 3 Watch tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stage1.atlas import Atlas
from stage2.crew import ReviewCrew
from stage3.watch import StudyWatch


class StudyWatchTests(unittest.TestCase):
    def setUp(self):
        self.data_dir = Path(__file__).resolve().parent.parent / "data"
        self.crew = ReviewCrew("", "", "stage3-test", Atlas(str(self.data_dir), 1))
        self.watch = StudyWatch(str(self.data_dir), self.crew, budget_ms=1)

    def tearDown(self):
        self.crew.close()

    def test_period_completes_and_explains_decision(self):
        report = self.watch.run_period(range(1, 13))
        self.assertEqual(report.status, "COMPLETED")
        self.assertEqual(report.cuts, list(range(1, 13)))
        self.assertEqual(report.budget["mode"], "SAFETY_ONLY")
        decision_id = next(item["decision_id"] for item in report.trace if item.get("decision_id"))
        explanation = self.watch.explain(decision_id)
        self.assertEqual(explanation.decision_id, decision_id)
        self.assertTrue(explanation.consistent_with_trace)

    def test_unit_shift_is_data_integrity_event(self):
        report = self.watch.run_period(range(1, 13))
        events = [item for item in report.adversarial_events if item.get("type") == "LAB_UNIT_SHIFT"]
        self.assertTrue(any(item["site"] == "S04" and item["test"] == "GLUC" for item in events))
        self.assertTrue(all(item["clinical_escalation"] is False for item in events))

    def test_unanswered_gate_is_pending(self):
        decision = self.crew._human_gate_decision({"code": "UNKNOWN", "usubjid": "999-S99-999", "site": "S99"})
        self.assertEqual(decision["status"], "PENDING")


if __name__ == "__main__":
    unittest.main()
