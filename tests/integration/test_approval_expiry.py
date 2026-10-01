from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from opspilot.approvals.service import expire_pending_approvals
from opspilot.db.session import SessionFactory
from opspilot.models.audit import AgentRun, Approval, ToolCall
from opspilot.models.incident import Incident, TraceEvent


async def test_expired_approval_moves_incident_to_needs_human() -> None:
    async with SessionFactory() as session:
        incident = Incident(
            title="Expiring approval",
            description="Approval should not wait forever",
            source="manual",
            severity="P2",
            service_name="gateway",
            status="WAITING_APPROVAL",
            created_by="expiry-operator",
        )
        session.add(incident)
        await session.flush()
        run = AgentRun(incident_id=incident.id, status="WAITING_APPROVAL")
        session.add(run)
        await session.flush()
        tool_call = ToolCall(
            run_id=run.id,
            incident_id=incident.id,
            tool_name="restart_service",
            arguments_json={
                "service": "gateway",
                "instance_ids": ["gateway-1"],
                "reason": "Restart one saturated instance safely",
            },
            evidence_ids_json=["evidence-expiry"],
            rollback_plan="Keep the instance isolated if checks fail.",
            risk_level="medium",
            status="pending_approval",
            idempotency_key=f"expiry:{incident.id}",
        )
        session.add(tool_call)
        await session.flush()
        approval = Approval(
            incident_id=incident.id,
            tool_call_id=tool_call.id,
            requested_by="expiry-operator",
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        session.add_all(
            [
                approval,
                TraceEvent(
                    incident_id=incident.id,
                    sequence=1,
                    event_type="state_transition",
                    payload={"state": "WAITING_APPROVAL"},
                ),
            ]
        )
        await session.commit()
        incident_id = incident.id
        approval_id = approval.id

    async with SessionFactory() as session:
        assert await expire_pending_approvals(session) == 1
        await session.commit()

    async with SessionFactory() as session:
        stored_incident = await session.get(Incident, incident_id)
        stored_approval = await session.get(Approval, approval_id)
        trace = list(
            await session.scalars(
                select(TraceEvent)
                .where(TraceEvent.incident_id == incident_id)
                .order_by(TraceEvent.sequence)
            )
        )
        assert stored_incident is not None
        assert stored_incident.status == "NEEDS_HUMAN"
        assert stored_approval is not None
        assert stored_approval.decision == "expired"
        assert trace[-1].payload["reason"] == "approval_expired"

        assert await expire_pending_approvals(session) == 0
