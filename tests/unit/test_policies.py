import pytest
from pydantic import ValidationError

from opspilot.agent.policies import PolicyViolationError, SafetyGuard
from opspilot.agent.schemas import FinalAnswerDecision, ProposedActionDecision


def restart_action(**overrides: object) -> ProposedActionDecision:
    values: dict[str, object] = {
        "tool": "restart_service",
        "arguments": {
            "service": "gateway",
            "instance_ids": ["gateway-1"],
            "reason": "isolate the unhealthy instance",
        },
        "risk": "medium",
        "evidence_ids": ["ev-1"],
        "rollback_plan": "restore the original instance routing",
    }
    values.update(overrides)
    return ProposedActionDecision.model_validate(values)


def test_action_requires_tool_specific_risk() -> None:
    with pytest.raises(ValidationError, match="requires risk=medium"):
        restart_action(risk="high")


def test_action_cannot_reference_unknown_evidence() -> None:
    with pytest.raises(PolicyViolationError, match="unknown evidence"):
        SafetyGuard().validate_action(restart_action(), {"ev-2"})


def test_action_rejects_shell_like_argument_keys() -> None:
    action = restart_action()
    action.arguments["command"] = "restart everything"

    with pytest.raises(PolicyViolationError, match="argument key"):
        SafetyGuard().validate_action(action, {"ev-1"})


def test_action_rejects_shell_control_characters() -> None:
    action = restart_action()
    action.arguments["reason"] = "recover service; delete logs"

    with pytest.raises(PolicyViolationError, match="control characters"):
        SafetyGuard().validate_action(action, {"ev-1"})


def test_answer_without_evidence_must_admit_insufficient_information() -> None:
    answer = FinalAnswerDecision(
        summary="No supported conclusion is available",
        confidence=0.2,
    )

    with pytest.raises(PolicyViolationError, match="declare insufficient"):
        SafetyGuard().validate_final_answer(answer, set())


def test_insufficient_information_cannot_claim_high_confidence() -> None:
    answer = FinalAnswerDecision(
        summary="Available evidence is insufficient",
        confidence=0.9,
        insufficient_information=True,
    )

    with pytest.raises(PolicyViolationError, match="high confidence"):
        SafetyGuard().validate_final_answer(answer, set())


def test_supported_answer_is_accepted() -> None:
    answer = FinalAnswerDecision(
        summary="Gateway saturation is supported by metrics",
        root_causes=["CPU saturation"],
        confidence=0.8,
        evidence_ids=["ev-1"],
        next_steps=["Confirm the affected instance"],
    )

    SafetyGuard().validate_final_answer(answer, {"ev-1"})
