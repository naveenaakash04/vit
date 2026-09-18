"""Protocol visit, exposure, and concomitant-medication checks."""

from __future__ import annotations

from ..models import DATE_COLUMNS, Finding, StudySnapshot, VISIT_DAYS, parse_date, parse_number


def _finding(code, row, domain, sequence, message, severity="HIGH"):
    return Finding(code, row["USUBJID"], domain, sequence, message, severity)


def _record_sequence(domain, row):
    return row.get(f"{domain}SEQ", "1")


def visit_findings(snapshot):
    """Detect visit window deviations using pre-indexed domain records for O(1) retrieval."""
    findings = []
    window = 7 if snapshot.protocol_version == 1 else 3
    
    # Pre-index domain visits by (USUBJID, domain, visit) to avoid O(N * M) nested looping
    visits_by_subject: dict[tuple[str, str, str], dict[str, str]] = {}
    for domain in DATE_COLUMNS:
        for row in snapshot.table(domain):
            usubjid = row.get("USUBJID")
            visit = row.get("VISIT", "").upper()
            if usubjid and visit in VISIT_DAYS:
                key = (usubjid, domain, visit)
                if key not in visits_by_subject:
                    visits_by_subject[key] = row

    for subject in snapshot.table("DM"):
        baseline = parse_date(subject.get("RFSTDTC"))
        if baseline is None:
            continue
        usubjid = subject.get("USUBJID", "")
        for domain in DATE_COLUMNS:
            for visit, target_day in VISIT_DAYS.items():
                row = visits_by_subject.get((usubjid, domain, visit))
                if row is None:
                    continue
                observed = parse_date(row.get(DATE_COLUMNS[domain]))
                if observed is None:
                    continue
                expected = baseline.fromordinal(baseline.toordinal() + target_day)
                delta = abs((observed - expected).days)
                if delta > window:
                    findings.append(
                        _finding(
                            "VISIT_WINDOW_DEVIATION",
                            row,
                            domain,
                            _record_sequence(domain, row),
                            f"{visit} is {delta} days from scheduled date; window is +/-{window} days",
                        )
                    )
    return findings


def exposure_findings(snapshot):
    findings = []
    subjects = {row["USUBJID"]: row for row in snapshot.table("DM")}
    for row in snapshot.table("EX"):
        subject = subjects.get(row.get("USUBJID", ""))
        if subject is None:
            continue
        expected = 10.0 if subject.get("ARM", "").upper() == "DRUG" else 0.0
        actual = parse_number(row.get("EXDOSE"))
        if actual is not None and row.get("EXDOSU", "").lower() == "mg" and actual != expected:
            findings.append(_finding("DOSE_ERROR", row, "EX", row.get("EXSEQ", "1"), f"Administered dose {actual} mg; expected {expected:g} mg"))
    return findings


def medication_findings(snapshot):
    prohibited = {"SYSTEMIC_GLUCORTICOID"}
    if snapshot.protocol_version >= 3:
        prohibited.add("SULFONYLUREA")
    return [
        _finding("PROHIBITED_MEDICATION", row, "CM", row["CMSEQ"], f"{row['CMCLAS']} is prohibited under protocol v{snapshot.protocol_version}")
        for row in snapshot.table("CM")
        if row["CMCLAS"].upper() in prohibited
    ]


def deviation_findings(snapshot):
    return visit_findings(snapshot) + exposure_findings(snapshot) + medication_findings(snapshot)
