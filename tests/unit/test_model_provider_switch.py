from typing import Any

import pytest

from opspilot.agent.live_orchestrator import OrchestrationResult
from opspilot.config import Settings
from opspilot.incidents import service as incident_service
from opspilot.model_gateway.client import ModelGatewayTimeoutError
from opspilot.models.audit import AgentRun


class FailingModelClient:
    model_name = "unavailable-model"

    def __init__(self, **_: Any) -> None:
        pass

    async def complete(self, *_: Any) -> Any:
        raise ModelGatewayTimeoutError("timeout")

    async def aclose(self) -> None:
        pass


class SuccessfulModelClient(FailingModelClient):
    pass


class SuccessfulOrchestrator:
    def __init__(self, *_: Any, **__: Any) -> None:
        pass

    async def run(self, *_: Any) -> OrchestrationResult:
        return OrchestrationResult(
            events=[
                {"event_type": "state_transition", "payload": {"state": "RESOLVED"}}
            ],
            model_name="served-model",
            input_tokens=1_250,
            output_tokens=250,
            latency_ms=321,
        )


@pytest.mark.asyncio
async def test_live_provider_failure_falls_back_to_audited_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        model_provider="openai_compatible",
        model_base_url="http://model.test/v1",
        model_api_key="secret",
        model_name="live-model",
        model_fallback_to_mock=True,
    )
    monkeypatch.setattr(incident_service, "get_settings", lambda: settings)
    monkeypatch.setattr(
        incident_service, "OpenAICompatibleClient", FailingModelClient
    )
    run = AgentRun(incident_id="incident-id")

    events = await incident_service._diagnosis_events(
        run, "payment", "payment redis timeout is increasing"
    )

    assert events[0] == {
        "event_type": "model_fallback",
        "payload": {"reason": "ModelGatewayTimeoutError"},
    }
    assert len([event for event in events if event["event_type"] == "tool_call"]) == 5
    assert run.model_name == "mock-fallback"
    assert run.model_version == "phase-3"


@pytest.mark.asyncio
async def test_live_provider_persists_auditable_usage_and_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        model_provider="openai_compatible",
        model_name="requested-model",
        model_version="adapter-v1",
        model_input_cost_per_million_tokens=2.0,
        model_output_cost_per_million_tokens=8.0,
    )
    monkeypatch.setattr(incident_service, "get_settings", lambda: settings)
    monkeypatch.setattr(
        incident_service, "OpenAICompatibleClient", SuccessfulModelClient
    )
    monkeypatch.setattr(incident_service, "LiveOrchestrator", SuccessfulOrchestrator)
    run = AgentRun(incident_id="incident-id")

    events = await incident_service._diagnosis_events(
        run, "inventory", "inventory false alarm is healthy"
    )

    assert run.model_name == "served-model"
    assert run.input_tokens == 1_250
    assert run.output_tokens == 250
    assert run.latency_ms == 321
    assert run.estimated_cost == pytest.approx(0.0045)
    assert events[-1] == {
        "event_type": "model_usage",
        "payload": {
            "model": "served-model",
            "model_version": "adapter-v1",
            "input_tokens": 1_250,
            "output_tokens": 250,
            "latency_ms": 321,
            "estimated_cost_usd": pytest.approx(0.0045),
        },
    }
