"""Incremental in-memory cut updates for StudyGraph."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from stage1.atlas import StudyGraph


@dataclass
class CutDelta:
    cut: int
    added_records: int
    corrected_records: int
    affected_subjects: set[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "cut": self.cut,
            "added_records": self.added_records,
            "corrected_records": self.corrected_records,
            "affected_subjects": sorted(self.affected_subjects),
        }


class IncrementalStudyGraph:
    """Load source CSVs once, then update only visible records and corrections."""

    def __init__(self, data_dir: str):
        self.graph = StudyGraph(data_dir)
        known = set(self.graph.raw_tables)
        self.dynamic_tables: dict[str, list[dict[str, str]]] = {}
        for path in self.graph.data_dir.glob("*.csv"):
            domain = path.stem.upper()
            if domain not in known and domain not in {"CORRECTIONS", "CUTS", "REFERENCE_RANGES"}:
                self.dynamic_tables[domain] = self.graph._read_csv(path)
        self.current_cut: int | None = None
        self._record_keys: set[tuple[str, str, str]] = set()
        self._record_values: dict[tuple[str, str, str], dict[str, str]] = {}

    def update_to_cut(self, cut: int) -> CutDelta:
        if self.current_cut is None:
            self.graph.build(cut)
            self.graph.raw_tables.update(self.dynamic_tables)
            self._add_dynamic_domains(cut)
            self._record_values = {
                (domain, row["USUBJID"], self._sequence(domain, row)): deepcopy(row)
                for domain, rows in self.graph.tables.items()
                for row in rows
            }
            self._record_keys = set(self._record_values)
            self.current_cut = cut
            return CutDelta(cut, len(self._record_keys), 0, {key[1] for key in self._record_keys})

        updates = self.graph._correction_map(cut)
        added = 0
        corrected = 0
        affected: set[str] = set()
        for domain, rows in self.graph.raw_tables.items():
            for raw in rows:
                if not raw.get("USUBJID"):
                    continue
                available = self.graph._cut(raw, "cut_available")
                if available is None or available > cut:
                    continue
                key = (domain, raw["USUBJID"], self._sequence(domain, raw))
                updated = dict(raw)
                for field in tuple(updated):
                    correction_key = (*key, field)
                    if correction_key in updates:
                        updated[field] = updates[correction_key]
                if key not in self._record_values:
                    added += 1
                    affected.add(key[1])
                elif updated != self._record_values[key]:
                    corrected += 1
                    affected.add(key[1])
                self._record_values[key] = updated

        self._reindex()
        self.current_cut = cut
        return CutDelta(cut, added, corrected, affected)

    @staticmethod
    def _sequence(domain: str, row: dict[str, str]) -> str:
        return row.get(f"{domain}SEQ", "1")

    def _add_dynamic_domains(self, cut: int) -> None:
        for domain, rows in self.graph.raw_tables.items():
            if domain in self.graph.tables:
                continue
            visible = [dict(row) for row in rows if row.get("USUBJID") and self.graph._cut(row, "cut_available") is not None and self.graph._cut(row, "cut_available") <= cut]
            self.graph.tables[domain] = visible

    def _reindex(self) -> None:
        tables: dict[str, list[dict[str, str]]] = defaultdict(list)
        by_subject: dict[str, dict[str, list[dict[str, str]]]] = defaultdict(lambda: defaultdict(list))
        index: dict[str, dict[str, dict[str, list[dict[str, str]]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        for (domain, usubjid, _), row in self._record_values.items():
            tables[domain].append(row)
            by_subject[usubjid][domain].append(row)
            index[domain][usubjid][row.get("VISIT", "").upper() or "_NO_VISIT"].append(row)
        self.graph.tables = dict(tables)
        self.graph.by_subject = {subject: dict(domains) for subject, domains in by_subject.items()}
        self.graph.index = {domain: dict(subjects) for domain, subjects in index.items()}
        self.graph.current_cut = self.current_cut
        self.graph.metrics = {
            "nodes": len(self.graph.by_subject) + sum(len(rows) for rows in self.graph.tables.values()),
            "edges": sum(len(rows) for rows in self.graph.tables.values()),
            "subjects": len(self.graph.by_subject),
            "ms": 0.0,
        }
