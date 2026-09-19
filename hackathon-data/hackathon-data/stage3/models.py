"""Stage 3 report, trace, and explanation schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RecordRef:
    domain: str
    usubjid: str
    sequence: str

    def as_dict(self) -> dict[str, str]:
        return {"domain": self.domain, "usubjid": self.usubjid, "sequence": self.sequence}


@dataclass(frozen=True)
class Explanation:
    decision_id: str
    what: str
    evidence: tuple[RecordRef, ...]
    evidence_lines: tuple[str, ...]
    alternatives: tuple[str, ...]
    why: str
    consistent_with_trace: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "what": self.what,
            "evidence": [item.as_dict() for item in self.evidence],
            "evidence_lines": list(self.evidence_lines),
            "alternatives": list(self.alternatives),
            "why": self.why,
            "consistent_with_trace": self.consistent_with_trace,
        }


@dataclass
class SurveillanceReport:
    cuts: list[int] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    site_risks: list[dict[str, Any]] = field(default_factory=list)
    adversarial_events: list[dict[str, Any]] = field(default_factory=list)
    deviations: list[dict[str, Any]] = field(default_factory=list)
    open_items: list[dict[str, Any]] = field(default_factory=list)
    budget: dict[str, Any] = field(default_factory=dict)
    trace: list[dict[str, Any]] = field(default_factory=list)
    status: str = "NOT_STARTED"

    def as_dict(self) -> dict[str, Any]:
        return {
            "cuts": self.cuts,
            "findings": self.findings,
            "decisions": self.decisions,
            "site_risks": self.site_risks,
            "adversarial_events": self.adversarial_events,
            "deviations": self.deviations,
            "open_items": self.open_items,
            "budget": self.budget,
            "trace": self.trace,
            "status": self.status,
        }
