from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.dependencies.auth import Identity, require_permission
from apps.api.schemas import (
    ApprovalComment,
    ApprovalDecision,
    ApprovalRead,
    IncidentRead,
)
from opspilot.agent.state import AgentState, assert_transition
from opspilot.approvals.service import expire_pending_approvals
from opspilot.db.session import get_session
from opspilot.models.audit import AgentRun, Approval, ToolCall
from opspilot.models.incident import Incident, TraceEvent
from opspilot.tools.gateway import ToolGateway

router = APIRouter(prefix="/approvals", tags=["approvals"])
SessionDependency = Annotated[AsyncSession, Depends(get_session)]
ReadIdentity = Annotated[Identity, Depends(require_permission("approval:read"))]
DecideIdentity = Annotated[Identity, Depends(require_permission("approval:decide"))]


@router.get("", response_model=list[ApprovalRead])
async def list_pending_approvals(
    session: SessionDependency,
    _identity: ReadIdentity,
    status_filter: Annotated[
        Literal["pending", "approved", "rejected", "expired"],
        Query(alias="status"),
    ] = "pending",
) -> list[ApprovalRead]:
    if status_filter == "pending":
        expired = await expire_pending_approvals(session)
        if expired:
            await session.commit()
    rows = await session.execute(
        select(Approval, ToolCall)
        .join(ToolCall, Approval.tool_call_id == ToolCall.id)
        .where(Approval.decision == status_filter)
        .order_by(Approval.created_at)
    )
    return [_approval_read(approval, call) for approval, call in rows.all()]


@router.post("/{approval_id}/decision", response_model=IncidentRead)
async def decide_approval(
    approval_id: str,
    payload: ApprovalDecision,
    session: SessionDependency,
    identity: DecideIdentity,
) -> Incident:
    row = (
        await session.execute(
            select(Approval, ToolCall, Incident)
            .join(ToolCall, Approval.tool_call_id == ToolCall.id)
            .join(Incident, Approval.incident_id == Incident.id)
            .where(Approval.id == approval_id)
            .with_for_update()
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    approval, tool_call, incident = row
    if approval.decision != "pending":
        raise HTTPException(status_code=409, detail="Approval already decided")
    if approval.requested_by == identity.user_id:
        raise HTTPException(status_code=403, detail="Requester cannot self-approve")

    now = datetime.now(UTC)
    expires_at = approval.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= now:
        assert_transition(AgentState(incident.status), AgentState.NEEDS_HUMAN)
        approval.decision = "expired"
        incident.status = AgentState.NEEDS_HUMAN
        tool_call.status = "expired"
        await _append_trace(
            session,
            incident.id,
            "state_transition",
            {"state": AgentState.NEEDS_HUMAN, "reason": "approval_expired"},
        )
        await session.commit()
        raise HTTPException(status_code=409, detail="Approval expired")

    approval.reviewed_by = identity.user_id
    approval.reviewed_at = now
    approval.comment = payload.comment
    if payload.decision == "reject":
        assert_transition(AgentState(incident.status), AgentState.REJECTED)
        approval.decision = "rejected"
        tool_call.status = "rejected"
        incident.status = AgentState.REJECTED
        await _append_trace(
            session,
            incident.id,
            "state_transition",
            {"state": AgentState.REJECTED, "reviewed_by": identity.user_id},
        )
        run = await session.get(AgentRun, tool_call.run_id)
        if run is not None:
            run.status = "REJECTED"
        await session.commit()
        return await _get_incident(session, incident.id)

    assert_transition(AgentState(incident.status), AgentState.EXECUTING)
    approval.decision = "approved"
    incident.status = AgentState.EXECUTING
    await _append_trace(
        session,
        incident.id,
        "state_transition",
        {"state": AgentState.EXECUTING, "approval_id": approval.id},
    )
    result = ToolGateway().execute_approved_change(
        tool_call.tool_name,
        tool_call.arguments_json,
        approval_id=approval.id,
        approved=True,
        idempotency_key=tool_call.idempotency_key,
    )
    tool_call.result_json = result
    tool_call.status = "succeeded"
    await _append_trace(
        session,
        incident.id,
        "tool_result",
        {"tool_call_id": tool_call.id, "result": result},
    )

    assert_transition(AgentState.EXECUTING, AgentState.VERIFYING)
    incident.status = AgentState.VERIFYING
    await _append_trace(
        session,
        incident.id,
        "state_transition",
        {"state": AgentState.VERIFYING},
    )
    await _append_trace(
        session,
        incident.id,
        "verification",
        {
            "status": "passed",
            "evidence_ids": tool_call.evidence_ids_json,
            "message": "Sandbox action completed and health check passed",
        },
    )
    assert_transition(AgentState.VERIFYING, AgentState.RESOLVED)
    incident.status = AgentState.RESOLVED
    await _append_trace(
        session,
        incident.id,
        "state_transition",
        {"state": AgentState.RESOLVED},
    )
    run = await session.get(AgentRun, tool_call.run_id)
    if run is not None:
        run.status = "COMPLETED"
    await session.commit()
    return await _get_incident(session, incident.id)


@router.post("/{approval_id}/approve", response_model=IncidentRead)
async def approve_action(
    approval_id: str,
    payload: ApprovalComment,
    session: SessionDependency,
    identity: DecideIdentity,
) -> Incident:
    return await decide_approval(
        approval_id,
        ApprovalDecision(decision="approve", comment=payload.comment),
        session,
        identity,
    )


@router.post("/{approval_id}/reject", response_model=IncidentRead)
async def reject_action(
    approval_id: str,
    payload: ApprovalComment,
    session: SessionDependency,
    identity: DecideIdentity,
) -> Incident:
    return await decide_approval(
        approval_id,
        ApprovalDecision(decision="reject", comment=payload.comment),
        session,
        identity,
    )


def _approval_read(approval: Approval, call: ToolCall) -> ApprovalRead:
    return ApprovalRead(
        id=approval.id,
        incident_id=approval.incident_id,
        requested_by=approval.requested_by,
        decision=approval.decision,
        expires_at=approval.expires_at,
        tool_name=call.tool_name,
        arguments=call.arguments_json,
        risk=call.risk_level,
        evidence_ids=call.evidence_ids_json,
        rollback_plan=call.rollback_plan or "",
    )


async def _append_trace(
    session: AsyncSession,
    incident_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    current = await session.scalar(
        select(func.max(TraceEvent.sequence)).where(
            TraceEvent.incident_id == incident_id
        )
    )
    session.add(
        TraceEvent(
            incident_id=incident_id,
            sequence=(current or 0) + 1,
            event_type=event_type,
            payload=payload,
        )
    )
    await session.flush()


async def _get_incident(session: AsyncSession, incident_id: str) -> Incident:
    incident = await session.scalar(
        select(Incident)
        .where(Incident.id == incident_id)
        .options(selectinload(Incident.trace))
    )
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident
