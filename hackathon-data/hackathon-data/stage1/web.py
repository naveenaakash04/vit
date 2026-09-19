"""Local browser interface for the Atlas study review engine."""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    from .atlas import Atlas, parse_date
except (ImportError, ValueError):
    try:
        from stage1.atlas import Atlas, parse_date
    except ImportError:
        from atlas import Atlas, parse_date


def build_stage2_report(data_dir: str | Path, cut: int = 12, protocol_version: int | None = None) -> dict[str, Any]:
    """Execute ReviewCrew and return the serializable Stage 2 review report."""
    try:
        from stage2.crew import ReviewCrew
    except (ImportError, ValueError):
        try:
            from ..stage2.crew import ReviewCrew
        except (ImportError, ValueError):
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
            from stage2.crew import ReviewCrew

    try:
        from stage1.atlas import Atlas
    except (ImportError, ValueError):
        try:
            from .atlas import Atlas
        except (ImportError, ValueError):
            from atlas import Atlas

    atlas = Atlas(str(data_dir), cut=cut)
    crew = ReviewCrew("", "", "team-sentinel", atlas)
    report = crew.run_cycle(cut, protocol_version)
    result = report.as_dict()
    crew.close()
    return result


def _first_date(row: dict[str, str]) -> str | None:
    for key in ("AESTDTC", "LBDTC", "VSDTC", "EXSTDTC", "CMSTDTC", "DSSTDTC", "MHSTDTC", "EGDTC", "VISITDTC", "DMDTC", "RFSTDTC", "DATE", "DTC"):
        value = row.get(key)
        if value:
            return str(value)
    return None


def _first_numeric_value(row: dict[str, str], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip().replace(",", ".")
        if not text or text.upper() in {"NA", "N/A", "ND", "NULL", "MISSING"}:
            continue
        try:
            return float(text)
        except ValueError:
            continue
    return None


def _risk_lab_signal(atlas: Atlas, row: dict[str, str], test_code: str) -> tuple[float, float] | None:
    value = _first_numeric_value(row, ("LBSTRESN", "LBORRES", "LBSTRESC"))
    if value is None:
        return None
    reference = atlas._lab_range(test_code, row)
    if reference is None:
        return None
    try:
        upper_limit = float(reference["HIGH"])
    except (KeyError, TypeError, ValueError):
        return None
    unit = str(row.get("LBORRESU") or "")
    reference_unit = str(reference.get("UNIT") or "")
    if unit == "ukat/L" and reference_unit == "U/L":
        value *= 60
    elif unit == "U/L" and reference_unit == "ukat/L":
        value /= 60
    return value, upper_limit * (60 if reference_unit == "ukat/L" and unit == "ukat/L" else 1)


_cached_atlas: Atlas | None = None


def _get_atlas(atlas: Atlas | None = None) -> Atlas:
    global _cached_atlas
    if atlas is not None:
        return atlas
    if _cached_atlas is None:
        data_dir = Path(__file__).resolve().parent.parent / "data"
        _cached_atlas = Atlas(str(data_dir), cut=12)
        _cached_atlas.graph.build()
    return _cached_atlas


def _build_subject_risk(subject_id: str, atlas: Atlas | None = None) -> dict[str, object]:
    atl = _get_atlas(atlas)
    patient = atl.graph.patient360(subject_id)
    if not patient:
        return {
            "subject_id": subject_id,
            "risk_score": 0,
            "risk_level": "Low",
            "summary": "No subject records were found for this ID.",
            "evidence": [],
            "details": {},
        }

    score = 0
    evidence: list[dict[str, object]] = []
    details: dict[str, object] = {"site": (patient.get("demographics") or {}).get("SITEID"), "lab_flags": [], "qtc_flags": [], "dose_flags": []}
    demographics = patient.get("demographics") or {}

    age = _first_numeric_value(demographics, ("AGE",))
    if age is not None and age >= 65:
        score += 10
        evidence.append({"category": "Demographics", "severity": "Moderate", "label": "Age >= 65 years", "value": age})

    for row in patient.get("labs", []):
        test_code = str(row.get("LBTESTCD") or row.get("LBTEST") or "").upper()
        if not test_code:
            continue
        signal = _risk_lab_signal(atl, row, test_code)
        if signal is None:
            continue
        value, limit = signal
        if test_code in {"ALT", "AST"} and value > 3 * limit:
            score += 30
            evidence.append({"category": "Laboratory", "severity": "Critical", "label": f"{test_code} > 3x ULN", "value": value})
            details["lab_flags"].append({"test": test_code, "value": value, "limit": limit})
        elif test_code in {"BILI", "BILIRUBIN"} and value > 2 * limit:
            score += 25
            evidence.append({"category": "Laboratory", "severity": "High", "label": f"{test_code} elevated beyond 2x ULN", "value": value})
            details["lab_flags"].append({"test": test_code, "value": value, "limit": limit})

    for row in patient.get("ecg", []):
        test_code = str(row.get("EGTESTCD") or row.get("EGTEST") or "").upper()
        value = _first_numeric_value(row, ("EGSTRESN", "EGORRES", "EGSTRESC"))
        if test_code == "QTCF" and value is not None and value >= 500:
            score += 25
            evidence.append({"category": "ECG", "severity": "High", "label": "QTc above danger threshold", "value": value})
            details["qtc_flags"].append({"test": test_code, "value": value})

    for row in patient.get("dosing", []):
        dose = _first_numeric_value(row, ("EXDOSE", "EXDOSN"))
        if dose is not None and dose not in {0.0, 10.0}:
            score += 20
            evidence.append({"category": "Exposure", "severity": "Moderate", "label": "Dose deviates from protocol 0 or 10 mg", "value": dose})
            details["dose_flags"].append({"dose": dose})

    for row in patient.get("concomitant_medications", []):
        class_name = str(row.get("CMCLAS") or "").upper()
        if "ACE" in class_name or "INHIBITOR" in class_name:
            score += 5
            evidence.append({"category": "Concomitant Medication", "severity": "Low", "label": "ACE inhibitor co-medication present", "value": row.get("CMTRT")})
            break

    for row in patient.get("adverse_events", []):
        if str(row.get("AESER") or "").upper() == "Y" or str(row.get("AESHOSP") or "").upper() == "Y":
            score += 18
            evidence.append({"category": "Adverse Event", "severity": "High", "label": "Serious AE or hospitalization flagged", "value": row.get("AETERM")})
            break

    risk_score = min(max(score, 0), 100)
    risk_level = "Critical" if risk_score >= 75 else "High" if risk_score >= 50 else "Moderate" if risk_score >= 25 else "Low"
    summary = f"Subject {subject_id} has a {risk_level.lower()} risk profile based on {len(evidence)} supporting signal(s) from the study records and protocol context."
    return {
        "subject_id": subject_id,
        "risk_score": risk_score,
        "risk_level": risk_level,
        "summary": summary,
        "evidence": evidence,
        "details": details,
    }


def _build_subject_replay(subject_id: str, atlas: Atlas | None = None) -> dict[str, object]:
    atl = _get_atlas(atlas)
    patient = atl.graph.patient360(subject_id)
    if not patient:
        return {"subject_id": subject_id, "events": [], "event_count": 0, "summary": "No replay timeline is available for this subject."}

    events: list[dict[str, object]] = []
    for domain, rows in {
        "DM": patient.get("demographics") and [patient.get("demographics")] or [],
        "LB": patient.get("labs", []),
        "AE": patient.get("adverse_events", []),
        "EX": patient.get("dosing", []),
        "CM": patient.get("concomitant_medications", []),
        "EG": patient.get("ecg", []),
        "MH": patient.get("medical_history", []),
        "DS": patient.get("disposition", []),
    }.items():
        for row in rows:
            date = _first_date(row)
            if not date:
                continue
            label = row.get("VISIT") or row.get("LBTESTCD") or row.get("VSTESTCD") or row.get("AETERM") or row.get("CMTRT") or row.get("EXTRT") or row.get("DSDECOD") or row.get("MHTERM") or row.get("EGTESTCD") or domain
            value = _first_numeric_value(row, ("LBORRES", "LBSTRESN", "VSORRES", "VSSTRESN", "EXDOSE", "CMDOSE", "EGORRES", "EGSTRESN", "AGE"))
            if value is None:
                value = row.get("AETERM") or row.get("DSDECOD") or row.get("MHTERM")
            unit = row.get("LBORRESU") or row.get("VSORRESU") or row.get("EXDOSU") or row.get("EGORRESU") or ""
            events.append({"date": str(date), "domain": domain, "label": str(label), "value": value, "unit": str(unit), "source": f"{domain}.csv"})

    events.sort(key=lambda item: (parse_date(str(item["date"])) or date.max, str(item["domain"]), str(item["label"])))
    return {
        "subject_id": subject_id,
        "events": events,
        "event_count": len(events),
        "summary": f"{len(events)} study events were replayed for {subject_id} in chronological order.",
    }


class AtlasServer(ThreadingHTTPServer):
    atlas: Atlas
    static_dir: Path


class RequestHandler(BaseHTTPRequestHandler):
    server: AtlasServer

    def _send_json(self, payload: dict | list, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        if not path.is_file() or path.parent != self.server.static_dir:
            self._send_json({"error": "Not found"}, 404)
            return
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
        }.get(path.suffix, "application/octet-stream")
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        request = urlparse(self.path)
        params = parse_qs(request.query)
        try:
            if request.path == "/api/health":
                self._send_json({"ok": True})
                return
            if request.path == "/api/summary":
                cut = int(params.get("cut", [self.server.atlas.graph.current_cut or 12])[0])
                atlas = Atlas(str(self.server.atlas.graph.data_dir), cut)
                cut_row = next((r for r in atlas.graph.cut_rows if atlas.graph._cut(r, "cut") == cut), None)
                protocol_version = atlas.graph._cut(cut_row, "protocol_version") if cut_row else (3 if cut >= 9 else 2 if cut >= 5 else 1)
                self._send_json({**atlas.graph.metrics, "cut": cut, "protocol_version": protocol_version})
                return
            if request.path == "/api/answer":
                question = params.get("q", [""])[0].strip()
                if not question:
                    self._send_json({"error": "Question is required"}, 400)
                    return
                self._send_json(self.server.atlas.answer(question).as_dict())
                return
            if request.path == "/api/patient":
                raw_usubjid = params.get("usubjid", [""])[0].strip()
                if not raw_usubjid:
                    self._send_json({"error": "USUBJID is required"}, 400)
                    return
                # Automatically extract USUBJID if user passed a formatted ref (e.g. "DS · 042-S01-010 · 1")
                match = re.search(r"\b\d{3}-S\d{1,3}-\d{3}\b", raw_usubjid, re.IGNORECASE)
                usubjid = match.group(0).upper() if match else raw_usubjid.upper()
                patient = self.server.atlas.graph.patient360(usubjid)
                if not patient:
                    self._send_json({"error": f"Subject '{usubjid}' not found"}, 404)
                    return
                self._send_json(patient)
                return
            if request.path == "/api/stage2/report":
                cut = int(params.get("cut", [self.server.atlas.graph.current_cut or 12])[0])
                pv = int(params.get("protocol_version", [0])[0]) or None
                report = build_stage2_report(self.server.atlas.graph.data_dir, cut, pv)
                self._send_json(report)
                return
            if request.path == "/api/risk/predict":
                raw_id = (params.get("subject_id") or params.get("subject") or params.get("usubjid") or [""])[0].strip()
                if not raw_id or raw_id.lower() == "all":
                    if not self.server.atlas.graph.tables:
                        self.server.atlas.graph.build()
                    all_risks = [
                        _build_subject_risk(s, atlas=self.server.atlas)
                        for s in sorted(self.server.atlas.graph.by_subject.keys())
                    ]
                    self._send_json(all_risks)
                    return
                match = re.search(r"\b\d{3}-S\d{1,3}-\d{3}\b", raw_id, re.IGNORECASE)
                subject_id = match.group(0).upper() if match else raw_id.upper()
                self._send_json(_build_subject_risk(subject_id, atlas=self.server.atlas))
                return
            if request.path == "/api/risk/replay":
                raw_id = (params.get("subject_id") or params.get("subject") or params.get("usubjid") or [""])[0].strip()
                if not raw_id:
                    self._send_json({"error": "Please provide a subject_id."}, 400)
                    return
                match = re.search(r"\b\d{3}-S\d{1,3}-\d{3}\b", raw_id, re.IGNORECASE)
                subject_id = match.group(0).upper() if match else raw_id.upper()
                self._send_json(_build_subject_replay(subject_id, atlas=self.server.atlas))
                return
            if request.path == "/api/graph":
                subject_id = params.get("subject_id", [""])[0].strip()
                if not subject_id:
                    self._send_json({"nodes": [], "edges": [], "message": "Subject ID required."}, 400)
                    return
                patient = self.server.atlas.graph.patient360(subject_id)
                if not patient:
                    self._send_json({"nodes": [], "edges": [], "message": "No graph data found for that subject."}, 404)
                    return
                node_id = f"subject:{subject_id}"
                nodes = [{"id": node_id, "label": subject_id, "type": "subject", "color": "#16795e", "shape": "dot", "size": 18, "meta": {"subject_id": subject_id}}]
                edges = []
                domain_map = {
                    "labs": "LB",
                    "adverse_events": "AE",
                    "dosing": "EX",
                    "concomitant_medications": "CM",
                    "ecg": "EG",
                    "medical_history": "MH",
                    "disposition": "DS",
                }
                for key, domain in domain_map.items():
                    for index, row in enumerate(patient.get(key, []), start=1):
                        record_id = f"{domain}:{subject_id}:{index}"
                        nodes.append({"id": record_id, "label": domain, "type": "record", "color": "#5b8cf4", "shape": "box", "size": 12, "meta": {"subject_id": subject_id, "domain": domain, "seq": index}})
                        edges.append({"from": node_id, "to": record_id, "label": "HAS_RECORD", "color": "#5b8cf4"})
                self._send_json({"nodes": nodes, "edges": edges, "selected_subject": subject_id, "legend": [{"label": "Subject", "color": "#16795e"}, {"label": "Record", "color": "#5b8cf4"}]})
                return
            if request.path in {"/", "/index.html"}:
                self._send_file(self.server.static_dir / "index.html")
                return
            self._send_file(self.server.static_dir / request.path.lstrip("/"))
        except (ValueError, KeyError) as exc:
            self._send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data")
    parser.add_argument("--static-dir", type=Path, default=Path(__file__).resolve().parent / "static")
    parser.add_argument("--cut", type=int, default=12)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    server = AtlasServer(("127.0.0.1", args.port), RequestHandler)
    server.atlas = Atlas(str(args.data_dir), args.cut)
    server.static_dir = args.static_dir.resolve()
    print(f"Atlas running at http://localhost:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
