import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.dependencies.auth import Identity, require_permission
from apps.api.schemas import IncidentCreate, IncidentMessageCreate, IncidentRead
from opspilot.db.session import SessionFactory, get_session
from opspilot.incidents.service import append_trace, start_diagnosis
from opspilot.models.audit import AgentRun, Approval, Evidence, ToolCall
from opspilot.models.incident import Incident, TraceEvent
from opspilot.security.rbac import Role
from opspilot.tasks import DiagnosisDispatchError

router = APIRouter(prefix="/incidents", tags=["incidents"])
SessionDependency = Annotated[AsyncSession, Depends(get_session)]
CreateIdentity = Annotated[Identity, Depends(require_permission("incident:create"))]
ReadIdentity = Annotated[Identity, Depends(require_permission("incident:read"))]


@router.post("", response_model=IncidentRead, status_code=status.HTTP_201_CREATED)
async def create_incident(
    payload: IncidentCreate, session: SessionDependency, identity: CreateIdentity
) -> Incident:
    incident = Incident(
        **payload.model_dump(), status="NEW", created_by=identity.user_id
    )
    session.add(incident)
    await session.flush()

    try:
        await start_diagnosis(session, incident, payload.description)
    except DiagnosisDispatchError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return await _get_incident(session, incident.id)


@router.get("", response_model=list[IncidentRead])
async def list_incidents(
    session: SessionDependency, identity: ReadIdentity
) -> list[Incident]:
    statement = select(Incident).options(selectinload(Incident.trace))
    if identity.role == Role.OPERATOR:
        statement = statement.where(Incident.created_by == identity.user_id)
    result = await session.scalars(statement.order_by(Incident.created_at.desc()))
    return list(result.unique())


@router.get("/{incident_id}", response_model=IncidentRead)
async def get_incident(
    incident_id: str, session: SessionDependency, identity: ReadIdentity
) -> Incident:
    incident = await _get_incident(session, incident_id)
    _assert_incident_access(identity, incident)
    return incident


@router.get("/{incident_id}/audit")
async def export_incident_audit(
    incident_id: str, session: SessionDependency, identity: ReadIdentity
) -> JSONResponse:
    incident = await _get_incident(session, incident_id)
    _assert_incident_access(identity, incident)
    runs = list(await session.scalars(
        select(AgentRun).where(AgentRun.incident_id == incident_id)
        .order_by(AgentRun.started_at, AgentRun.id)
    ))
    calls = list(await session.scalars(
        select(ToolCall).where(ToolCall.incident_id == incident_id)
        .order_by(ToolCall.created_at, ToolCall.id)
    ))
    evidence = list(await session.scalars(
        select(Evidence).where(Evidence.incident_id == incident_id)
        .order_by(Evidence.observed_at, Evidence.id)
    ))
    approvals = list(await session.scalars(
        select(Approval).where(Approval.incident_id == incident_id)
        .order_by(Approval.created_at, Approval.id)
    ))
    report = {
        "schema_version": 1,
        "exported_at": datetime.now(UTC),
        "incident": {
            "id": incident.id,
            "title": incident.title,
            "description": incident.description,
            "source": incident.source,
            "severity": incident.severity,
            "service_name": incident.service_name,
            "status": incident.status,
            "created_by": incident.created_by,
            "external_key": incident.external_key,
            "created_at": incident.created_at,
            "updated_at": incident.updated_at,
        },
        "trace": [
            {
                "id": item.id,
                "sequence": item.sequence,
                "event_type": item.event_type,
                "payload": item.payload,
                "created_at": item.created_at,
            }
            for item in incident.trace
        ],
        "agent_runs": [
            {
                "id": run.id,
                "model_name": run.model_name,
                "model_version": run.model_version,
                "prompt_version": run.prompt_version,
                "status": run.status,
                "input_tokens": run.input_tokens,
                "output_tokens": run.output_tokens,
                "latency_ms": run.latency_ms,
                "estimated_cost": run.estimated_cost,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
            }
            for run in runs
        ],
        "tool_calls": [
            {
                "id": call.id,
                "run_id": call.run_id,
                "tool_name": call.tool_name,
                "arguments": call.arguments_json,
                "result": call.result_json,
                "evidence_ids": call.evidence_ids_json,
                "risk_level": call.risk_level,
                "status": call.status,
                "rollback_plan": call.rollback_plan,
                "idempotency_key": call.idempotency_key,
                "created_at": call.created_at,
            }
            for call in calls
        ],
        "evidence": [
            {
                "id": item.id,
                "tool_call_id": item.tool_call_id,
                "source_type": item.source_type,
                "source_uri": item.source_uri,
                "content": item.content,
                "observed_at": item.observed_at,
                "content_hash": item.content_hash,
            }
            for item in evidence
        ],
        "approvals": [
            {
                "id": item.id,
                "tool_call_id": item.tool_call_id,
                "requested_by": item.requested_by,
                "reviewed_by": item.reviewed_by,
                "decision": item.decision,
                "comment": item.comment,
                "expires_at": item.expires_at,
                "reviewed_at": item.reviewed_at,
            }
            for item in approvals
        ],
    }
    return JSONResponse(
        content=jsonable_encoder(report),
        headers={
            "Content-Disposition": (
                f'attachment; filename="opspilot-incident-{incident.id}-audit.json"'
            )
        },
    )


@router.post("/{incident_id}/messages", response_model=IncidentRead)
async def add_incident_message(
    incident_id: str,
    payload: IncidentMessageCreate,
    session: SessionDependency,
    identity: CreateIdentity,
) -> Incident:
    incident = await _get_incident(session, incident_id)
    _assert_incident_access(identity, incident)
    if incident.status in {"QUEUED", "RUNNING", "WAITING_APPROVAL", "EXECUTING", "VERIFYING"}:
        raise HTTPException(
            status_code=409,
            detail="Cannot start a new diagnosis while an action is active",
        )
    await append_trace(
        session,
        incident.id,
        "user_message",
        {"content": payload.content, "created_by": identity.user_id},
    )
    try:
        await start_diagnosis(session, incident, payload.content)
    except DiagnosisDispatchError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return await _get_incident(session, incident.id)


@router.get("/{incident_id}/events")
async def stream_incident_events(
    incident_id: str,
    request: Request,
    session: SessionDependency,
    identity: ReadIdentity,
    after: int = Query(default=0, ge=0),
    last_event_id: Annotated[int | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    incident = await session.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    _assert_incident_access(identity, incident)

    async def event_stream() -> AsyncIterator[str]:
        cursor = max(after, last_event_id or 0)
        terminal_states = {
            "DIAGNOSED", "SIMULATION_COMPLETE", "RESOLVED", "FAILED", "REJECTED", "NEEDS_HUMAN"
        }
        while not await request.is_disconnected():
            async with SessionFactory() as stream_session:
                events = list(
                    await stream_session.scalars(
                        select(TraceEvent)
                        .where(
                            TraceEvent.incident_id == incident_id,
                            TraceEvent.sequence > cursor,
                        )
                        .order_by(TraceEvent.sequence)
                    )
                )
                for event in events:
                    cursor = event.sequence
                    data = json.dumps(
                        {
                            "id": event.id,
                            "sequence": event.sequence,
                            "event_type": event.event_type,
                            "payload": event.payload,
                            "created_at": event.created_at.isoformat(),
                        },
                        ensure_ascii=False,
                    )
                    yield f"id: {event.sequence}\nevent: {event.event_type}\ndata: {data}\n\n"
                incident_status = await stream_session.scalar(
                    select(Incident.status).where(Incident.id == incident_id)
                )
            if incident_status in terminal_states:
                break
            if not events:
                yield ": heartbeat\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _get_incident(session: AsyncSession, incident_id: str) -> Incident:
    result = await session.scalar(
        select(Incident)
        .where(Incident.id == incident_id)
        .options(selectinload(Incident.trace))
        .execution_options(populate_existing=True)
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return result


def _assert_incident_access(identity: Identity, incident: Incident) -> None:
    if identity.role == Role.OPERATOR and incident.created_by != identity.user_id:
        raise HTTPException(status_code=404, detail="Incident not found")
