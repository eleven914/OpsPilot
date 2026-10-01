from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from opspilot.agent.state import AgentState, assert_transition
from opspilot.models.audit import AgentRun, Approval, ToolCall
from opspilot.models.incident import Incident, TraceEvent


async def expire_pending_approvals(
    session: AsyncSession, *, now: datetime | None = None
) -> int:
    """Move expired pending approvals to NEEDS_HUMAN in one transaction scope."""
    checked_at = now or datetime.now(UTC)
    rows = (
        await session.execute(
            select(Approval, ToolCall, Incident)
            .join(ToolCall, Approval.tool_call_id == ToolCall.id)
            .join(Incident, Approval.incident_id == Incident.id)
            .where(Approval.decision == "pending", Approval.expires_at <= checked_at)
            .with_for_update()
        )
    ).all()
    for approval, tool_call, incident in rows:
        assert_transition(AgentState(incident.status), AgentState.NEEDS_HUMAN)
        approval.decision = "expired"
        tool_call.status = "expired"
        incident.status = AgentState.NEEDS_HUMAN
        run = await session.get(AgentRun, tool_call.run_id)
        if run is not None:
            run.status = "NEEDS_HUMAN"
        current = await session.scalar(
            select(func.max(TraceEvent.sequence)).where(
                TraceEvent.incident_id == incident.id
            )
        )
        session.add(
            TraceEvent(
                incident_id=incident.id,
                sequence=(current or 0) + 1,
                event_type="state_transition",
                payload={
                    "state": AgentState.NEEDS_HUMAN,
                    "reason": "approval_expired",
                },
            )
        )
    if rows:
        await session.flush()
    return len(rows)
