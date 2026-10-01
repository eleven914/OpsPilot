"""Background task entry points for OpsPilot."""

from opspilot.tasks.dispatch import DiagnosisDispatchError, dispatch_diagnosis

__all__ = ["DiagnosisDispatchError", "dispatch_diagnosis"]
