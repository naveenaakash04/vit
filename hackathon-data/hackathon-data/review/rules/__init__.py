"""Protocol finding rules grouped by review task."""

from .deviations import deviation_findings
from .eligibility import eligibility_findings
from .safety import safety_findings


def findings(snapshot):
    """Run all implemented protocol checks against one snapshot."""
    checks = (eligibility_findings, deviation_findings, safety_findings)
    result = [finding for check in checks for finding in check(snapshot)]
    return sorted(result, key=lambda item: (item.usubjid, item.domain, item.sequence, item.code))


__all__ = ["findings"]
