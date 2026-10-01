import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from opspilot.agent.budget import ExecutionBudget
from opspilot.agent.policies import SafetyGuard
from opspilot.agent.schemas import (
    FinalAnswerDecision,
    ProposedActionDecision,
    ToolCallDecision,
)
from opspilot.agent.state import AgentState, assert_transition
from opspilot.tools.gateway import ToolGateway
from opspilot.tools.scenarios import ScenarioAction


class MockOrchestrator:
    """Deterministic Phase 0 model that exposes every state and tool decision."""

    def __init__(self, gateway: ToolGateway | None = None) -> None:
        self.gateway = gateway or ToolGateway()
        self._owns_gateway = gateway is None

    def run(self, service: str, description: str) -> list[dict[str, Any]]:
        try:
            return self._run(service, description)
        finally:
            if self._owns_gateway:
                self.gateway.close()

    def _run(self, service: str, description: str) -> list[dict[str, Any]]:
        now = datetime.now(UTC)
        start, end = now - timedelta(minutes=15), now
        events: list[dict[str, Any]] = []
        state = AgentState.NEW
        budget = ExecutionBudget()
        guard = SafetyGuard()
        scenario_id = self.gateway.select_scenario(service, description)

        def transition(target: AgentState) -> None:
            nonlocal state
            assert_transition(state, target)
            state = target
            events.append({"event_type": "state_transition", "payload": {"state": state}})

        transition(AgentState.TRIAGE)
        transition(AgentState.COLLECTING_EVIDENCE)
        calls: list[tuple[str, dict[str, Any]]] = [
            (
                "query_metrics",
                {
                    "service": service,
                    "scenario_id": scenario_id,
                    "metric": "health",
                    "start": start,
                    "end": end,
                },
            ),
            (
                "query_logs",
                {
                    "service": service,
                    "scenario_id": scenario_id,
                    "keywords": description.split()[:5],
                    "start": start,
                    "end": end,
                    "limit": 50,
                },
            ),
            ("get_service_info", {"service": service, "scenario_id": scenario_id}),
            (
                "search_runbook",
                {
                    "service": service,
                    "scenario_id": scenario_id,
                    "query": description,
                    "top_k": 3,
                },
            ),
            (
                "search_incidents",
                {
                    "service": service,
                    "scenario_id": scenario_id,
                    "query": description,
                    "top_k": 3,
                },
            ),
        ]
        evidence_ids: list[str] = []
        for tool, arguments in calls:
            budget.consume_model_turn()
            decision = ToolCallDecision(
                tool=tool,
                arguments=arguments,
                reason=f"收集 {service} 的诊断证据",
            )
            budget.consume_tool_call()
            result = self.gateway.execute(decision.tool, decision.arguments)
            evidence_id = str(uuid.uuid4())
            evidence_ids.append(evidence_id)
            events.append(
                {
                    "event_type": "tool_call",
                    "payload": {
                        "tool": decision.tool,
                        "arguments": result.pop("arguments"),
                        "evidence_id": evidence_id,
                        "result": result,
                    },
                }
            )
        transition(AgentState.DIAGNOSING)
        budget.consume_model_turn()
        action = self._proposed_action(
            self.gateway.action_for(service, scenario_id), evidence_ids
        )
        if action is not None:
            guard.validate_action(action, set(evidence_ids))
            transition(AgentState.PROPOSING_ACTION)
            events.append(
                {"event_type": "proposed_action", "payload": action.model_dump()}
            )
            transition(AgentState.WAITING_APPROVAL)
            return events

        answer = FinalAnswerDecision(
            summary=f"已完成 {service} 的 Mock 诊断",
            root_causes=[self.gateway.root_cause_for(service, scenario_id)],
            confidence=0.86,
            evidence_ids=evidence_ids,
            next_steps=self.gateway.recommended_steps_for(service, scenario_id),
        )
        guard.validate_final_answer(answer, set(evidence_ids))
        events.append(
            {
                "event_type": "final_answer",
                "payload": answer.model_dump(),
            }
        )
        transition(AgentState.RESOLVED)
        return events

    @staticmethod
    def _proposed_action(
        scenario_action: ScenarioAction | None, evidence_ids: list[str]
    ) -> ProposedActionDecision | None:
        if scenario_action is None:
            return None
        return ProposedActionDecision(
            tool=scenario_action.tool,
            arguments=scenario_action.arguments,
            risk=scenario_action.risk,
            evidence_ids=evidence_ids,
            rollback_plan=scenario_action.rollback_plan,
        )
