import json

import pytest

from opspilot.agent.parser import ModelOutputError, parse_model_decision
from opspilot.agent.schemas import FinalAnswerDecision


def valid_answer_json() -> str:
    return json.dumps(
        {
            "type": "final_answer",
            "summary": "The available evidence supports a diagnosis",
            "root_causes": ["Redis timeout"],
            "confidence": 0.8,
            "evidence_ids": ["evidence-1"],
            "next_steps": ["Check Redis latency"],
            "insufficient_information": False,
        }
    )


def test_valid_complete_json_is_parsed() -> None:
    decision = parse_model_decision(valid_answer_json())
    assert isinstance(decision, FinalAnswerDecision)
    assert decision.confidence == 0.8


def test_invalid_json_is_rejected_without_repair() -> None:
    with pytest.raises(ModelOutputError, match="not a valid decision"):
        parse_model_decision('{"type": "final_answer"')


def test_repair_function_is_called_at_most_once() -> None:
    repair_calls = 0

    def repair(raw: str, validation_error: str) -> str:
        nonlocal repair_calls
        repair_calls += 1
        assert raw == "invalid"
        assert validation_error
        return valid_answer_json()

    decision = parse_model_decision("invalid", repair=repair)
    assert isinstance(decision, FinalAnswerDecision)
    assert repair_calls == 1


def test_failed_repair_is_not_retried_again() -> None:
    repair_calls = 0

    def repair(raw: str, validation_error: str) -> str:
        nonlocal repair_calls
        repair_calls += 1
        return "still invalid"

    with pytest.raises(ModelOutputError, match="after one repair attempt"):
        parse_model_decision("invalid", repair=repair)
    assert repair_calls == 1


def test_markdown_wrapped_json_is_not_implicitly_extracted() -> None:
    wrapped = f"Here is the command:\n```json\n{valid_answer_json()}\n```"
    with pytest.raises(ModelOutputError):
        parse_model_decision(wrapped)


def test_unknown_tool_is_rejected() -> None:
    raw = json.dumps(
        {
            "type": "tool_call",
            "tool": "run_shell",
            "arguments": {"command": "whoami"},
            "reason": "Inspect the current operating system user",
        }
    )
    with pytest.raises(ModelOutputError):
        parse_model_decision(raw)


def test_extra_command_field_is_rejected() -> None:
    payload = json.loads(valid_answer_json())
    payload["command"] = "restart everything"
    with pytest.raises(ModelOutputError):
        parse_model_decision(json.dumps(payload))
