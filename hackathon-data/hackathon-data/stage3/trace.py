"""Durable decision trace used by StudyWatch.explain()."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class DecisionTrace:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.entries: dict[str, dict[str, Any]] = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("decision_id"):
                    self.entries[entry["decision_id"]] = entry

    def record(self, entry: dict[str, Any]) -> dict[str, Any]:
        enriched = {"timestamp": datetime.now(timezone.utc).isoformat(), **entry}
        decision_id = enriched.setdefault("decision_id", f"D-{len(self.entries) + 1:03d}")
        self.entries[decision_id] = enriched
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(enriched, sort_keys=True) + "\n")
        return enriched

    def get(self, decision_id: str) -> dict[str, Any] | None:
        return self.entries.get(decision_id)
