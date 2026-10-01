import json
from collections.abc import Sequence
from typing import Any

import pytest

from opspilot.agent.live_orchestrator import LiveOrchestrator
from opspilot.model_gateway.schemas import ChatMessage, ModelResponse, ModelUsage


class ContractFollowingClient:
    model_name = "fixture-model"

    async def complete(self, messages: Sequence[ChatMessage]) -> ModelResponse:
        context: dict[str, Any] = json.loads(messages[1].content)
        step = context.get("next_evidence_step")
        decision: dict[str, Any]
        if step == 1:
            decision = {
                "type": "tool_call",
                "tool": "query_metrics",
                "arguments": {
                    "service": context["service"],
                    "metric": context["query_defaults"]["metric"],
                    "start": context["observation_start"],
                    "end": context["observation_end"],
                },
                "reason": "Collect metrics evidence before diagnosis",
            }
        elif step == 2:
            decision = {
                "type": "tool_call",
                "tool": "query_logs",
                "arguments": {
                    "service": context["service"],
                    "keywords": context["search_terms"],
                    "start": context["observation_start"],
                    "end": context["observation_end"],
                    "limit": context["query_defaults"]["log_limit"],
                },
                "reason": "Collect log evidence before diagnosis",
            }
        elif step == 3:
            decision = {
                "type": "tool_call",
                "tool": "get_service_info",
                "arguments": {"service": context["service"]},
                "reason": "Collect service evidence before diagnosis",
            }
        elif step in {4, 5}:
            decision = {
                "type": "tool_call",
                "tool": "search_runbook" if step == 4 else "search_incidents",
                "arguments": {
                    "service": context["service"],
                    "query": context["incident"],
                    "top_k": context["query_defaults"]["top_k"],
                },
                "reason": "Collect knowledge evidence before diagnosis",
            }
        else:
            decision = {
                "type": "final_answer",
                "summary": "Evidence supports the incident diagnosis",
                "root_causes": [context["root_cause_candidate"]],
                "confidence": context["recommended_confidence"],
                "evidence_ids": context["evidence_ids"],
                "next_steps": context["recommended_steps"],
                "insufficient_information": False,
            }
        return ModelResponse(
            content=json.dumps(decision),
            model=self.model_name,
            usage=ModelUsage(input_tokens=10, output_tokens=5),
            latency_ms=3,
        )


class RepairingClient(ContractFollowingClient):
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, messages: Sequence[ChatMessage]) -> ModelResponse:
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                content="not valid json",
                model=self.model_name,
                usage=ModelUsage(input_tokens=2, output_tokens=1),
                latency_ms=1,
            )
        return await super().complete(messages)


class WrongToolRepairingClient(ContractFollowingClient):
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, messages: Sequence[ChatMessage]) -> ModelResponse:
        self.calls += 1
        context: dict[str, Any] = json.loads(messages[1].content)
        if context.get("next_evidence_step") == 3 and len(messages) == 2:
            return ModelResponse(
                content=json.dumps(
                    {
                        "type": "tool_call",
                        "tool": "query_metrics",
                        "arguments": {
                            "service": context["service"],
                            "metric": context["query_defaults"]["metric"],
                            "start": context["observation_start"],
                            "end": context["observation_end"],
                        },
                        "reason": "Repeated the previous evidence tool",
                    }
                ),
                model=self.model_name,
                usage=ModelUsage(input_tokens=2, output_tokens=1),
                latency_ms=1,
            )
        return await super().complete(messages)


class RepairPromptInspectingClient(WrongToolRepairingClient):
    def __init__(self) -> None:
        super().__init__()
        self.repair_prompt = ""

    async def complete(self, messages: Sequence[ChatMessage]) -> ModelResponse:
        if len(messages) == 4:
            self.repair_prompt = messages[-1].content
        return await super().complete(messages)


@pytest.mark.asyncio
async def test_live_orchestrator_runs_strict_evidence_loop() -> None:
    result = await LiveOrchestrator(ContractFollowingClient()).run(
        "payment", "payment redis timeout is increasing"
    )

    tool_events = [
        event for event in result.events if event["event_type"] == "tool_call"
    ]
    final = next(
        event for event in result.events if event["event_type"] == "final_answer"
    )
    assert len(tool_events) == 5
    assert all("scenario_id" not in event["payload"]["arguments"] for event in tool_events)
    assert len(final["payload"]["evidence_ids"]) == 5
    assert result.events[-1]["payload"]["state"] == "DIAGNOSED"
    assert result.input_tokens == 60
    assert result.output_tokens == 30
    assert result.latency_ms == 18


@pytest.mark.asyncio
async def test_live_orchestrator_repairs_invalid_output_only_once() -> None:
    client = RepairingClient()

    result = await LiveOrchestrator(client).run(
        "payment", "payment redis timeout is increasing"
    )

    assert client.calls == 7
    assert result.events[-1]["payload"]["state"] == "DIAGNOSED"
    assert result.input_tokens == 62
    assert result.output_tokens == 31


@pytest.mark.asyncio
async def test_live_orchestrator_repairs_wrong_evidence_tool() -> None:
    client = RepairPromptInspectingClient()

    result = await LiveOrchestrator(client).run(
        "payment", "payment redis timeout is increasing"
    )

    tools = [
        event["payload"]["tool"]
        for event in result.events
        if event["event_type"] == "tool_call"
    ]
    assert tools == [
        "query_metrics",
        "query_logs",
        "get_service_info",
        "search_runbook",
        "search_incidents",
    ]
    assert client.calls == 7
    assert 'decision type must be "tool_call"' in client.repair_prompt
    assert 'tool must be exactly "get_service_info"' in client.repair_prompt
    assert "Do not return proposed_action or final_answer" in client.repair_prompt
    assert '"service": "string"' in client.repair_prompt
