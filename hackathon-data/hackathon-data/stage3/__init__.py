"""Stage 3 unattended Study Watch."""

from .models import Explanation, SurveillanceReport

__all__ = ["Explanation", "StudyWatch", "SurveillanceReport"]


def __getattr__(name: str):
	if name == "StudyWatch":
		from .watch import StudyWatch

		return StudyWatch
	raise AttributeError(name)
