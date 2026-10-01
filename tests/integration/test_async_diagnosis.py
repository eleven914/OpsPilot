import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from apps.api.main import app
from opspilot.config import Settings
from opspilot.db.session import SessionFactory
from opspilot.models.incident import Incident, TraceEvent
from opspilot.tasks.diagnosis import (
    mark_interrupted_diagnosis_failed,
    run_queued_diagnosis,
)
from opspilot.tasks.dispatch import DiagnosisDispatchError

HEADERS = {"X-User-Id": "async-operator", "X-Role": "operator"}


def test_task_soft_limit_must_be_lower_than_hard_limit() -> None:
    with pytest.raises(ValueError, match="soft time limit"):
        Settings(
            task_soft_time_limit_seconds=300,
            task_time_limit_seconds=300,
        )


def test_chaos_task_controls_are_rejected_in_production() -> None:
    with pytest.raises(ValueError, match="chaos task controls"):
        Settings(env="production", chaos_task_delay_seconds=1)
    with pytest.raises(ValueError, match="chaos task controls"):
        Settings(env="production", chaos_ignore_soft_time_limit=True)


def test_celery_mode_persists_queue_event_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatched: list[tuple[str, str, str]] = []
    settings = Settings(task_mode="celery")
    monkeypatch.setattr(
        "opspilot.incidents.service.get_settings", lambda: settings
    )
    monkeypatch.setattr(
        "opspilot.incidents.service.dispatch_diagnosis",
        lambda incident_id, description, task_id: dispatched.append(
            (incident_id, description, task_id)
        ),
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/incidents",
            headers=HEADERS,
            json={
                "title": "Queued payment diagnosis",
                "description": "payment timeout needs investigation",
                "severity": "P2",
                "service_name": "payment",
            },
        )
        blocked = client.post(
            f"/api/v1/incidents/{response.json()['id']}/messages",
            headers=HEADERS,
            json={"content": "do not overlap this run"},
        )

    assert response.status_code == 201
    assert response.json()["status"] == "QUEUED"
    queued = response.json()["trace"][-1]
    assert queued["event_type"] == "task_queued"
    assert queued["payload"]["task_id"] == dispatched[0][2]
    assert dispatched[0][:2] == (
        response.json()["id"],
        "payment timeout needs investigation",
    )
    assert blocked.status_code == 409


def test_dispatch_failure_is_audited_and_returns_service_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(task_mode="celery")
    monkeypatch.setattr(
        "opspilot.incidents.service.get_settings", lambda: settings
    )

    def fail_dispatch(incident_id: str, description: str, task_id: str) -> None:
        raise DiagnosisDispatchError("Diagnosis task broker is unavailable")

    monkeypatch.setattr(
        "opspilot.incidents.service.dispatch_diagnosis", fail_dispatch
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/incidents",
            headers=HEADERS,
            json={
                "title": "Unavailable task broker",
                "description": "inventory needs a diagnosis",
                "severity": "P2",
                "service_name": "inventory",
            },
        )
        incidents = client.get("/api/v1/incidents", headers=HEADERS).json()

    assert response.status_code == 503
    stored = next(item for item in incidents if item["title"] == "Unavailable task broker")
    assert stored["status"] == "FAILED"
    assert stored["trace"][-1]["event_type"] == "task_dispatch_failed"


@pytest.mark.asyncio
async def test_worker_runs_a_queued_diagnosis_with_a_fresh_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings()
    monkeypatch.setattr("opspilot.tasks.diagnosis.get_settings", lambda: settings)
    async with SessionFactory() as session:
        incident = Incident(
            title="Queued inventory diagnosis",
            description="inventory false alarm is healthy",
            severity="P3",
            service_name="inventory",
            status="QUEUED",
            created_by="worker-test",
        )
        session.add(incident)
        await session.commit()
        incident_id = incident.id

    result = await run_queued_diagnosis(
        incident_id,
        "inventory false alarm is healthy",
        task_id="worker-task-1",
    )

    async with SessionFactory() as session:
        stored = await session.get(Incident, incident_id)
        event_types = list(
            await session.scalars(
                select(TraceEvent.event_type)
                .where(TraceEvent.incident_id == incident_id)
                .order_by(TraceEvent.sequence)
            )
        )
    assert result["status"] == "DIAGNOSED"
    assert stored is not None
    assert stored.status == "DIAGNOSED"
    assert event_types[0] == "task_started"
    assert "final_answer" in event_types


@pytest.mark.asyncio
async def test_worker_resumes_a_redelivered_running_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings()
    monkeypatch.setattr("opspilot.tasks.diagnosis.get_settings", lambda: settings)
    async with SessionFactory() as session:
        incident = Incident(
            title="Redelivered inventory diagnosis",
            description="inventory false alarm is healthy",
            severity="P3",
            service_name="inventory",
            status="RUNNING",
            created_by="worker-test",
        )
        session.add(incident)
        await session.flush()
        session.add(
            TraceEvent(
                incident_id=incident.id,
                sequence=1,
                event_type="task_started",
                payload={"task_id": "redelivered-task"},
            )
        )
        await session.commit()
        incident_id = incident.id

    result = await run_queued_diagnosis(
        incident_id,
        "inventory false alarm is healthy",
        task_id="redelivered-task",
    )

    async with SessionFactory() as session:
        restarted = await session.scalar(
            select(TraceEvent).where(
                TraceEvent.incident_id == incident_id,
                TraceEvent.event_type == "task_restarted",
            )
        )
    assert result["status"] == "DIAGNOSED"
    assert restarted is not None
    assert restarted.payload["redelivered"] is True


@pytest.mark.asyncio
async def test_soft_timeout_is_persisted_as_failed() -> None:
    async with SessionFactory() as session:
        incident = Incident(
            title="Soft timeout diagnosis",
            description="timeout",
            severity="P2",
            service_name="inventory",
            status="RUNNING",
            created_by="worker-test",
        )
        session.add(incident)
        await session.commit()
        incident_id = incident.id

    await mark_interrupted_diagnosis_failed(
        incident_id,
        task_id="soft-timeout-task",
        error_type="SoftTimeLimitExceeded",
    )

    async with SessionFactory() as session:
        stored = await session.get(Incident, incident_id)
        failure = await session.scalar(
            select(TraceEvent).where(
                TraceEvent.incident_id == incident_id,
                TraceEvent.event_type == "task_failed",
            )
        )
    assert stored is not None
    assert stored.status == "FAILED"
    assert failure is not None
    assert failure.payload == {
        "task_id": "soft-timeout-task",
        "error_type": "SoftTimeLimitExceeded",
    }


def test_sse_resumes_from_last_event_id() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/incidents",
            headers=HEADERS,
            json={
                "title": "SSE resume diagnosis",
                "description": "inventory false alarm is healthy",
                "severity": "P3",
                "service_name": "inventory",
            },
        ).json()
        final_sequence = created["trace"][-1]["sequence"]
        events = client.get(
            f"/api/v1/incidents/{created['id']}/events",
            headers={
                "X-User-Id": "async-viewer",
                "X-Role": "viewer",
                "Last-Event-ID": str(final_sequence - 1),
            },
        )

    assert events.status_code == 200
    assert f"id: {final_sequence}\n" in events.text
    assert f"id: {final_sequence - 1}\n" not in events.text
