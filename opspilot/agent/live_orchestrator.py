import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from opspilot.agent.budget import ExecutionBudget
from opspilot.agent.parser import ModelOutputError, parse_model_decision
from opspilot.agent.policies import SafetyGuard
from opspilot.agent.prompt import MODEL_CONTRACT, READ_TOOLS, SYSTEM_POLICY
from opspilot.agent.schemas import (
    FinalAnswerDecision,
    ModelDecision,
    ProposedActionDecision,
    ToolCallDecision,
)
from opspilot.agent.state import AgentState, assert_transition
from opspilot.model_gateway.client import DecisionClient
from opspilot.model_gateway.schemas import ChatMessage, ModelResponse
from opspilot.tools.gateway import ToolGateway
from opspilot.tools.scenarios import ScenarioAction


@dataclass(frozen=True, slots=True)
class OrchestrationResult:
    events: list[dict[str, Any]]
    model_name: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


class LiveOrchestrator:
    """Run the evidence loop with strict decisions from a remote model."""

    def __init__(
        self,
        client: DecisionClient,
        gateway: ToolGateway | None = None,
        *,
        max_model_turns: int = 8,
        max_tool_calls: int = 12,
        max_run_seconds: int = 180,
    ) -> None:
        self.client = client
        self.gateway = gateway or ToolGateway()
        self._owns_gateway = gateway is None
        self._budget_limits = (max_model_turns, max_tool_calls, max_run_seconds)

    async def run(self, service: str, description: str) -> OrchestrationResult:
        responses: list[ModelResponse] = []
        try:
            events = await self._run(service, description, responses)
        finally:
            if self._owns_gateway:
                self.gateway.close()
        return OrchestrationResult(
            events=events,
            model_name=responses[-1].model if responses else self.client.model_name,
            input_tokens=sum(item.usage.input_tokens for item in responses),
            output_tokens=sum(item.usage.output_tokens for item in responses),
            latency_ms=sum(item.latency_ms for item in responses),
        )

    async def _run(
        self,
        service: str,
        description: str,
        responses: list[ModelResponse],
    ) -> list[dict[str, Any]]:
        now = datetime.now(UTC)
        start, end = now - timedelta(minutes=15), now
        events: list[dict[str, Any]] = []
        state = AgentState.NEW
        budget = ExecutionBudget(
            max_model_turns=self._budget_limits[0],
            max_tool_calls=self._budget_limits[1],
            max_run_seconds=self._budget_limits[2],
        )
        guard = SafetyGuard()
        scenario_id = self.gateway.select_scenario(service, description)
        search_terms = _search_terms(description)

        def transition(target: AgentState) -> None:
            nonlocal state
            assert_transition(state, target)
            state = target
            events.append({"event_type": "state_transition", "payload": {"state": state}})

        transition(AgentState.TRIAGE)
        transition(AgentState.COLLECTING_EVIDENCE)
        evidence_ids: list[str] = []
        for step in range(len(READ_TOOLS)):
            required_tool = READ_TOOLS[step]
            context = {
                "incident": description,
                "service": service,
                "state": "COLLECTING_EVIDENCE",
                "next_evidence_step": step + 1,
                "required_tool": required_tool,
                "observation_start": start.isoformat().replace("+00:00", "Z"),
                "observation_end": end.isoformat().replace("+00:00", "Z"),
                "search_terms": search_terms,
                "query_defaults": {
                    "metric": "health",
                    "log_level": None,
                    "log_limit": 50,
                    "top_k": 3,
                },
            }
            decision = await self._request_decision(
                context,
                budget,
                responses,
                required_tool=required_tool,
            )
            if not isinstance(decision, ToolCallDecision):
                raise ModelOutputError("Evidence collection requires a tool_call decision")
            execution_arguments = {**decision.arguments, "scenario_id": scenario_id}
            budget.consume_tool_call()
            result = self.gateway.execute(decision.tool, execution_arguments)
            result.pop("arguments", None)
            evidence_id = str(uuid.uuid4())
            evidence_ids.append(evidence_id)
            events.append(
                {
                    "event_type": "tool_call",
                    "payload": {
                        "tool": decision.tool,
                        "arguments": decision.arguments,
                        "evidence_id": evidence_id,
                        "result": result,
                    },
                }
            )

        transition(AgentState.DIAGNOSING)
        terminal_context = _terminal_context(
            description=description,
            evidence_ids=evidence_ids,
            root_cause=self.gateway.root_cause_for(service, scenario_id),
            recommended_steps=self.gateway.recommended_steps_for(service, scenario_id),
            action=self.gateway.action_for(service, scenario_id),
        )
        terminal = await self._request_decision(terminal_context, budget, responses)
        if isinstance(terminal, ProposedActionDecision):
            guard.validate_action(terminal, set(evidence_ids))
            transition(AgentState.PROPOSING_ACTION)
            events.append(
                {"event_type": "proposed_action", "payload": terminal.model_dump()}
            )
            transition(AgentState.WAITING_APPROVAL)
            return events
        if isinstance(terminal, FinalAnswerDecision):
            guard.validate_final_answer(terminal, set(evidence_ids))
            events.append(
                {"event_type": "final_answer", "payload": terminal.model_dump()}
            )
            transition(AgentState.RESOLVED)
            return events
        raise ModelOutputError("Diagnosis requires a terminal model decision")

    async def _request_decision(
        self,
        context: dict[str, Any],
        budget: ExecutionBudget,
        responses: list[ModelResponse],
        *,
        required_tool: str | None = None,
    ) -> ModelDecision:
        messages = [
            ChatMessage(role="system", content=SYSTEM_POLICY),
            ChatMessage(
                role="user",
                content=json.dumps(context, ensure_ascii=False, sort_keys=True),
            ),
        ]
        budget.consume_model_turn()
        response = await self.client.complete(messages)
        responses.append(response)
        try:
            return _parse_required_decision(response.content, required_tool)
        except ModelOutputError as first_error:
            repair_messages = [
                *messages,
                ChatMessage(role="assistant", content=response.content),
                ChatMessage(
                    role="user",
                    content=_repair_instruction(first_error, required_tool),
                ),
            ]
            budget.consume_model_turn()
            repaired = await self.client.complete(repair_messages)
            responses.append(repaired)
            try:
                return _parse_required_decision(repaired.content, required_tool)
            except ModelOutputError as repaired_error:
                raise ModelOutputError(
                    "Model output is invalid after one repair attempt"
                ) from repaired_error


def _search_terms(description: str) -> list[str]:
    terms = re.findall(r"[\w.-]+", description.casefold(), flags=re.UNICODE)
    return terms[:5] or ["incident"]


def _parse_required_decision(
    content: str, required_tool: str | None
) -> ModelDecision:
    decision = parse_model_decision(content)
    if required_tool is None:
        return decision
    if not isinstance(decision, ToolCallDecision):
        raise ModelOutputError(
            f"Evidence collection requires a {required_tool} tool_call decision"
        )
    if decision.tool != required_tool:
        raise ModelOutputError(
            f"Evidence step requires tool {required_tool}, got {decision.tool}"
        )
    return decision


def _repair_instruction(
    error: ModelOutputError, required_tool: str | None
) -> str:
    if required_tool is None:
        return (
            "Return exactly one corrected JSON decision with no markdown or extra "
            f"text. The previous output failed validation: {error}"
        )
    tool_schemas = cast(dict[str, dict[str, str]], MODEL_CONTRACT["tools"])
    argument_schema = tool_schemas[required_tool]
    return (
        "Return exactly one corrected JSON decision with no markdown or extra text. "
        'The decision type must be "tool_call". '
        f'The tool must be exactly "{required_tool}". '
        "Do not return proposed_action or final_answer. "
        "Include a non-empty reason. "
        "Copy argument values exactly from the original user context and use this "
        "arguments schema: "
        f"{json.dumps(argument_schema, ensure_ascii=False, sort_keys=True)}. "
        f"The previous output failed validation: {error}"
    )


def _terminal_context(
    *,
    description: str,
    evidence_ids: list[str],
    root_cause: str,
    recommended_steps: list[str],
    action: ScenarioAction | None,
) -> dict[str, Any]:
    candidate_action: dict[str, Any] | None = None
    if action is not None:
        candidate_action = {
            "tool": action.tool,
            "arguments": action.arguments,
            "risk": action.risk,
            "rollback_plan": action.rollback_plan,
        }
    return {
        "incident": description,
        "state": "DIAGNOSING",
        "evidence_ids": evidence_ids,
        "root_cause_candidate": root_cause,
        "recommended_steps": recommended_steps,
        "candidate_action": candidate_action,
        "recommended_confidence": 0.86,
        "insufficient_information": False,
    }
