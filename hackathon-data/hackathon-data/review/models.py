"""Shared data structures and parsing helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

DOMAIN_FILES = ("DM", "AE", "LB", "VS", "EX", "CM", "DS", "MH", "EG")
DATE_FORMATS = ("%Y-%m-%d", "%d-%b-%Y", "%d-%B-%Y")
MISSING_NUMERIC = {"", "ND"}
VISIT_DAYS = {
    "SCREENING": -14,
    "BASELINE": 0,
    "WEEK2": 14,
    "WEEK4": 28,
    "WEEK8": 56,
    "WEEK12": 84,
    "WEEK16": 112,
    "WEEK20": 140,
    "WEEK24": 168,
    "EOS": 182,
}
DATE_COLUMNS = {"LB": "LBDTC", "VS": "VSDTC", "EX": "EXSTDTC", "EG": "EGDTC"}


class StudyDataError(ValueError):
    """Raised when the study data cannot form a consistent snapshot."""


@dataclass(frozen=True)
class Finding:
    """A protocol finding with a directly traceable source record."""

    code: str
    usubjid: str
    domain: str
    sequence: str
    message: str
    severity: str = "HIGH"

    def as_dict(self) -> dict[str, str]:
        return {
            "finding_code": self.code,
            "USUBJID": self.usubjid,
            "domain": self.domain,
            "sequence": self.sequence,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class StudySnapshot:
    """All data visible at one cut, with corrections available at that cut applied."""

    cut: int
    protocol_version: int
    tables: dict[str, list[dict[str, str]]]
    reference_ranges: list[dict[str, str]]

    def table(self, domain: str) -> list[dict[str, str]]:
        try:
            return self.tables[domain.upper()]
        except KeyError as exc:
            raise StudyDataError(f"Unknown domain: {domain}") from exc

    def summary(self) -> dict[str, Any]:
        return {
            "cut": self.cut,
            "protocol_version": self.protocol_version,
            "rows": {domain: len(rows) for domain, rows in self.tables.items()},
        }


def parse_date(value: str | None) -> date | None:
    """Parse the date formats used by the study, safely returning None if unparseable."""
    if value is None or not value.strip():
        return None
    text = value.strip()
    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(text.upper(), date_format).date()
        except ValueError:
            continue
    return None


def parse_number(value: str | None) -> float | None:
    """Parse numeric results while preserving non-numeric lab values as missing."""
    if value is None:
        return None
    text = value.strip()
    if not text or text.upper() in MISSING_NUMERIC or text.startswith("<"):
        return None
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    else:
        text = text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None
