"""Detectors for data-integrity threats introduced during surveillance."""

from __future__ import annotations

import hashlib
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from stage1.atlas import parse_number


class AdversarialDetector:
    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self.previous_hashes: dict[str, str] = {}
        self.previous_medians: dict[tuple[str, str], float] = {}

    def document_changes(self) -> list[dict[str, Any]]:
        events = []
        for path in sorted((self.data_dir.parent / "documents").glob("*.md")):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            old = self.previous_hashes.get(str(path))
            if old and old != digest:
                events.append({"type": "DOCUMENT_CHANGED", "document": path.name, "instruction_ignored": True, "reason": "Changed document is evidence, not executable policy."})
            self.previous_hashes[str(path)] = digest
        return events

    def laboratory_shifts(self, rows: list[dict[str, str]], cut: int) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
        for row in rows:
            if str(row.get("cut_available", "")) != str(cut):
                continue
            value = parse_number(row.get("LBORRES"))
            if value is not None:
                site = row.get("USUBJID", "").split("-")[1] if "-" in row.get("USUBJID", "") else "UNKNOWN"
                grouped[(site, row.get("LBTESTCD", "").upper())].append(value)
        events = []
        for key, values in grouped.items():
            if len(values) < 3:
                continue
            median = statistics.median(values)
            previous = self.previous_medians.get(key)
            if previous and median and (0.04 <= median / previous <= 0.08 or 12.0 <= median / previous <= 25.0):
                events.append({"type": "LAB_UNIT_SHIFT", "cut": cut, "site": key[0], "test": key[1], "previous_median": previous, "current_median": median, "ratio": median / previous, "action": "QUARANTINE_AND_REISSUE", "clinical_escalation": False})
            self.previous_medians[key] = median
        return events

    def regularity(self, tables: dict[str, list[dict[str, str]]], cut: int) -> list[dict[str, Any]]:
        events = []
        by_site: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in tables.get("VS", []):
            site = row.get("USUBJID", "").split("-")[1] if "-" in row.get("USUBJID", "") else "UNKNOWN"
            by_site[site].append(row)
        for site, rows in by_site.items():
            values = [parse_number(row.get("VSORRES")) for row in rows]
            values = [value for value in values if value is not None]
            if len(values) >= 10 and len(set(values)) == 1:
                events.append({"type": "SITE_REGULARITY", "cut": cut, "site": site, "reason": "Vital-sign values are identical across records.", "action": "QUARANTINE_AND_AUDIT", "clinical_escalation": False})
        return events
