from enum import StrEnum


class AgentState(StrEnum):
    NEW = "NEW"
    TRIAGE = "TRIAGE"
    COLLECTING_EVIDENCE = "COLLECTING_EVIDENCE"
    DIAGNOSING = "DIAGNOSING"
    PROPOSING_ACTION = "PROPOSING_ACTION"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    DIAGNOSED = "DIAGNOSED"
    SIMULATION_COMPLETE = "SIMULATION_COMPLETE"
    RESOLVED = "RESOLVED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    NEEDS_HUMAN = "NEEDS_HUMAN"


ALLOWED_TRANSITIONS: dict[AgentState, set[AgentState]] = {
    AgentState.NEW: {AgentState.TRIAGE},
    AgentState.TRIAGE: {AgentState.COLLECTING_EVIDENCE, AgentState.NEEDS_HUMAN},
    AgentState.COLLECTING_EVIDENCE: {AgentState.DIAGNOSING, AgentState.NEEDS_HUMAN},
    AgentState.DIAGNOSING: {
        AgentState.PROPOSING_ACTION,
        AgentState.DIAGNOSED,
        AgentState.NEEDS_HUMAN,
    },
    AgentState.PROPOSING_ACTION: {
        AgentState.WAITING_APPROVAL,
        AgentState.NEEDS_HUMAN,
    },
    AgentState.WAITING_APPROVAL: {
        AgentState.EXECUTING,
        AgentState.REJECTED,
        AgentState.NEEDS_HUMAN,
    },
    AgentState.EXECUTING: {
        AgentState.VERIFYING,
        AgentState.FAILED,
    },
    AgentState.VERIFYING: {
        AgentState.RESOLVED,
        AgentState.SIMULATION_COMPLETE,
        AgentState.FAILED,
        AgentState.NEEDS_HUMAN,
    },
    AgentState.DIAGNOSED: set(),
    AgentState.SIMULATION_COMPLETE: set(),
    AgentState.RESOLVED: set(),
    AgentState.FAILED: set(),
    AgentState.REJECTED: set(),
    AgentState.NEEDS_HUMAN: set(),
}


def assert_transition(current: AgentState, target: AgentState) -> None:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"Illegal state transition: {current} -> {target}")
