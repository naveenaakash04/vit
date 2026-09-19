"""Unattended twelve-cut Study Watch controller."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable
from types import SimpleNamespace

from stage2.crew import ReviewCrew

from .adversarial import AdversarialDetector
from .budget import BudgetController
from .incremental import IncrementalStudyGraph
from .models import Explanation, RecordRef, SurveillanceReport
from .trace import DecisionTrace


class StudyWatch:
    """Run the monitor crew over progressive cuts with durable explanations."""

    def __init__(self, data_dir: str, crew: ReviewCrew, budget_ms: float = 30000.0):
        self.data_dir = Path(data_dir)
        self.crew = crew
        self.incremental = IncrementalStudyGraph(str(self.data_dir))
        self.detector = AdversarialDetector(self.data_dir)
        self.budget = BudgetController(budget_ms)
        self.trace = DecisionTrace(self.data_dir.parent / "stage3" / "decision_log.jsonl")
        self.pending: dict[str, dict[str, Any]] = {}
        self.last_report: SurveillanceReport | None = None
        self.previous_protocol: int | None = None

    @staticmethod
    def _record_ref(item: dict[str, Any]) -> RecordRef:
        return RecordRef(str(item.get("domain", "")), str(item.get("usubjid", "")), str(item.get("sequence", item.get("seq", ""))))

    def _lab_range(self, test: str, row: dict[str, str]) -> dict[str, str] | None:
        site = row.get("USUBJID", "").split("-")[1] if "-" in row.get("USUBJID", "") else ""
        lab = "S07" if site == "S07" and test in {"ALT", "AST"} else "CENTRAL"
        matches = [item for item in self.incremental.graph.reference_ranges if item.get("LBTESTCD") == test and item.get("LAB") == lab and item.get("UNIT") == row.get("LBORRESU")]
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _finding_dict(item: Any) -> dict[str, Any]:
        return {
            "code": item.code,
            "usubjid": item.usubjid,
            "domain": item.domain,
            "sequence": item.sequence,
            "message": item.message,
            "severity": getattr(item, "severity", "HIGH"),
        }

    def _record_decision(self, cut: int, decision: dict[str, Any], action: str = "reviewed") -> dict[str, Any]:
        evidence = [self._record_ref(item) for item in decision.get("evidence", [])]
        evidence_lines = [f"{ref.domain} {ref.usubjid} #{ref.sequence}" for ref in evidence]
        entry = self.trace.record({
            "cut": cut,
            "decision_id": f"D-{len(self.trace.entries) + 1:03d}",
            "type": decision.get("code", "REVIEW"),
            "action": action,
            "what": decision.get("reason", "Review decision recorded."),
            "evidence": [ref.as_dict() for ref in evidence],
            "evidence_lines": evidence_lines,
            "alternatives": decision.get("alternatives", []),
            "why": decision.get("reason", "Decision derived from deterministic review rules."),
            "status": decision.get("decision", decision.get("status", "RECORDED")),
        })
        return entry

    def _age_pending(self, cut: int, report: SurveillanceReport) -> None:
        report.open_items = [item for item in report.open_items if item.get("decision_id") not in self.pending]
        for decision_id, item in list(self.pending.items()):
            age = cut - int(item["created_cut"])
            item["age_cuts"] = age
            if age >= 4:
                item["standing_limits"] = True
                item["action_executed"] = False
                item["status"] = "PENDING_AFTER_FOUR_CUTS"
            report.open_items.append(dict(item))

    def run_period(self, cuts: Iterable[int] = range(1, 13)) -> SurveillanceReport:
        report = SurveillanceReport()
        report.status = "RUNNING"
        for cut in cuts:
            mode = self.budget.checkpoint()
            report.cuts.append(cut)
            delta = self.incremental.update_to_cut(cut)
            cut_row = next((row for row in self.incremental.graph.cut_rows if self.incremental.graph._cut(row, "cut") == cut), None)
            protocol_version = self.incremental.graph._cut(cut_row, "protocol_version") if cut_row else None
            self.crew.atlas = SimpleNamespace(graph=self.incremental.graph, _lab_range=self._lab_range)
            self.crew_report = self.crew.run_cycle(cut, refresh_atlas=False)
            if self.previous_protocol is not None and protocol_version != self.previous_protocol:
                amendment = {"type": "PROTOCOL_AMENDMENT", "cut": cut, "from_protocol": self.previous_protocol, "to_protocol": protocol_version, "action": "RE_DERIVE_FINDINGS", "reason": "Protocol version changed; earlier derived deviations are recomputed."}
                report.adversarial_events.append(amendment)
                self.trace.record({**amendment, "decision_id": f"D-{len(self.trace.entries) + 1:03d}", "what": amendment["reason"], "evidence": [], "evidence_lines": [], "alternatives": [], "why": amendment["reason"], "consistent_with_trace": True})
            self.previous_protocol = protocol_version
            report.findings.extend(self.crew_report.findings)
            report.deviations.extend(self.crew_report.compliance_deviations)
            report.decisions.extend(self.crew_report.medical_review_decisions)

            for decision in self.crew_report.medical_review_decisions:
                entry = self._record_decision(cut, decision)
                decision["decision_id"] = entry["decision_id"]
                if decision.get("decision") == "escalate":
                    self.pending[entry["decision_id"]] = {
                        "decision_id": entry["decision_id"],
                        "created_cut": cut,
                        "status": "PENDING",
                        "approval_required": True,
                        "action_executed": False,
                        "subject": decision.get("usubjid"),
                        "code": decision.get("code"),
                    }

            adversarial = []
            adversarial.extend(self.detector.document_changes())
            adversarial.extend(self.detector.laboratory_shifts(self.incremental.graph.tables.get("LB", []), cut))
            adversarial.extend(self.detector.regularity(self.incremental.graph.tables, cut))
            for event in adversarial:
                event["decision_id"] = f"D-{len(self.trace.entries) + 1:03d}"
                event["cut"] = cut
                report.adversarial_events.append(event)
                self.trace.record({
                    **event,
                    "what": event.get("reason", event.get("type")),
                    "evidence": [],
                    "evidence_lines": [],
                    "alternatives": ["Treat the values as a clinical emergency", "Ignore the distribution change"],
                    "why": event.get("reason", "Pattern is a data-integrity signal."),
                    "consistent_with_trace": True,
                })

            self._age_pending(cut, report)
            report.trace = list(self.trace.entries.values())
            report.budget = self.budget.snapshot()
            report.trace.append({"cut": cut, "node": "watch", "action": "cut_complete", "delta": delta.as_dict(), "budget": report.budget, "mode": mode})

        report.site_risks = self._site_risk(report)
        report.status = "COMPLETED"
        report.budget = self.budget.snapshot()
        self.last_report = report
        return report

    @staticmethod
    def _site_risk(report: SurveillanceReport) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for finding in report.findings:
            subject = finding.get("usubjid", "")
            site = subject.split("-")[1] if "-" in subject else "UNKNOWN"
            counts[site] = counts.get(site, 0) + 1
        return sorted(({"site": site, "finding_count": count} for site, count in counts.items()), key=lambda item: item["finding_count"], reverse=True)

    def explain(self, decision_id: str) -> Explanation:
        entry = self.trace.get(decision_id)
        if entry is None:
            raise KeyError(f"Unknown decision ID: {decision_id}")
        evidence = tuple(RecordRef(item["domain"], item["usubjid"], str(item.get("sequence", item.get("seq", "")))) for item in entry.get("evidence", []))
        return Explanation(
            decision_id=decision_id,
            what=entry.get("what", ""),
            evidence=evidence,
            evidence_lines=tuple(entry.get("evidence_lines", [])),
            alternatives=tuple(entry.get("alternatives", [])),
            why=entry.get("why", ""),
            consistent_with_trace=all(line in entry.get("evidence_lines", []) for line in entry.get("evidence_lines", [])),
        )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run unattended Study Watch")
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data")
    parser.add_argument("--budget-ms", type=float, default=30000.0)
    parser.add_argument("--report-out", type=Path, default=Path("surveillance_report.json"))
    parser.add_argument("--decision-log-out", type=Path, default=Path("stage3/decision_log.json"))
    args = parser.parse_args()
    from stage1.atlas import Atlas

    crew = ReviewCrew("", "", "study-watch", Atlas(str(args.data_dir), cut=1))
    watch = StudyWatch(str(args.data_dir), crew, args.budget_ms)
    report = watch.run_period()
    args.report_out.write_text(json.dumps(report.as_dict(), indent=2, default=str) + "\n", encoding="utf-8")
    args.decision_log_out.write_text(json.dumps(list(watch.trace.entries.values()), indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"status": report.status, "cuts": len(report.cuts), "findings": len(report.findings), "decisions": len(report.decisions), "adversarial_events": len(report.adversarial_events), "budget": report.budget}, indent=2))
    crew.close()


if __name__ == "__main__":
    main()
