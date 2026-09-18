"""Command-line interface for the study review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .loader import load_snapshot
from .rules import findings


def main() -> None:
    parser = argparse.ArgumentParser(description="Cut-aware clinical study review")
    parser.add_argument("--cut", type=int, required=True, help="Historical data cut to load")
    parser.add_argument("--findings", action="store_true", help="Run protocol checks and print findings")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data",
        help="Directory containing the study CSV files",
    )
    args = parser.parse_args()
    snapshot = load_snapshot(args.data_dir, args.cut)
    output: Any = snapshot.summary()
    if args.findings:
        output = [finding.as_dict() for finding in findings(snapshot)]
    print(json.dumps(output, indent=2))
