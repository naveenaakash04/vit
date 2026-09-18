"""Eligibility and exclusion criteria checks."""


from __future__ import annotations

from ..models import Finding, StudyDataError, StudySnapshot, parse_number


def _finding(code, row, domain, sequence, message, severity="HIGH"):
    return Finding(code, row["USUBJID"], domain, sequence, message, severity)


def _screening_labs(snapshot, usubjid):
    return {
        row["LBTESTCD"]: row
        for row in snapshot.table("LB")
        if row["USUBJID"] == usubjid and row["VISIT"].upper() == "SCREENING"
    }


def _range_for(snapshot, test, row):
    usubjid = row.get("USUBJID", "")
    site = row.get("SITEID") or row.get("LAB")
    if not site and usubjid:
        dm_rows = [r for r in snapshot.table("DM") if r.get("USUBJID") == usubjid]
        if dm_rows:
            site = dm_rows[0].get("SITEID")
    if not site and usubjid:
        parts = usubjid.split("-")
        if len(parts) > 1:
            site = parts[1]

    site = (site or "").upper()
    unit = row.get("LBORRESU")

    # 1. Site-specific match with matching unit
    if site:
        for r in snapshot.reference_ranges:
            if r.get("LBTESTCD") == test and r.get("LAB", "").upper() == site and (not unit or r.get("UNIT") == unit):
                return r
        for r in snapshot.reference_ranges:
            if r.get("LBTESTCD") == test and r.get("LAB", "").upper() == site:
                return r

    # 2. Central lab match with matching unit
    for r in snapshot.reference_ranges:
        if r.get("LBTESTCD") == test and r.get("LAB", "").upper() == "CENTRAL" and (not unit or r.get("UNIT") == unit):
            return r

    # 3. Any match on test and unit
    if unit:
        for r in snapshot.reference_ranges:
            if r.get("LBTESTCD") == test and r.get("UNIT") == unit:
                return r

    # 4. Central lab match
    for r in snapshot.reference_ranges:
        if r.get("LBTESTCD") == test and r.get("LAB", "").upper() == "CENTRAL":
            return r

    # 5. Any match on test
    for r in snapshot.reference_ranges:
        if r.get("LBTESTCD") == test:
            return r

    raise StudyDataError(f"No reference range found for {test} in {row}")


def screening_labs(snapshot, usubjid):
    return _screening_labs(snapshot, usubjid)


def lab_range(snapshot, test, row):
    return _range_for(snapshot, test, row)


def eligibility_findings(snapshot):
    findings = []
    
    # Pre-index screening labs by subject to avoid repeated table scans
    screening_labs_by_subj: dict[str, dict[str, dict[str, str]]] = {}
    for row in snapshot.table("LB"):
        if row.get("VISIT", "").upper() == "SCREENING":
            usubjid = row.get("USUBJID")
            test = row.get("LBTESTCD")
            if usubjid and test:
                if usubjid not in screening_labs_by_subj:
                    screening_labs_by_subj[usubjid] = {}
                screening_labs_by_subj[usubjid][test] = row

    # Pre-index MH records by subject
    mh_by_subj: dict[str, list[dict[str, str]]] = {}
    for row in snapshot.table("MH"):
        usubjid = row.get("USUBJID")
        if usubjid:
            if usubjid not in mh_by_subj:
                mh_by_subj[usubjid] = []
            mh_by_subj[usubjid].append(row)

    for subject in snapshot.table("DM"):
        usubjid = subject.get("USUBJID", "")
        age = parse_number(subject.get("AGE"))
        hba1c = parse_number(subject.get("SCR_HBA1C"))
        if age is not None and not 18 <= age <= 75:
            findings.append(_finding("AGE_OUT_OF_RANGE", subject, "DM", "1", f"Age {age} is outside 18-75"))
        if hba1c is not None and not 7.0 <= hba1c <= 10.5:
            findings.append(_finding("SCREENING_HBA1C_OUT_OF_RANGE", subject, "DM", "1", f"Screening HbA1c {hba1c} is outside 7.0-10.5"))

        labs = screening_labs_by_subj.get(usubjid, {})
        for test in ("ALT", "AST"):
            row = labs.get(test)
            if row is None:
                continue
            value = parse_number(row.get("LBORRES"))
            try:
                ref_range = _range_for(snapshot, test, row)
                if value is not None and value > 2 * float(ref_range["HIGH"]):
                    findings.append(_finding("HEPATIC_EXCLUSION", row, "LB", row.get("LBSEQ", "1"), f"Screening {test} {value} exceeds 2x ULN"))
            except StudyDataError:
                continue
        if snapshot.protocol_version >= 2:
            row = labs.get("CREAT")
            value = parse_number(row.get("LBORRES")) if row else None
            if value is not None and value > 1.5:
                findings.append(_finding("RENAL_EXCLUSION", row, "LB", row.get("LBSEQ", "1"), f"Screening creatinine {value} exceeds 1.5 mg/dL"))
        for row in mh_by_subj.get(usubjid, []):
            if "PREGN" in row.get("MHTERM", "").upper():
                findings.append(_finding("PREGNANCY_EXCLUSION", row, "MH", row.get("MHSEQ", "1"), "Pregnancy is recorded in medical history"))
    return findings
