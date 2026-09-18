"""Site-query and medical-monitor response handling."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .models import StudyDataError


@dataclass(frozen=True)
class Response:
    """A scripted response returned by a site or medical monitor."""

    status: str
    message: str
    key: str


class ResponseStore:
    """Look up scripted site and monitor responses from the study response files."""

    def __init__(self, response_dir: str | Path):
        root = Path(response_dir)
        self._site_data = self._read_json(root / "site_replies.json")
        self._monitor_data = self._read_json(root / "monitor_decisions.json")

    @staticmethod
    def _read_json(path: Path) -> dict:
        try:
            with path.open(encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise StudyDataError(f"Unable to read response file {path}") from exc

    @staticmethod
    def _response(key: str, value: list[str]) -> Response:
        if len(value) != 2:
            raise StudyDataError(f"Invalid response for key {key}: {value}")
        return Response(status=value[0], message=value[1], key=key)

    def site_reply(self, domain: str, usubjid: str, sequence: str) -> Response:
        """Return a site reply, falling back to the scripted default on a miss."""
        key = f"{domain.upper()}|{usubjid}|{sequence}"
        replies = self._site_data.get("replies", {})
        value = replies.get(key, self._site_data.get("_default"))
        if value is None:
            raise StudyDataError("site_replies.json has no _default response")
        return self._response(key, value)

    def monitor_decision(
        self,
        finding_code: str,
        usubjid: str | None = None,
        siteid: str | None = None,
    ) -> Response | None:
        """Return a subject decision first, then a site-level decision if available."""
        if not usubjid and not siteid:
            raise ValueError("Provide usubjid or siteid for a monitor lookup")
        decisions = self._monitor_data.get("decisions", {})
        keys = []
        if usubjid:
            keys.append(f"{finding_code}|{usubjid}")
        if siteid:
            keys.append(f"{finding_code}|{siteid}")
        for key in keys:
            if key in decisions:
                return self._response(key, decisions[key])
        return None

    def resubmit_clarification(
        self,
        decision: Response,
        clarification: str,
    ) -> Response:
        """Resubmit a clarification and return the scripted approved result."""
        if decision.status != "CLARIFY":
            return decision
        if not clarification.strip():
            raise ValueError("A clarification answer is required before resubmission")
        return Response(
            status="APPROVED",
            message=f"Clarification submitted: {clarification.strip()}",
            key=decision.key,
        )
