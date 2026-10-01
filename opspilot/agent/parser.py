from collections.abc import Callable

from pydantic import TypeAdapter, ValidationError

from opspilot.agent.schemas import ModelDecision


class ModelOutputError(ValueError):
    """Raised when model output remains invalid after the single repair attempt."""


RepairFunction = Callable[[str, str], str]
_DECISION_ADAPTER: TypeAdapter[ModelDecision] = TypeAdapter(ModelDecision)


def parse_model_decision(
    raw_output: str,
    *,
    repair: RepairFunction | None = None,
) -> ModelDecision:
    """Validate a complete JSON decision, allowing at most one repair call."""
    try:
        return _DECISION_ADAPTER.validate_json(raw_output)
    except ValidationError as first_error:
        if repair is None:
            raise ModelOutputError("Model output is not a valid decision") from first_error
        repaired = repair(raw_output, str(first_error))
        try:
            return _DECISION_ADAPTER.validate_json(repaired)
        except ValidationError as repaired_error:
            raise ModelOutputError(
                "Model output is invalid after one repair attempt"
            ) from repaired_error
