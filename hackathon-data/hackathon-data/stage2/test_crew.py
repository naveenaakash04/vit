import unittest
from pathlib import Path

from stage1.atlas import Atlas
from stage1.web import build_stage2_report
from stage2.crew import ReviewCrew, ReviewReport


class ReviewCrewTests(unittest.TestCase):
    def setUp(self):
        data_dir = Path(__file__).resolve().parent.parent / "data"
        self.atlas = Atlas(str(data_dir), cut=6)
        self.crew = ReviewCrew("https://hub.test", "https://gateway.test", "team-demo", self.atlas)

    def test_cycle_runs_and_trace_records_work(self):
        report = self.crew.run_cycle(6, 2)
        self.assertIsInstance(report, ReviewReport)
        self.assertTrue(report.trace)
        self.assertIsInstance(report.queries, list)
        self.assertIsInstance(report.escalations, list)

    def test_same_cut_is_idempotent_across_cycles(self):
        first = self.crew.run_cycle(6, 2)
        second = self.crew.run_cycle(6, 2)
        self.assertEqual(len(second.queries), 0)
        self.assertEqual(len(second.escalations), 0)
        self.assertEqual(first.cut, second.cut)

    def test_stage2_report_is_visible_in_app(self):
        report = build_stage2_report(str(self.atlas.graph.data_dir), 6)
        self.assertIsInstance(report, dict)
        self.assertIn("summary", report)
        self.assertIn("findings", report)

    def test_aeshosp_treated_as_serious_ae(self):
        findings = self.crew._findings_for_cut(6)
        ae_findings = [f for f in findings if f.domain == "AE"]
        self.assertTrue(len(ae_findings) > 0)
        for f in ae_findings:
            if "hospitalisation" in f.message.lower() or "serious" in f.message.lower():
                review = self.crew._medical_review(f, 6, 2)
                self.assertIn(review["decision"], ("escalate", "monitor_only"))

    def test_clarify_resubmission_loop(self):
        answer = self.crew._answer_clarification("What was the subject's screening ALT and concomitant medication?", "042-S07-001")
        self.assertIsInstance(answer, str)
        self.assertIn("042-S07-001", answer)

    def test_cross_protocol_adaptation(self):
        report_v1 = self.crew.run_cycle(1, 1)
        self.assertEqual(report_v1.protocol_version, 1)
        report_v3 = self.crew.run_cycle(12, 3)
        self.assertEqual(report_v3.protocol_version, 3)

    def test_risk_prediction_and_replay_are_available(self):
        from stage1.web import _build_subject_risk, _build_subject_replay

        risk = _build_subject_risk("042-S01-001")
        self.assertEqual(risk["subject_id"], "042-S01-001")
        self.assertIn(risk["risk_level"], {"Low", "Moderate", "High", "Critical"})
        self.assertTrue(0 <= risk["risk_score"] <= 100)
        self.assertTrue(risk["evidence"])

        replay = _build_subject_replay("042-S01-001")
        self.assertEqual(replay["subject_id"], "042-S01-001")
        self.assertTrue(replay["events"])
        self.assertEqual([event["date"] for event in replay["events"]], sorted(event["date"] for event in replay["events"]))

    def test_risk_ui_sections_are_visible(self):
        html_path = Path(__file__).resolve().parent.parent / "stage1" / "static" / "index.html"
        html = html_path.read_text(encoding="utf-8")
        for token in ("Risk Prediction", "Risk Replay"):
            self.assertIn(token, html)


if __name__ == "__main__":
    unittest.main()
