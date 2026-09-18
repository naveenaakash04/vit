"""Adverse-event and liver-safety checks."""

from __future__ import annotations

from ..models import Finding, StudySnapshot, parse_date, parse_number
from .eligibility import lab_range


def _finding(code, row, domain, sequence, message, severity="HIGH"):
    return Finding(code, row["USUBJID"], domain, sequence, message, severity)


def adverse_event_findings(snapshot):
    findings = []
    for row in snapshot.table("AE"):
        if row["AESER"].upper() == "Y" or row["AESHOSP"].upper() == "Y":
            code = "SERIOUS_AE"
            message = "Serious adverse event requires safety review"
            if row["AESHOSP"].upper() == "Y" and row["AESER"].upper() != "Y":
                code = "SAE_MISCODED"
                message = "Hospitalisation flag indicates serious AE despite AESER coding"
            findings.append(_finding(code, row, "AE", row["AESEQ"], message))
    return findings


def hy_findings(snapshot):
    findings = []
    by_subject = {}
    for row in snapshot.table("LB"):
        by_subject.setdefault(row["USUBJID"], []).append(row)
    for rows in by_subject.values():
        transaminases = [row for row in rows if row["LBTESTCD"] in {"ALT", "AST"}]
        bilirubin = [row for row in rows if row["LBTESTCD"] == "BILI"]
        for transaminase in transaminases:
            trans_value = parse_number(transaminase["LBORRES"])
            try:
                trans_range = lab_range(snapshot, transaminase["LBTESTCD"], transaminase)
            except StudyDataError:
                continue
            if trans_value is None or trans_range is None:
                continue
            range_high = parse_number(trans_range["HIGH"])
            if range_high is None or range_high <= 0:
                continue
            trans_unit = transaminase.get("LBORRESU", "")
            range_unit = trans_range.get("UNIT", "")
            norm_trans = trans_value
            if trans_unit == "ukat/L" and range_unit == "U/L":
                norm_trans = trans_value * 60
            elif trans_unit == "U/L" and range_unit == "ukat/L":
                norm_trans = trans_value / 60
            if norm_trans <= 3 * range_high:
                continue
            trans_date = parse_date(transaminase["LBDTC"])
            if trans_date is None:
                continue
            for bili in bilirubin:
                bili_date = parse_date(bili["LBDTC"])
                bili_value = parse_number(bili["LBORRES"])
                try:
                    bili_range = lab_range(snapshot, "BILI", bili)
                except StudyDataError:
                    continue
                if bili_date is None or bili_value is None or bili_range is None:
                    continue
                bili_high = parse_number(bili_range["HIGH"])
                if bili_high is None or bili_high <= 0:
                    continue
                if abs((trans_date - bili_date).days) <= 14 and bili_value > 2 * bili_high:
                    findings.append(_finding("HYS_LAW_CANDIDATE", transaminase, "LB", transaminase["LBSEQ"], f"{transaminase['LBTESTCD']} exceeds 3x ULN with bilirubin record {bili['LBSEQ']} above 2x ULN within 14 days"))
                    break
    return findings


def safety_findings(snapshot):
    return adverse_event_findings(snapshot) + hy_findings(snapshot)
