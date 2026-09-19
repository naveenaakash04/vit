"""Shared time budget and graceful degradation policy."""

from __future__ import annotations

import time


class BudgetController:
    def __init__(self, total_ms: float = 30000.0):
        self.total_ms = max(float(total_ms), 1.0)
        self.started = time.perf_counter()
        self.narrative_enabled = True
        self.mode = "FULL"

    @property
    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self.started) * 1000

    @property
    def used_percent(self) -> float:
        return min(100.0, self.elapsed_ms / self.total_ms * 100)

    def checkpoint(self) -> str:
        used = self.used_percent
        if used >= 80:
            self.narrative_enabled = False
            self.mode = "SAFETY_ONLY"
        elif used >= 60:
            self.mode = "REDUCED"
        return self.mode

    def snapshot(self) -> dict[str, float | str | bool]:
        self.checkpoint()
        return {
            "total_ms": round(self.total_ms, 3),
            "elapsed_ms": round(self.elapsed_ms, 3),
            "used_percent": round(self.used_percent, 2),
            "mode": self.mode,
            "narrative_enabled": self.narrative_enabled,
        }
