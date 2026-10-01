import hashlib
import json
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from opspilot.agent.budget import BudgetExceededError
from opspilot.agent.live_orchestrator import LiveOrchestrator
from opspilot.agent.orchestrator import MockOrchestrator
from opspilot.agent.parser import ModelOutputError
from opspilot.agent.policies import PolicyViolationError
from opspilot.config import get_settings
from opspilot.model_gateway.client import ModelGatewayError, OpenAICompatibleClient
from opspilot.models.audit import AgentRun, Approval, Evidence, ToolCall
from opspilot.models.incident import Incident, TraceEvent
from opspilot.observability.metrics import (
    DIAGNOSIS_DURATION,
    DIAGNOSIS_RUNS,
    MODEL_ESTIMATED_COST,
    MODEL_FALLBACKS,
)
from opspilot.tasks.dispatch import (
    DiagnosisDispatchError,
    dispatch_diagnosis,
    new_task_id,
)


async def append_trace(
    session: AsyncSession,
    incident_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> TraceEvent:
    current = await session.scalar(
        select(func.max(TraceEvent.sequence)).where(
            TraceEvent.incident_id == incident_id
        )
    )
    event = TraceEvent(
        incident_id=incident_id,
        sequence=(current or 0) + 1,
        event_type=event_type,
        payload=payload,
    )
    session.add(event)
    await session.flush()
    return event


async def run_diagnosis(
    session: AsyncSession, incident: Incident, description: str
) -> AgentRun:
    settings = get_settings()
    run = AgentRun(
        incident_id=incident.id,
        model_name=(
            "mock-model"
            if settings.model_provider == "mock"
            else settings.model_name
        ),
        model_version=(
            "phase-3"
            if settings.model_provider == "mock"
            else settings.model_version
        ),
        prompt_version="opspilot-v0.2",
    )
    events = await _diagnosis_events(run, incident.service_name, description)
    session.add(run)
    await session.flush()
    current = await session.scalar(
        select(func.max(TraceEvent.sequence)).where(
            TraceEvent.incident_id == incident.id
        )
    )
    start_sequence = current or 0
    for offset, event in enumerate(events, start=1):
        sequence = start_sequence + offset
        session.add(TraceEvent(incident_id=incident.id, sequence=sequence, **event))
        await _persist_event(session, incident, run, sequence, event)
    incident.status = _terminal_state(events)
    run.status = (
        "WAITING_APPROVAL"
        if incident.status == "WAITING_APPROVAL"
        else "COMPLETED"
    )
    run.finished_at = datetime.now(UTC)
    await session.flush()
    return run


async def start_diagnosis(
    session: AsyncSession, incident: Incident, description: str
) -> None:
    """Run inline or durably queue a diagnosis according to deployment settings."""
    if get_settings().task_mode == "inline":
        started = perf_counter()
        outcome = "failed"
        try:
            incident.status = "RUNNING"
            await session.commit()
            await run_diagnosis(session, incident, description)
            await session.commit()
            outcome = incident.status.casefold()
        except Exception as error:
            await session.rollback()
            failed_incident = await session.get(Incident, incident.id)
            if failed_incident is not None:
                failed_incident.status = "FAILED"
                await append_trace(
                    session,
                    incident.id,
                    "task_failed",
                    {"error_type": type(error).__name__},
                )
                await session.commit()
            raise
        finally:
            DIAGNOSIS_RUNS.labels("inline", outcome).inc()
            DIAGNOSIS_DURATION.labels("inline").observe(perf_counter() - started)
        return

    task_id = new_task_id()
    incident.status = "QUEUED"
    await append_trace(
        session,
        incident.id,
        "task_queued",
        {"task_id": task_id},
    )
    await session.commit()
    try:
        dispatch_diagnosis(incident.id, description, task_id)
    except DiagnosisDispatchError:
        incident.status = "FAILED"
        await append_trace(
            session,
            incident.id,
            "task_dispatch_failed",
            {"task_id": task_id},
        )
        await session.commit()
        raise


async def _diagnosis_events(
    run: AgentRun, service: str, description: str
) -> list[dict[str, Any]]:
    settings = get_settings()
    if settings.model_provider == "mock":
        return MockOrchestrator().run(service, description)

    client = OpenAICompatibleClient(
        base_url=settings.model_base_url,
        api_key=settings.model_api_key.get_secret_value(),
        model_name=settings.model_name,
        timeout_seconds=settings.model_timeout_seconds,
        max_tokens=settings.model_max_tokens,
    )
    orchestrator = LiveOrchestrator(
        client,
        max_model_turns=settings.max_model_turns,
        max_tool_calls=settings.max_tool_calls,
        max_run_seconds=settings.max_run_seconds,
    )
    try:
        result = await orchestrator.run(service, description)
    except (
        BudgetExceededError,
        ModelGatewayError,
        ModelOutputError,
        PolicyViolationError,
    ) as error:
        if not settings.model_fallback_to_mock:
            raise
        MODEL_FALLBACKS.labels(type(error).__name__).inc()
        run.model_name = "mock-fallback"
        run.model_version = "phase-3"
        return [
            {
                "event_type": "model_fallback",
                "payload": {"reason": type(error).__name__},
            },
            *MockOrchestrator().run(service, description),
        ]
    finally:
        await client.aclose()

    run.model_name = result.model_name
    run.input_tokens = result.input_tokens
    run.output_tokens = result.output_tokens
    run.latency_ms = result.latency_ms
    run.estimated_cost = estimate_model_cost(
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        input_cost_per_million=settings.model_input_cost_per_million_tokens,
        output_cost_per_million=settings.model_output_cost_per_million_tokens,
    )
    MODEL_ESTIMATED_COST.labels(result.model_name).inc(run.estimated_cost)
    return [
        *result.events,
        {
            "event_type": "model_usage",
            "payload": {
                "model": result.model_name,
                "model_version": settings.model_version,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "latency_ms": result.latency_ms,
                "estimated_cost_usd": run.estimated_cost,
            },
        },
    ]


def estimate_model_cost(
    *,
    input_tokens: int,
    output_tokens: int,
    input_cost_per_million: float,
    output_cost_per_million: float,
) -> float:
    """Estimate one run's cost from explicit per-million-token prices."""
    return (
        input_tokens * input_cost_per_million
        + output_tokens * output_cost_per_million
    ) / 1_000_000


def _terminal_state(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        if event["event_type"] == "state_transition":
            return str(event["payload"]["state"])
    return "FAILED"


async def _persist_event(
    session: AsyncSession,
    incident: Incident,
    run: AgentRun,
    sequence: int,
    event: dict[str, Any],
) -> None:
    payload = event["payload"]
    if event["event_type"] == "tool_call":
        result = payload["result"]
        tool_call = ToolCall(
            run_id=run.id,
            incident_id=incident.id,
            tool_name=payload["tool"],
            arguments_json=payload["arguments"],
            result_json=result,
            evidence_ids_json=[payload["evidence_id"]],
            risk_level="low",
            status="succeeded",
            idempotency_key=f"{run.id}:{sequence}",
        )
        session.add(tool_call)
        await session.flush()
        content = json.dumps(result, ensure_ascii=False, sort_keys=True)
        session.add(
            Evidence(
                id=payload["evidence_id"],
                incident_id=incident.id,
                tool_call_id=tool_call.id,
                source_type=payload["tool"],
                source_uri=result["source_uri"],
                content=content,
                observed_at=datetime.fromisoformat(result["observed_at"]),
                content_hash=hashlib.sha256(content.encode()).hexdigest(),
            )
        )
    elif event["event_type"] == "proposed_action":
        tool_call = ToolCall(
            run_id=run.id,
            incident_id=incident.id,
            tool_name=payload["tool"],
            arguments_json=payload["arguments"],
            evidence_ids_json=payload["evidence_ids"],
            rollback_plan=payload["rollback_plan"],
            risk_level=payload["risk"],
            status="pending_approval",
            idempotency_key=f"{run.id}:{sequence}",
        )
        session.add(tool_call)
        await session.flush()
        session.add(
            Approval(
                incident_id=incident.id,
                tool_call_id=tool_call.id,
                requested_by=incident.created_by,
                expires_at=datetime.now(UTC)
                + timedelta(seconds=get_settings().approval_ttl_seconds),
            )
        )
