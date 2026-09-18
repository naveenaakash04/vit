"""Compatibility entry point for the cut-aware clinical study review."""

from review import (
    Finding,
    Response,
    ResponseStore,
    StudyDataError,
    StudySnapshot,
    findings,
    load_snapshot,
    parse_date,
    parse_number,
)
from review.cli import main

__all__ = [
    "Finding",
    "Response",
    "ResponseStore",
    "StudyDataError",
    "StudySnapshot",
    "findings",
    "load_snapshot",
    "parse_date",
    "parse_number",
    "main",
]


if __name__ == "__main__":
    main()
