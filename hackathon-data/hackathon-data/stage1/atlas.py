"""Stage 1: subject-centric graph ingestion for the Study Sentinel data."""

from __future__ import annotations

import csv
import json
import re
import time
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

DOMAINS = ("DM", "LB", "AE", "EX", "CM", "EG", "MH", "DS")
SEQUENCE_COLUMNS = {domain: f"{domain}SEQ" for domain in DOMAINS if domain != "DM"}
DATE_COLUMNS = {
    "LB": "LBDTC",
    "AE": "AESTDTC",
    "EX": "EXSTDTC",
    "CM": "CMSTDTC",
    "EG": "EGDTC",
    "DS": "DSSTDTC",
}
DATE_FORMATS = ("%Y-%m-%d", "%d-%b-%Y", "%d-%B-%Y")


def parse_number(value: str | None) -> float | None:
    """Parse study numeric values without turning below-detection values into zero."""
    if value is None:
        return None
    text = value.strip()
    if not text or text.upper() == "ND" or text.startswith("<"):
        return None
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    else:
        text = text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def parse_date(value: str | None) -> date | None:
    """Parse ISO and CDISC alphanumeric dates."""
    if value is None or not value.strip():
        return None
    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(value.strip().upper(), date_format).date()
        except ValueError:
            continue
    return None


@dataclass(frozen=True)
class RecordRef:
    domain: str
    usubjid: str
    seq: str

    def as_dict(self) -> dict[str, str]:
        return {"domain": self.domain, "usubjid": self.usubjid, "seq": self.seq}


@dataclass(frozen=True)
class Answer:
    answer: Any
    evidence: tuple[RecordRef, ...]
    explanation: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "evidence": [ref.as_dict() for ref in self.evidence],
            "explanation": self.explanation,
        }


class StudyGraph:
    """In-memory, cut-aware index of the study's subject-linked records."""

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.raw_tables = {
            domain: self._read_csv(self.data_dir / f"{domain}.csv")
            for domain in DOMAINS
        }
        self.corrections = self._read_csv(self.data_dir / "corrections.csv")
        self.cut_rows = self._read_csv(self.data_dir / "cuts.csv")
        self.reference_ranges = self._read_csv(self.data_dir / "reference_ranges.csv")
        self.tables: dict[str, list[dict[str, str]]] = {}
        self.by_subject: dict[str, dict[str, list[dict[str, str]]]] = {}
        self.index: dict[str, dict[str, dict[str, list[dict[str, str]]]]] = {}
        self.current_cut: int | None = None
        self.metrics: dict[str, int | float] = {}

    @staticmethod
    def _read_csv(path: Path) -> list[dict[str, str]]:
        try:
            with path.open(newline="", encoding="utf-8-sig") as handle:
                return list(csv.DictReader(handle))
        except (OSError, csv.Error):
            return []

    @staticmethod
    def _cut(row: dict[str, str], field: str) -> int | None:
        try:
            return int(row.get(field, ""))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _sequence(domain: str, row: dict[str, str]) -> str:
        if domain == "DM":
            return "1"
        return row.get(SEQUENCE_COLUMNS[domain], "")

    def _max_cut(self) -> int:
        cuts = [self._cut(row, "cut") for row in self.cut_rows]
        values = [value for value in cuts if value is not None]
        return max(values, default=0)

    def _correction_map(self, cut: int) -> dict[tuple[str, str, str, str], str]:
        updates: dict[tuple[str, str, str, str], tuple[int, str]] = {}
        for correction in self.corrections:
            correction_cut = self._cut(correction, "cut")
            domain = correction.get("domain", "").upper()
            usubjid = correction.get("usubjid", "")
            sequence = correction.get("seq", "")
            field = correction.get("field", "")
            new_value = correction.get("new_value")
            if correction_cut is None or correction_cut > cut or not all((domain, usubjid, sequence, field)):
                continue
            key = (domain, usubjid, sequence, field)
            previous = updates.get(key)
            if previous is None or correction_cut > previous[0]:
                updates[key] = (correction_cut, new_value or "")
        return {key: value for key, (_, value) in updates.items()}

    def build(self, cut: int | None = None) -> dict[str, int | float]:
        """Build filtered subject indexes and return graph construction metrics."""
        started = time.perf_counter()
        selected_cut = self._max_cut() if cut is None else cut
        updates = self._correction_map(selected_cut)
        tables: dict[str, list[dict[str, str]]] = {}
        by_subject: dict[str, dict[str, list[dict[str, str]]]] = defaultdict(lambda: defaultdict(list))
        index: dict[str, dict[str, dict[str, list[dict[str, str]]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

        for domain, rows in self.raw_tables.items():
            visible: list[dict[str, str]] = []
            for raw_row in rows:
                if not raw_row.get("USUBJID"):
                    continue
                available = self._cut(raw_row, "cut_available")
                if available is None or available > selected_cut:
                    continue
                row = dict(raw_row)
                usubjid = row["USUBJID"]
                sequence = self._sequence(domain, row)
                for field in tuple(row):
                    key = (domain, usubjid, sequence, field)
                    if key in updates:
                        row[field] = updates[key]
                visible.append(row)
                by_subject[usubjid][domain].append(row)
                visit = row.get("VISIT", "").upper() or "_NO_VISIT"
                index[domain][usubjid][visit].append(row)
            tables[domain] = visible

        self.tables = tables
        self.by_subject = {subject: dict(domains) for subject, domains in by_subject.items()}
        self.index = {domain: dict(subjects) for domain, subjects in index.items()}
        self.current_cut = selected_cut
        subjects = len(self.by_subject)
        record_nodes = sum(len(rows) for rows in tables.values())
        self.metrics = {
            "nodes": subjects + record_nodes,
            "edges": record_nodes,
            "subjects": subjects,
            "ms": round((time.perf_counter() - started) * 1000, 3),
        }
        return dict(self.metrics)

    def patient360(self, usubjid: str) -> dict[str, Any]:
        """Return all indexed records for one subject without reading source files."""
        if not self.tables:
            self.build()
        subject_domains = self.by_subject.get(usubjid)
        if subject_domains is None:
            return {}
        demographics = (subject_domains.get("DM") or [{}])[0]
        timeline: list[dict[str, str]] = []
        for domain, date_column in DATE_COLUMNS.items():
            for row in subject_domains.get(domain, []):
                timeline.append(
                    {
                        "domain": domain,
                        "sequence": self._sequence(domain, row),
                        "visit": row.get("VISIT", ""),
                        "date": row.get(date_column, ""),
                    }
                )
        timeline.sort(key=lambda item: (item["date"], item["domain"], item["sequence"]))
        return {
            "USUBJID": usubjid,
            "demographics": deepcopy(demographics),
            "timeline": timeline,
            "adverse_events": deepcopy(subject_domains.get("AE", [])),
            "labs": deepcopy(subject_domains.get("LB", [])),
            "dosing": deepcopy(subject_domains.get("EX", [])),
            "concomitant_medications": deepcopy(subject_domains.get("CM", [])),
            "ecg": deepcopy(subject_domains.get("EG", [])),
            "medical_history": deepcopy(subject_domains.get("MH", [])),
            "disposition": deepcopy(subject_domains.get("DS", [])),
        }


class Atlas:
    """Answer count, lookup, finding, and trap questions over a StudyGraph."""

    def __init__(self, data_dir: str, cut: int | None = None):
        self.graph = StudyGraph(data_dir)
        self.graph.build(cut)

    @staticmethod
    def _ref(domain: str, row: dict[str, str]) -> RecordRef:
        sequence = row.get(f"{domain}SEQ", "1")
        return RecordRef(domain, row.get("USUBJID", ""), sequence)

    def _site(self, question: str) -> str | None:
        available_sites = {row.get("SITEID", "").upper() for row in self.graph.tables.get("DM", []) if row.get("SITEID")}
        match = re.search(r"\bsite\s*[:#-]?\s*([A-Za-z0-9_-]+)\b", question, re.IGNORECASE)
        if match:
            candidate = match.group(1).upper()
            if candidate in available_sites:
                return candidate
            if f"S{candidate.zfill(2)}" in available_sites:
                return f"S{candidate.zfill(2)}"
            if f"S{candidate}" in available_sites:
                return f"S{candidate}"
            return candidate
        for s in available_sites:
            if re.search(rf"\b{re.escape(s)}\b", question, re.IGNORECASE):
                return s
        return None

    def _subject(self, question: str) -> str | None:
        available_subjs = {row.get("USUBJID", "").upper() for row in self.graph.tables.get("DM", []) if row.get("USUBJID")}
        match = re.search(r"\b[A-Za-z0-9]+-[A-Za-z0-9]+-[A-Za-z0-9]+\b", question)
        if match:
            cand = match.group(0).upper()
            if not available_subjs or cand in available_subjs:
                return cand
        for subj in available_subjs:
            if re.search(rf"\b{re.escape(subj)}\b", question, re.IGNORECASE):
                return subj
        return None

    def _subjects(self, site: str | None = None) -> dict[str, dict[str, str]]:
        subjects = {row["USUBJID"]: row for row in self.graph.tables.get("DM", [])}
        if site is None:
            return subjects
        return {key: row for key, row in subjects.items() if row.get("SITEID", "").upper() == site}

    def _answer_discontinuations(self, question: str) -> Answer:
        subjects = self._subjects(self._site(question))
        matching_ds = []
        for row in self.graph.tables.get("DS", []):
            if row["USUBJID"] not in subjects:
                continue
            text = f"{row.get('DSDECOD', '')} {row.get('DSTERM', '')}".upper()
            if "ADVERSE" in text or re.search(r"\bAE\b", text):
                matching_ds.append(row)
        evidence = [self._ref("DS", row) for row in matching_ds]
        for ds_row in matching_ds:
            evidence.extend(self._ref("AE", row) for row in self.graph.by_subject.get(ds_row["USUBJID"], {}).get("AE", []))
        count = len({row["USUBJID"] for row in matching_ds})
        explanation = "No qualifying discontinuation due to an adverse event was found." if count == 0 else "Counted unique subjects with a disposition reason indicating an adverse event."
        return Answer(count, tuple(evidence), explanation)

    def _answer_dose_errors(self, question: str) -> Answer:
        site = self._site(question)
        subjects = self._subjects(site)
        errors = []
        for row in self.graph.tables.get("EX", []):
            subject = subjects.get(row["USUBJID"])
            if subject is None:
                continue
            expected = 10.0 if subject.get("ARM", "").upper() == "DRUG" else 0.0
            actual = parse_number(row.get("EXDOSE"))
            if actual is not None and row.get("EXDOSU", "").lower() == "mg" and actual != expected:
                errors.append(row)
        evidence = tuple(self._ref("EX", row) for row in errors)
        answer = [row["USUBJID"] for row in errors]
        explanation = "No dosing errors were found." if not answer else "These exposure records contain a dose inconsistent with the subject arm."
        return Answer(answer, evidence, explanation)

    @staticmethod
    def _clean_row(row: dict[str, str]) -> dict[str, str]:
        return {k: v for k, v in row.items() if k not in ("cut_available", "corrected_at_cut")}

    def _lab_range(self, test: str, row: dict[str, str]) -> dict[str, str] | None:
        usubjid = row.get("USUBJID", "")
        site = row.get("SITEID") or row.get("LAB")
        if not site and usubjid:
            dm_row = (self.graph.by_subject.get(usubjid, {}).get("DM") or [{}])[0]
            site = dm_row.get("SITEID")
        if not site and usubjid:
            parts = usubjid.split("-")
            if len(parts) > 1:
                site = parts[1]

        site = (site or "").upper()
        unit = row.get("LBORRESU")

        # 1. Match site laboratory and unit
        if site:
            for item in self.graph.reference_ranges:
                if item.get("LBTESTCD") == test and item.get("LAB", "").upper() == site and (not unit or item.get("UNIT") == unit):
                    return item
            for item in self.graph.reference_ranges:
                if item.get("LBTESTCD") == test and item.get("LAB", "").upper() == site:
                    return item

        # 2. Match CENTRAL lab with matching unit
        for item in self.graph.reference_ranges:
            if item.get("LBTESTCD") == test and item.get("LAB", "").upper() == "CENTRAL" and (not unit or item.get("UNIT") == unit):
                return item

        # 3. Match any lab with matching unit
        if unit:
            for item in self.graph.reference_ranges:
                if item.get("LBTESTCD") == test and item.get("UNIT") == unit:
                    return item

        # 4. Match CENTRAL lab
        for item in self.graph.reference_ranges:
            if item.get("LBTESTCD") == test and item.get("LAB", "").upper() == "CENTRAL":
                return item

        # 5. Any match on test
        for item in self.graph.reference_ranges:
            if item.get("LBTESTCD") == test:
                return item

        return None

    def _normalized_lab_value(self, row: dict[str, str]) -> float | None:
        value = parse_number(row.get("LBORRES"))
        if value is not None and row.get("LBTESTCD") in {"ALT", "AST"} and row.get("LBORRESU") == "ukat/L":
            return value * 60
        return value

    def _answer_hys_law(self) -> Answer:
        candidates: list[str] = []
        evidence: list[RecordRef] = []
        by_subject: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in self.graph.tables.get("LB", []):
            by_subject[row["USUBJID"]].append(row)
        for usubjid, rows in by_subject.items():
            transaminases = [row for row in rows if row.get("LBTESTCD") in {"ALT", "AST"}]
            bilirubin = [row for row in rows if row.get("LBTESTCD") == "BILI"]
            found = False
            for trans in transaminases:
                trans_range = self._lab_range(trans["LBTESTCD"], trans)
                trans_val = parse_number(trans.get("LBORRES"))
                if trans_range is None or trans_val is None:
                    continue
                range_high = parse_number(trans_range.get("HIGH"))
                if range_high is None or range_high <= 0:
                    continue
                trans_unit = trans.get("LBORRESU", "")
                range_unit = trans_range.get("UNIT", "")
                norm_trans = trans_val
                if trans_unit == "ukat/L" and range_unit == "U/L":
                    norm_trans = trans_val * 60
                elif trans_unit == "U/L" and range_unit == "ukat/L":
                    norm_trans = trans_val / 60

                if norm_trans <= 3 * range_high:
                    continue
                trans_date = parse_date(trans.get("LBDTC"))
                if trans_date is None:
                    continue
                for bili in bilirubin:
                    bili_range = self._lab_range("BILI", bili)
                    bili_val = parse_number(bili.get("LBORRES"))
                    bili_date = parse_date(bili.get("LBDTC"))
                    if bili_range is None or bili_val is None or bili_date is None:
                        continue
                    bili_high = parse_number(bili_range.get("HIGH"))
                    if bili_high is None or bili_high <= 0:
                        continue
                    if abs((trans_date - bili_date).days) <= 14 and bili_val > 2 * bili_high:
                        found = True
                        evidence.extend((self._ref("LB", trans), self._ref("LB", bili)))
                        break
                if found:
                    break
            if found:
                candidates.append(usubjid)
        explanation = "No potential Hy's law candidates were found." if not candidates else "Candidates meet ALT or AST > 3x ULN and bilirubin > 2x ULN within 14 days."
        return Answer(candidates, tuple(evidence), explanation)

    def _answer_lookup(self, question: str) -> Answer:
        subject = self._subject(question)
        if not subject:
            return Answer([], (), "No subject identifier was present for the lookup.")
        domain_match = re.search(r"\b(DM|LB|AE|EX|CM|EG|MH|DS)\b", question.upper())
        domain = domain_match.group(1) if domain_match else "LB"
        rows = [row for row in self.graph.by_subject.get(subject, {}).get(domain, [])]
        window_match = re.search(r"within\s+(\d+)\s+days?\s+(?:of|from)\s+([A-Za-z0-9-]+)", question, re.IGNORECASE)
        if window_match and domain in DATE_COLUMNS:
            days = int(window_match.group(1))
            visit = window_match.group(2).upper()
            subject_rows = self.graph.by_subject.get(subject, {})
            anchor = None
            if visit == "BASELINE":
                dm_row = (subject_rows.get("DM") or [{}])[0]
                anchor = parse_date(dm_row.get("RFSTDTC"))
            else:
                for anchor_domain, anchor_rows in subject_rows.items():
                    date_column = DATE_COLUMNS.get(anchor_domain)
                    if not date_column:
                        continue
                    anchor_row = next((item for item in anchor_rows if item.get("VISIT", "").upper() == visit), None)
                    if anchor_row:
                        anchor = parse_date(anchor_row.get(date_column))
                        break
            if anchor:
                date_column = DATE_COLUMNS[domain]
                rows = [row for row in rows if (row_date := parse_date(row.get(date_column))) and abs((row_date - anchor).days) <= days]
        refs = tuple(self._ref(domain, row) for row in rows)
        cleaned_rows = [self._clean_row(row) for row in rows]
        return Answer(cleaned_rows, refs, "Lookup returned all visible records for the requested subject and domain.") if rows else Answer([], (), "No matching records were found.")

    def answer(self, question: str) -> Answer:
        """Answer one supported natural-language question with evidence citations."""
        normalized = question.lower()
        if "hy" in normalized and ("law" in normalized or "bilirubin" in normalized):
            return self._answer_hys_law()
        if ("dose" in normalized or "dosing" in normalized) and ("error" in normalized or "incorrect" in normalized):
            return self._answer_dose_errors(question)
        if "discontinu" in normalized and ("adverse" in normalized or "event" in normalized):
            return self._answer_discontinuations(question)
        return self._answer_lookup(question)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Build the Stage 1 study graph")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--cut", type=int)
    parser.add_argument("--stats-out", type=Path, default=Path("graph_stats.json"))
    args = parser.parse_args()
    graph = StudyGraph(str(args.data_dir))
    stats = graph.build(args.cut)
    args.stats_out.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
