import hashlib
import json
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
from opspilot.models.audit import AgentRun, Approval, Evidence, ToolCall
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
        Literal["pending", "approved", "rejected", "expired", "invalidated"],
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

    evidence_version = await _frozen_scenario_version(
        session, incident.id, tool_call.evidence_ids_json
    )
    gateway = ToolGateway()
    if (
        evidence_version is None
        or gateway.scenario_for_version(incident.service_name, evidence_version) is None
    ):
        gateway.close()
        assert_transition(AgentState(incident.status), AgentState.NEEDS_HUMAN)
        approval.decision = "invalidated"
        tool_call.status = "invalidated"
        incident.status = AgentState.NEEDS_HUMAN
        await _append_trace(
            session,
            incident.id,
            "approval_invalidated",
            {"reason": "simulated_evidence_version_unavailable", "approval_id": approval.id},
        )
        await _append_trace(
            session,
            incident.id,
            "state_transition",
            {"state": AgentState.NEEDS_HUMAN},
        )
        run = await session.get(AgentRun, tool_call.run_id)
        if run is not None:
            run.status = "NEEDS_HUMAN"
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
    result: dict[str, Any] | None = None
    phase = "sandbox_execution"
    try:
        result = gateway.execute_approved_change(
            tool_call.tool_name,
            tool_call.arguments_json,
            approval_id=approval.id,
            approved=True,
            idempotency_key=tool_call.idempotency_key,
        )
        phase = "sandbox_verification"
        verification = gateway.verify_simulated_change(
            incident.service_name,
            evidence_version,
            tool_call.tool_name,
            tool_call.arguments_json,
            result,
        )
    except Exception as exc:
        if result is not None:
            tool_call.result_json = result
            tool_call.status = "succeeded"
            await _append_trace(
                session,
                incident.id,
                "tool_result",
                {"tool_call_id": tool_call.id, "result": result},
            )
        else:
            tool_call.status = "failed"
        assert_transition(AgentState.EXECUTING, AgentState.FAILED)
        incident.status = AgentState.FAILED
        await _append_trace(
            session,
            incident.id,
            "simulation_error",
            {
                "tool_call_id": tool_call.id,
                "phase": phase,
                "error_type": type(exc).__name__,
                "message": "Local simulation failed; no real service action was attempted",
            },
        )
        await _append_trace(
            session,
            incident.id,
            "state_transition",
            {"state": AgentState.FAILED, "reason": "simulation_error"},
        )
        run = await session.get(AgentRun, tool_call.run_id)
        if run is not None:
            run.status = "FAILED"
        await session.commit()
        return await _get_incident(session, incident.id)
    finally:
        gateway.close()
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
        {**verification, "evidence_ids": tool_call.evidence_ids_json},
    )
    target_state = {
        "passed": AgentState.SIMULATION_COMPLETE,
        "failed": AgentState.FAILED,
        "inconclusive": AgentState.NEEDS_HUMAN,
    }[verification["status"]]
    assert_transition(AgentState.VERIFYING, target_state)
    incident.status = target_state
    await _append_trace(
        session,
        incident.id,
        "state_transition",
        {"state": target_state},
    )
    run = await session.get(AgentRun, tool_call.run_id)
    if run is not None:
        run.status = "COMPLETED" if target_state == AgentState.SIMULATION_COMPLETE else target_state
    await session.commit()
    return await _get_incident(session, incident.id)


async def _frozen_scenario_version(
    session: AsyncSession, incident_id: str, evidence_ids: list[str]
) -> str | None:
    if not evidence_ids or len(set(evidence_ids)) != len(evidence_ids):
        return None
    rows = list(
        await session.scalars(
            select(Evidence).where(
                Evidence.incident_id == incident_id,
                Evidence.id.in_(evidence_ids),
            )
        )
    )
    if len(rows) != len(evidence_ids):
        return None
    versions: set[str] = set()
    for row in rows:
        if not row.source_uri.startswith("mock://"):
            return None
        if hashlib.sha256(row.content.encode()).hexdigest() != row.content_hash:
            return None
        try:
            content = json.loads(row.content)
        except ValueError:
            return None
        version = content.get("scenario_version") if isinstance(content, dict) else None
        if not isinstance(version, str) or len(version) != 64:
            return None
        versions.add(version)
    return next(iter(versions)) if len(versions) == 1 else None


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
