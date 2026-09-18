"""Historical cut loading and correction application."""

from __future__ import annotations

import csv
from pathlib import Path

from .models import DOMAIN_FILES, StudyDataError, StudySnapshot


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _as_cut(row: dict[str, str], field: str) -> int:
    try:
        return int(row[field])
    except (KeyError, TypeError, ValueError) as exc:
        raise StudyDataError(f"Invalid {field} in row: {row}") from exc


def _record_sequence(domain: str, row: dict[str, str]) -> str:
    sequence_column = f"{domain}SEQ"
    if sequence_column in row:
        return row[sequence_column]
    if domain == "DM":
        return "1"
    raise StudyDataError(f"Missing sequence column {sequence_column!r} in {domain}")


def load_snapshot(data_dir: str | Path, cut: int) -> StudySnapshot:
    """Load a historical snapshot and apply corrections known at that cut."""
    root = Path(data_dir)
    cuts = _read_csv(root / "cuts.csv")
    cut_rows = [row for row in cuts if _as_cut(row, "cut") == cut]
    if len(cut_rows) != 1:
        raise StudyDataError(f"Expected one row for cut {cut}, found {len(cut_rows)}")
    protocol_version = _as_cut(cut_rows[0], "protocol_version")

    corrections = _read_csv(root / "corrections.csv")
    latest_by_record: dict[tuple[str, str, str], dict[str, tuple[str, str, int]]] = {}
    for correction in corrections:
        c_cut = _as_cut(correction, "cut")
        if c_cut > cut:
            continue
        domain = correction.get("domain", "").upper()
        usubjid = correction.get("usubjid", "")
        seq = correction.get("seq", "")
        field = correction.get("field", "")
        new_val = correction.get("new_value", "")
        record_key = (domain, usubjid, seq)
        
        if record_key not in latest_by_record:
            latest_by_record[record_key] = {}
        
        prev = latest_by_record[record_key].get(field)
        if prev is None or c_cut > prev[2]:
            latest_by_record[record_key][field] = (new_val, str(c_cut), c_cut)

    tables: dict[str, list[dict[str, str]]] = {}
    for domain in DOMAIN_FILES:
        visible_rows = []
        for row in _read_csv(root / f"{domain}.csv"):
            if not row.get("USUBJID"):
                continue
            if _as_cut(row, "cut_available") > cut:
                continue
            corrected = dict(row)
            record_key = (domain, row["USUBJID"], _record_sequence(domain, row))
            if record_key in latest_by_record:
                for field, (new_value, cut_str, _) in latest_by_record[record_key].items():
                    if field in corrected:
                        corrected[field] = new_value
                        corrected["corrected_at_cut"] = cut_str
            visible_rows.append(corrected)
        tables[domain] = visible_rows

    return StudySnapshot(cut, protocol_version, tables, _read_csv(root / "reference_ranges.csv"))
