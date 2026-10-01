import asyncio
import logging
from time import perf_counter, sleep
from typing import Any

from billiard.exceptions import SoftTimeLimitExceeded  # type: ignore[import-untyped]
from celery import Task  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from opspilot.config import get_settings
from opspilot.incidents.service import append_trace, run_diagnosis
from opspilot.models.incident import Incident, TraceEvent
from opspilot.observability.metrics import (
    DIAGNOSIS_DURATION,
    DIAGNOSIS_RUNS,
    TASK_DURATION,
    TASK_RUNS,
)
from opspilot.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)
task_settings = get_settings()


@celery_app.task(  # type: ignore[untyped-decorator]
    name="opspilot.diagnose_incident",
    bind=True,
    ignore_result=True,
    soft_time_limit=task_settings.task_soft_time_limit_seconds,
    time_limit=task_settings.task_time_limit_seconds,
)
def diagnose_incident(task: Task, incident_id: str, description: str) -> dict[str, Any]:
    task_id = str(task.request.id)
    try:
        return asyncio.run(
            run_queued_diagnosis(
                incident_id,
                description,
                task_id=task_id,
            )
        )
    except SoftTimeLimitExceeded:
        if get_settings().chaos_ignore_soft_time_limit:
            while True:
                sleep(1)
        asyncio.run(
            mark_interrupted_diagnosis_failed(
                incident_id,
                task_id=task_id,
                error_type="SoftTimeLimitExceeded",
            )
        )
        raise


async def run_queued_diagnosis(
    incident_id: str, description: str, *, task_id: str
) -> dict[str, Any]:
    """Run one queued diagnosis with an event-loop-local SQLAlchemy engine."""
    started = perf_counter()
    outcome = "failed"
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            incident = await session.scalar(
                select(Incident)
                .where(Incident.id == incident_id)
                .with_for_update()
            )
            if incident is None:
                outcome = "not_found"
                return {"incident_id": incident_id, "status": "NOT_FOUND"}
            started_event = await session.scalar(
                select(TraceEvent)
                .where(
                    TraceEvent.incident_id == incident_id,
                    TraceEvent.event_type.in_({"task_started", "task_restarted"}),
                )
                .order_by(TraceEvent.sequence.desc())
                .limit(1)
            )
            is_redelivery = (
                incident.status == "RUNNING"
                and started_event is not None
                and started_event.payload.get("task_id") == task_id
            )
            if incident.status != "QUEUED" and not is_redelivery:
                outcome = "skipped"
                return {"incident_id": incident_id, "status": incident.status}

            incident.status = "RUNNING"
            await append_trace(
                session,
                incident.id,
                "task_restarted" if is_redelivery else "task_started",
                {"task_id": task_id, "redelivered": is_redelivery},
            )
            await session.commit()

            try:
                chaos_settings = get_settings()
                chaos_delay = chaos_settings.chaos_task_delay_seconds
                if chaos_delay and not is_redelivery:
                    await asyncio.sleep(chaos_delay)
                await run_diagnosis(session, incident, description)
                await session.commit()
            except Exception as error:
                await session.rollback()
                failed_incident = await session.get(Incident, incident_id)
                if failed_incident is not None:
                    failed_incident.status = "FAILED"
                    await append_trace(
                        session,
                        incident_id,
                        "task_failed",
                        {"task_id": task_id, "error_type": type(error).__name__},
                    )
                    await session.commit()
                logger.exception(
                    "Diagnosis task failed",
                    extra={
                        "event": "diagnosis_task",
                        "incident_id": incident_id,
                        "task_id": task_id,
                        "outcome": "failed",
                    },
                )
                raise
            outcome = incident.status.casefold()
            return {"incident_id": incident_id, "status": incident.status}
    finally:
        await engine.dispose()
        duration = perf_counter() - started
        TASK_RUNS.labels(outcome).inc()
        TASK_DURATION.observe(duration)
        DIAGNOSIS_RUNS.labels("celery", outcome).inc()
        DIAGNOSIS_DURATION.labels("celery").observe(duration)


async def mark_interrupted_diagnosis_failed(
    incident_id: str, *, task_id: str, error_type: str
) -> None:
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            incident = await session.scalar(
                select(Incident)
                .where(Incident.id == incident_id)
                .with_for_update()
            )
            if incident is None or incident.status != "RUNNING":
                return
            incident.status = "FAILED"
            await append_trace(
                session,
                incident_id,
                "task_failed",
                {"task_id": task_id, "error_type": error_type},
            )
            await session.commit()
    finally:
        await engine.dispose()
