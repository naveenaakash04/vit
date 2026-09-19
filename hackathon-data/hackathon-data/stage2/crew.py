"""Stage 2 review-crew orchestration for the Study Sentinel monitor flow."""

from __future__ import annotations

import json
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from review import findings, load_snapshot
from review.responses import ResponseStore
from stage1.atlas import Atlas


@dataclass
class ReviewReport:
    cut: int
    protocol_version: int
    findings: list[dict[str, Any]] = field(default_factory=list)
    medical_review_decisions: list[dict[str, Any]] = field(default_factory=list)
    queries: list[dict[str, Any]] = field(default_factory=list)
    escalations: list[dict[str, Any]] = field(default_factory=list)
    compliance_deviations: list[dict[str, Any]] = field(default_factory=list)
    site_flags: list[dict[str, Any]] = field(default_factory=list)
    open_queries: list[dict[str, Any]] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    existing_queries_suppressed: list[dict[str, Any]] = field(default_factory=list)
    rejected_escalations: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "cut": self.cut,
            "protocol_version": self.protocol_version,
            "findings": self.findings,
            "medical_review_decisions": self.medical_review_decisions,
            "queries": self.queries,
            "escalations": self.escalations,
            "compliance_deviations": self.compliance_deviations,
            "site_flags": self.site_flags,
            "open_queries": self.open_queries,
            "actions": self.actions,
            "trace": self.trace,
            "summary": self.summary,
            "existing_queries_suppressed": self.existing_queries_suppressed,
            "rejected_escalations": self.rejected_escalations,
        }


class ReviewCrew:
    """A deterministic Stage 2 monitor crew powered by Stage 1 Atlas and persisted memory."""

    def __init__(self, hub_url: str, gateway_url: str, team_key: str, atlas: Atlas):
        self.hub_url = hub_url
        self.gateway_url = gateway_url
        self.team_key = team_key
        self.atlas = atlas
        self.data_dir = Path(self.atlas.graph.data_dir)
        self.response_store = ResponseStore(self.data_dir.parent / "responses")
        self.storage_dir = self.data_dir.parent / "stage2"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.trace_path = self.storage_dir / "trace.jsonl"
        db_path = self.storage_dir / "crew_state.sqlite3"
        self.db = sqlite3.connect(str(db_path), timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self._init_db()
        self.memory = {
            "query_keys": set(self._load_serialized("query_keys", default=[])),
            "escalation_keys": set(self._load_serialized("escalation_keys", default=[])),
            "rejected_escalations": set(self._load_serialized("rejected_escalations", default=[])),
            "subject_cuts": defaultdict(list, self._load_serialized("subject_cuts", default={})),
            "subject_cycles": defaultdict(int, self._load_serialized("subject_cycles", default={})),
            "site_flags": defaultdict(int, self._load_serialized("site_flags", default={})),
            "site_open": set(self._load_serialized("site_open", default=[])),
        }
        self.trace: list[dict[str, Any]] = []

    def reset_memory(self) -> None:
        self.memory = {
            "query_keys": set(),
            "escalation_keys": set(),
            "rejected_escalations": set(),
            "subject_cuts": defaultdict(list),
            "subject_cycles": defaultdict(int),
            "site_flags": defaultdict(int),
            "site_open": set(),
        }
        self.db.execute("DELETE FROM state")
        self.db.commit()

    def close(self) -> None:
        try:
            self.db.close()
        except Exception:
            pass

    def __del__(self) -> None:
        try:
            self.db.close()
        except Exception:
            pass

    def _init_db(self) -> None:
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS trace (
                ts TEXT,
                node TEXT,
                action TEXT,
                payload TEXT
            )
            """
        )
        self.db.commit()

    def _save_serialized(self, key: str, value: Any) -> None:
        self.db.execute(
            "INSERT INTO state(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, sort_keys=True)),
        )
        self.db.commit()

    def _load_serialized(self, key: str, default: Any) -> Any:
        row = self.db.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return default

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _site_for_subject(atlas: Atlas, usubjid: str) -> str:
        subject = atlas.graph.by_subject.get(usubjid, {})
        dm_row = (subject.get("DM") or [{}])[0]
        return (dm_row.get("SITEID") or "UNKNOWN").upper()

    def _issue_key(self, domain: str, usubjid: str, seq: str, code: str) -> str:
        return json.dumps({"domain": domain.upper(), "usubjid": usubjid.upper(), "seq": str(seq), "code": code}, sort_keys=True)

    def _escalation_key(self, code: str, usubjid: str, site: str) -> str:
        return json.dumps({"code": code, "usubjid": usubjid.upper(), "site": site.upper()}, sort_keys=True)

    def _trace(self, node: str, action: str, cut: int, protocol_version: int, **details: Any) -> dict[str, Any]:
        entry = {
            "timestamp": self._now(),
            "node": node,
            "action": action,
            "cut": cut,
            "protocol_version": protocol_version,
            **details,
        }
        self.trace.append(entry)
        self.db.execute(
            "INSERT INTO trace(ts, node, action, payload) VALUES(?, ?, ?, ?)",
            (entry["timestamp"], node, action, json.dumps(entry, sort_keys=True)),
        )
        self.db.commit()
        with self.trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
        return entry

    def _findings_for_cut(self, cut: int) -> list[Any]:
        snapshot = load_snapshot(self.data_dir, cut)
        return findings(snapshot)

    def _protocol_version_for_cut(self, cut: int, override: int | None) -> int:
        if override is not None:
            return int(override)
        snapshot = load_snapshot(self.data_dir, cut)
        return int(snapshot.protocol_version)

    def _record_subject_cut(self, usubjid: str, cut: int) -> int:
        cuts = set(self.memory["subject_cuts"].get(usubjid, []))
        cuts.add(cut)
        self.memory["subject_cuts"][usubjid] = sorted(cuts)
        self._save_serialized("subject_cuts", dict(self.memory["subject_cuts"]))
        count = int(self.memory["subject_cycles"].get(usubjid, 0))
        self.memory["subject_cycles"][usubjid] = count + 1
        self._save_serialized("subject_cycles", dict(self.memory["subject_cycles"]))
        return len(cuts)

    def _site_recur_count(self, site: str) -> int:
        count = int(self.memory["site_flags"].get(site, 0))
        self.memory["site_flags"][site] = count + 1
        self._save_serialized("site_flags", dict(self.memory["site_flags"]))
        return count + 1

    def _screening_alt(self, usubjid: str) -> dict[str, Any] | None:
        rows = self.atlas.graph.by_subject.get(usubjid, {}).get("LB", [])
        screening = [row for row in rows if (row.get("VISIT", "") or "").upper() == "SCREENING" and row.get("LBTESTCD", "").upper() == "ALT"]
        if not screening:
            return None
        row = screening[0]
        value = row.get("LBORRES")
        if value is None:
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        return {"value": numeric, "unit": row.get("LBORRESU", ""), "record": {"domain": "LB", "usubjid": usubjid, "seq": row.get("LBSEQ", "1")}, "row": row}

    def _screening_alt_elevated(self, usubjid: str) -> bool:
        info = self._screening_alt(usubjid)
        if not info or "row" not in info:
            return False
        row = info["row"]
        ref_range = self.atlas._lab_range("ALT", row)
        if ref_range is None:
            return False
        try:
            high_val = float(ref_range.get("HIGH", 0))
            if high_val <= 0:
                return False
            val = info["value"]
            val_unit = info.get("unit", "")
            range_unit = ref_range.get("UNIT", "")
            if val_unit == "ukat/L" and range_unit == "U/L":
                val = val * 60
            elif val_unit == "U/L" and range_unit == "ukat/L":
                val = val / 60
            return val > 2 * high_val
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _as_record(domain: str, usubjid: str, seq: str) -> dict[str, str]:
        return {"domain": domain.upper(), "usubjid": usubjid, "seq": str(seq)}

    def _query_is_new(self, finding: Any, domain: str, usubjid: str, seq: str) -> bool:
        key = self._issue_key(domain, usubjid, seq, finding.code)
        already = key in self.memory["query_keys"]
        if not already:
            self.memory["query_keys"].add(key)
            self._save_serialized("query_keys", sorted(self.memory["query_keys"]))
        return not already

    def _escalation_is_new(self, code: str, usubjid: str, site: str) -> bool:
        key = self._escalation_key(code, usubjid, site)
        if key in self.memory["rejected_escalations"]:
            return False
        already = key in self.memory["escalation_keys"]
        if not already:
            self.memory["escalation_keys"].add(key)
            self._save_serialized("escalation_keys", sorted(self.memory["escalation_keys"]))
        return not already

    def _medical_review(self, finding: Any, cut: int, protocol_version: int) -> dict[str, Any]:
        evidence = [self._as_record(finding.domain, finding.usubjid, finding.sequence)]
        decision = "monitor_only"
        severity = getattr(finding, "severity", "HIGH")
        reason = finding.message
        alternatives = [
            "Monitor and document the issue.",
            "Escalate if the signal persists or an event is serious.",
        ]

        code = getattr(finding, "code", "")
        usubjid = getattr(finding, "usubjid", "")
        domain = getattr(finding, "domain", "")

        # Check cross-cycle frequency: subjects flagged across multiple distinct data cuts trigger escalation
        cuts_seen = set(self.memory["subject_cuts"].get(usubjid, []))
        has_prior_cuts = len(cuts_seen - {cut}) >= 1

        if code in {"SERIOUS_AE", "SAE_MISCODED"} or (domain == "AE" and ("serious" in reason.lower() or "hospitalisation" in reason.lower())):
            decision = "escalate"
            severity = "CRITICAL"
            reason = "Hospitalisation or serious AE criteria are met even when AESER is N; the protocol requires expedited reporting."
            alternatives = [
                "Expedite report and notify sponsor safety desk.",
                "Do not accept AESER=N as sufficient when AESHOSP=Y.",
            ]
        elif code == "HYS_LAW_CANDIDATE":
            if self._screening_alt_elevated(usubjid):
                decision = "monitor_only"
                severity = "LOW"
                reason = "Potential liver signal exists, but screening ALT was already elevated at baseline (> 2x ULN); keep in monitoring with explanation."
                alternatives = [
                    "Continue safety monitoring without dosing hold.",
                    "Review concomitant medications and baseline liver disease history.",
                ]
            else:
                decision = "escalate"
                severity = "HIGH"
                reason = "Potential Hy's law candidate requires medical review and dosing hold decision."
                alternatives = [
                    "Review screening ALT and concomitant hepatotoxic medication.",
                    "If no explanatory factor exists, escalate to medical monitor.",
                ]
        elif has_prior_cuts:
            decision = "escalate"
            severity = "HIGH"
            reason = f"Subject {usubjid} flagged across multiple distinct data cuts ({sorted(cuts_seen)}); automatically escalated for medical review."
            alternatives = [
                "Schedule comprehensive subject clinical audit.",
                "Review cumulative findings with the medical monitor.",
            ]
        elif domain in {"LB", "EX", "CM", "VS", "EG", "DS"}:
            decision = "query"
            reason = f"Data discrepancy ({code}): {finding.message}"
            alternatives = [
                "Issue a site query for the specific record.",
                "Keep the finding in monitoring until the site is responsive.",
            ]

        return {
            "code": code or "UNKNOWN",
            "usubjid": usubjid,
            "domain": domain,
            "sequence": getattr(finding, "sequence", ""),
            "decision": decision,
            "severity": severity,
            "reason": reason,
            "evidence": evidence,
            "alternatives": alternatives,
            "cut": cut,
            "protocol_version": protocol_version,
        }

    def _data_quality_query(self, finding: Any, kind: str) -> dict[str, Any]:
        record = self._as_record(finding.domain, finding.usubjid, finding.sequence)
        msg = f"Please review {record['domain']} record {record['usubjid']} sequence {record['seq']}: {finding.message}"
        query = {
            "id": f"Q-{len(self.memory['query_keys']) + 1:04d}",
            "status": "OPEN",
            "code": getattr(finding, "code", "UNKNOWN"),
            "domain": record["domain"],
            "usubjid": record["usubjid"],
            "sequence": record["seq"],
            "seq": record["seq"],
            "site": self._site_for_subject(self.atlas, record["usubjid"]),
            "issue": kind,
            "text": msg,
            "message": msg,
            "evidence": [record],
            "created_at": self._now(),
            "cut": self.atlas.graph.current_cut,
        }
        return query

    def _human_gate_decision(self, escalation: dict[str, Any]) -> dict[str, Any]:
        code = escalation["code"]
        usubjid = escalation["usubjid"]
        site = escalation["site"]
        decision = self.response_store.monitor_decision(code, usubjid=usubjid, siteid=site)
        if decision is None:
            return {"status": "APPROVED", "reason": "No monitor override supplied; default to approved action for traceability."}
        status = decision.status.upper()
        if status == "APPROVED":
            return {"status": "APPROVED", "reason": decision.message}
        if status == "REJECTED":
            return {"status": "REJECTED", "reason": decision.message}
        if status == "CLARIFY":
            return {"status": "CLARIFY", "reason": decision.message}
        return {"status": "REJECTED", "reason": f"Unexpected monitor status {decision.status}; downgraded to monitoring."}

    def _answer_clarification(self, question: str, usubjid: str) -> str:
        lowered = question.lower()
        patient = self.atlas.graph.patient360(usubjid) or {}
        labs = patient.get("labs", [])
        conmeds = patient.get("concomitant_medications", [])
        doses = patient.get("dosing", [])
        aes = patient.get("adverse_events", [])

        # Screening / Baseline Liver Chemistry
        if any(w in lowered for w in ("screening", "baseline", "alt", "ast", "liver", "bili", "transaminase")):
            screening_labs = [r for r in labs if (r.get("VISIT") or "").upper() == "SCREENING"]
            alt = next((r for r in screening_labs if r.get("LBTESTCD") == "ALT"), None)
            ast = next((r for r in screening_labs if r.get("LBTESTCD") == "AST"), None)
            bili = next((r for r in screening_labs if r.get("LBTESTCD") == "BILI"), None)
            parts = []
            if alt:
                parts.append(f"Screening ALT was {alt.get('LBORRES')} {alt.get('LBORRESU')} (LB seq {alt.get('LBSEQ')})")
            if ast:
                parts.append(f"AST was {ast.get('LBORRES')} {ast.get('LBORRESU')} (LB seq {ast.get('LBSEQ')})")
            if bili:
                parts.append(f"Bilirubin was {bili.get('LBORRES')} {bili.get('LBORRESU')} (LB seq {bili.get('LBSEQ')})")
            
            cm_summary = f"{len(conmeds)} concomitant medication(s) reported" if conmeds else "no concomitant hepatotoxic medications recorded"
            if conmeds:
                cm_names = ", ".join(c.get("CMTRT", "Med") for c in conmeds[:3])
                cm_summary += f" ({cm_names})"
            
            if parts:
                return f"For subject {usubjid}: {'; '.join(parts)}; {cm_summary}."

        # Concomitant Medications
        if any(w in lowered for w in ("conmed", "medication", "drug", "prohibited")):
            if not conmeds:
                return f"Subject {usubjid} has no concomitant medications recorded in CM domain."
            cm_details = [f"{c.get('CMTRT')} ({c.get('CMCLAS', 'Class')}, seq {c.get('CMSEQ')})" for c in conmeds]
            return f"Concomitant medications for {usubjid}: {'; '.join(cm_details)}."

        # Dosing
        if any(w in lowered for w in ("dose", "exposure", "treatment")):
            if not doses:
                return f"No dosing records found for subject {usubjid}."
            last_dose = doses[-1]
            return f"Subject {usubjid} received {len(doses)} dose(s); latest dose was {last_dose.get('EXDOSE')} {last_dose.get('EXDOSU')} on {last_dose.get('EXDTC')} (EX seq {last_dose.get('EXSEQ')})."

        # General Patient Summary fallback
        dm = patient.get("demographics", {})
        return (
            f"Subject {usubjid} profile: Arm {dm.get('ARM', 'N/A')}, Site {dm.get('SITEID', 'N/A')}, "
            f"{len(labs)} lab records, {len(aes)} AE records, {len(conmeds)} ConMeds, {len(doses)} doses."
        )

    def _submit_api(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.hub_url and not self.gateway_url:
            return {"status": "SIMULATED", "id": f"{path.strip('/')}-{len(payload.get('evidence', []))}"}
        target = self.gateway_url if path.startswith("/escalations") else self.hub_url
        request = urllib.request.Request(
            f"{target}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                body = response.read().decode("utf-8", errors="replace")
                return {"status": "OK", "http_status": response.status, "body": body}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return {"status": "ERROR", "http_status": exc.code, "body": body}
        except Exception as exc:  # pragma: no cover - network path only
            return {"status": "ERROR", "error": str(exc)}

    def _maybe_query_for_subject(self, finding: Any) -> dict[str, Any] | None:
        if not getattr(finding, "code", "").startswith(("VISIT_", "RENAL_", "HEPATIC_", "PROHIBITED_", "DUPLICATE_", "MISSING_")):
            return None
        record = self._as_record(finding.domain, finding.usubjid, finding.sequence)
        if not self._query_is_new(finding, record["domain"], record["usubjid"], record["seq"]):
            return None
        query = self._data_quality_query(finding, finding.code)
        return query

    def run_cycle(self, cut: int, protocol_version: int | None = None) -> ReviewReport:
        protocol_version = self._protocol_version_for_cut(cut, protocol_version)
        self.trace = []
        self._trace("detect", "cycle_started", cut=cut, protocol_version=protocol_version, team_key=self.team_key)

        findings_list = self._findings_for_cut(cut)
        self._trace("detect", "findings_detected", cut=cut, protocol_version=protocol_version, count=len(findings_list), findings=[{"code": item.code, "usubjid": item.usubjid, "domain": item.domain, "message": item.message} for item in findings_list[:10]])

        decisions: list[dict[str, Any]] = []
        queries: list[dict[str, Any]] = []
        escalations: list[dict[str, Any]] = []
        compliance_deviations: list[dict[str, Any]] = []
        site_flags: list[dict[str, Any]] = []
        actions: list[dict[str, Any]] = []
        open_queries: list[dict[str, Any]] = []
        suppressed_queries: list[dict[str, Any]] = []
        rejected_escalations: list[dict[str, Any]] = []

        for finding in findings_list:
            decision = self._medical_review(finding, cut, protocol_version)
            decisions.append(decision)
            self._trace(
                "medical_review",
                "reviewed",
                cut=cut,
                protocol_version=protocol_version,
                code=finding.code,
                usubjid=finding.usubjid,
                severity=decision["severity"],
                rationale=decision["reason"],
                evidence=decision["evidence"],
            )

            if decision["decision"] == "query":
                key = self._issue_key(finding.domain, finding.usubjid, finding.sequence, finding.code)
                if key in self.memory["query_keys"]:
                    suppressed_queries.append({"code": finding.code, "usubjid": finding.usubjid, "domain": finding.domain, "seq": finding.sequence, "reason": "duplicate query suppressed"})
                    self._trace(
                        "data_manager",
                        "duplicate_query_suppressed",
                        cut=cut,
                        protocol_version=protocol_version,
                        code=finding.code,
                        usubjid=finding.usubjid,
                        domain=finding.domain,
                        seq=finding.sequence,
                        reason="query already raised for this record",
                    )
                    continue
                query = self._data_quality_query(finding, "data_discrepancy")
                query["node"] = "data_manager"
                api_result = self._submit_api("/queries", query)
                query["api_result"] = api_result
                queries.append(query)
                self._trace(
                    "data_manager",
                    "query_created",
                    cut=cut,
                    protocol_version=protocol_version,
                    query=query,
                    evidence=query["evidence"],
                    api_result=api_result,
                )
                self.memory["query_keys"].add(key)
                self._save_serialized("query_keys", sorted(self.memory["query_keys"]))

            elif decision["decision"] == "escalate":
                site = self._site_for_subject(self.atlas, finding.usubjid)
                key = self._escalation_key(finding.code, finding.usubjid, site)
                if key in self.memory["rejected_escalations"] or key in self.memory["escalation_keys"]:
                    self._trace(
                        "medical_review",
                        "duplicate_escalation_suppressed",
                        cut=cut,
                        protocol_version=protocol_version,
                        code=finding.code,
                        usubjid=finding.usubjid,
                        site=site,
                        reason="escalation already raised or rejected earlier",
                    )
                    continue
                escalation = {
                    "id": f"E-{len(self.memory['escalation_keys']) + 1}",
                    "node": "medical_review",
                    "code": finding.code,
                    "usubjid": finding.usubjid,
                    "site": site,
                    "severity": decision["severity"],
                    "summary": decision["reason"],
                    "evidence": decision["evidence"],
                    "alternatives": decision["alternatives"],
                    "status": "PENDING",
                }
                escalations.append(escalation)
                self.memory["escalation_keys"].add(key)
                self._save_serialized("escalation_keys", sorted(self.memory["escalation_keys"]))
                self._trace(
                    "medical_review",
                    "escalation_drafted",
                    cut=cut,
                    protocol_version=protocol_version,
                    escalation=escalation,
                    evidence=escalation["evidence"],
                )

            else:
                self._trace(
                    "medical_review",
                    "monitor_only",
                    cut=cut,
                    protocol_version=protocol_version,
                    code=finding.code,
                    usubjid=finding.usubjid,
                    reason=decision["reason"],
                    evidence=decision["evidence"],
                )

        # Record subject hits across cuts for repeat-offender escalation in future distinct cuts
        for finding in findings_list:
            if getattr(finding, "usubjid", None):
                self._record_subject_cut(finding.usubjid, cut)

        # Compliance stage: evaluate against the protocol version active at this cut
        snapshot = load_snapshot(self.data_dir, cut)
        compliance_findings = findings(snapshot)
        for item in compliance_findings:
            compliance_deviations.append({
                "code": item.code,
                "usubjid": item.usubjid,
                "domain": item.domain,
                "seq": item.sequence,
                "message": item.message,
                "severity": getattr(item, "severity", "HIGH"),
            })
            self._trace(
                "compliance",
                "deviation_found",
                cut=cut,
                protocol_version=protocol_version,
                code=item.code,
                usubjid=item.usubjid,
                domain=item.domain,
                seq=item.sequence,
                message=item.message,
            )

        site_counts: defaultdict[str, int] = defaultdict(int)
        for item in compliance_deviations:
            site = self._site_for_subject(self.atlas, item["usubjid"])
            site_counts[site] += 1
            if site_counts[site] >= 2:
                flag = {
                    "site": site,
                    "status": "OPEN",
                    "reason": f"Recurring protocol or data issues across site {site} ({site_counts[site]} deviations) require site-level review.",
                    "count": site_counts[site],
                    "evidence": [{"usubjid": item["usubjid"], "code": item["code"]}],
                }
                if not any(existing["site"] == site for existing in site_flags):
                    site_flags.append(flag)
                    self._site_recur_count(site)
                    self._trace("compliance", "site_flag_raised", cut=cut, protocol_version=protocol_version, **flag)

        self._save_serialized("site_open", sorted(self.memory["site_open"]))

        # Human gate stage.
        for escalation in escalations:
            decision = self._human_gate_decision(escalation)
            self._trace(
                "human_gate",
                "decision",
                cut=cut,
                protocol_version=protocol_version,
                escalation_id=escalation["id"],
                decision=decision["status"],
                reason=decision["reason"],
            )
            if decision["status"] == "APPROVED":
                actions.append({
                    "id": escalation["id"],
                    "status": "APPROVED",
                    "action": f"Execute approved action for {escalation['usubjid']}",
                    "reason": decision["reason"],
                })
            elif decision["status"] == "REJECTED":
                escalation["status"] = "REJECTED"
                actions.append({
                    "id": escalation["id"],
                    "status": "REJECTED",
                    "action": "Downgrade to monitoring and do not re-escalate",
                    "reason": decision["reason"],
                })
                self.memory["rejected_escalations"].add(self._escalation_key(escalation["code"], escalation["usubjid"], escalation["site"]))
                self._save_serialized("rejected_escalations", sorted(self.memory["rejected_escalations"]))
                rejected_escalations.append({
                    "id": escalation["id"],
                    "code": escalation["code"],
                    "usubjid": escalation["usubjid"],
                    "reason": decision["reason"],
                })
                self._trace(
                    "human_gate",
                    "rejected_downgraded",
                    cut=cut,
                    protocol_version=protocol_version,
                    escalation_id=escalation["id"],
                    reason=decision["reason"],
                )
            elif decision["status"] == "CLARIFY":
                answer = self._answer_clarification(decision["reason"], escalation["usubjid"])
                self._trace(
                    "human_gate",
                    "clarification_requested",
                    cut=cut,
                    protocol_version=protocol_version,
                    escalation_id=escalation["id"],
                    question=decision["reason"],
                    graph_answer=answer,
                )
                resubmission = {
                    "id": escalation["id"],
                    "code": escalation["code"],
                    "usubjid": escalation["usubjid"],
                    "site": escalation["site"],
                    "summary": escalation["summary"],
                    "answer": answer,
                    "evidence": escalation["evidence"],
                }
                api_result = self._submit_api("/escalations", resubmission)
                self._trace(
                    "human_gate",
                    "clarification_resubmitted",
                    cut=cut,
                    protocol_version=protocol_version,
                    escalation_id=escalation["id"],
                    api_result=api_result,
                    answer=answer,
                )
                escalation["status"] = "CLARIFIED"
                if api_result.get("status") in ("OK", "SIMULATED"):
                    actions.append({"id": escalation["id"], "status": "CLARIFIED", "action": "Clarification answered and resubmitted", "reason": answer})
                else:
                    actions.append({"id": escalation["id"], "status": "ERROR", "action": "Clarification resubmission failed", "reason": str(api_result)})

        # execute stage report assembly
        for query in queries:
            open_queries.append(query)
        report = ReviewReport(
            cut=cut,
            protocol_version=protocol_version,
            findings=[{"code": item.code, "usubjid": item.usubjid, "domain": item.domain, "sequence": item.sequence, "message": item.message, "severity": item.severity} for item in findings_list],
            medical_review_decisions=decisions,
            queries=queries,
            escalations=escalations,
            compliance_deviations=compliance_deviations,
            site_flags=site_flags,
            open_queries=open_queries,
            actions=actions,
            trace=self.trace,
            summary=f"{len(findings_list)} findings, {len(queries)} queries, {len(escalations)} escalations, {len(compliance_deviations)} deviations.",
            existing_queries_suppressed=suppressed_queries,
            rejected_escalations=rejected_escalations,
        )
        self._trace("execute", "report_ready", cut=cut, protocol_version=protocol_version, query_count=len(queries), escalation_count=len(escalations), deviation_count=len(compliance_deviations))
        report.trace = self.trace
        return report
