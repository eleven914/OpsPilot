import pytest

from opspilot.agent.state import ALLOWED_TRANSITIONS, AgentState, assert_transition


def test_legal_transition() -> None:
    assert_transition(AgentState.NEW, AgentState.TRIAGE)


def test_illegal_transition_is_rejected() -> None:
    with pytest.raises(ValueError, match="Illegal state transition"):
        assert_transition(AgentState.NEW, AgentState.RESOLVED)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (current, target)
        for current, targets in ALLOWED_TRANSITIONS.items()
        for target in targets
    ],
)
def test_every_declared_transition_is_accepted(
    current: AgentState, target: AgentState
) -> None:
    assert_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (current, target)
        for current in AgentState
        for target in AgentState
        if target not in ALLOWED_TRANSITIONS[current]
    ],
)
def test_every_undeclared_transition_is_rejected(
    current: AgentState, target: AgentState
) -> None:
    with pytest.raises(ValueError, match="Illegal state transition"):
        assert_transition(current, target)
