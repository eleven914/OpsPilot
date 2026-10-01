import hashlib
import json
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.schemas import AlertmanagerAlert, AlertmanagerWebhook, IncidentRead
from opspilot.config import get_settings
from opspilot.db.session import get_session
from opspilot.incidents.service import start_diagnosis
from opspilot.models.incident import Incident
from opspilot.tasks import DiagnosisDispatchError

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
SessionDependency = Annotated[AsyncSession, Depends(get_session)]
KNOWN_SERVICES = {"gateway", "order", "payment", "inventory", "notification"}


@router.post("/alertmanager", response_model=list[IncidentRead])
async def receive_alertmanager_webhook(
    payload: AlertmanagerWebhook,
    session: SessionDependency,
    webhook_token: Annotated[str | None, Header(alias="X-Webhook-Token")] = None,
) -> list[Incident]:
    expected = get_settings().alertmanager_webhook_token
    if webhook_token is None or not secrets.compare_digest(webhook_token, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook token")

    incidents: list[Incident] = []
    for alert in payload.alerts:
        if alert.status != "firing":
            continue
        external_key = _external_key(alert)
        existing = await session.scalar(
            select(Incident).where(Incident.external_key == external_key)
        )
        if existing is not None:
            incidents.append(existing)
            continue
        labels = {**payload.common_labels, **alert.labels}
        annotations = {**payload.common_annotations, **alert.annotations}
        service_name = labels.get("service") or labels.get("service_name")
        if service_name not in KNOWN_SERVICES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Alert does not reference a known service",
            )
        severity = _severity(labels.get("severity", "warning"))
        title = (
            labels.get("alertname")
            or annotations.get("summary")
            or f"Alertmanager alert for {service_name}"
        )[:200]
        description = (
            annotations.get("description")
            or annotations.get("summary")
            or f"Alertmanager reported a firing alert for {service_name}"
        )[:5000]
        incident = Incident(
            title=title,
            description=description,
            severity=severity,
            service_name=service_name,
            source="alertmanager",
            status="NEW",
            created_by="alertmanager",
            external_key=external_key,
        )
        session.add(incident)
        await session.flush()
        try:
            await start_diagnosis(session, incident, description)
        except DiagnosisDispatchError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        incidents.append(incident)
    await session.commit()
    if not incidents:
        return []
    ids = [incident.id for incident in incidents]
    stored = await session.scalars(
        select(Incident)
        .where(Incident.id.in_(ids))
        .options(selectinload(Incident.trace))
    )
    by_id = {incident.id: incident for incident in stored.unique()}
    return [by_id[incident_id] for incident_id in ids]


def _external_key(alert: AlertmanagerAlert) -> str:
    if alert.fingerprint:
        return f"alertmanager:{alert.fingerprint}"
    material = json.dumps(
        {
            "labels": alert.labels,
            "starts_at": alert.starts_at.isoformat() if alert.starts_at else None,
        },
        sort_keys=True,
    )
    return f"alertmanager:{hashlib.sha256(material.encode()).hexdigest()}"


def _severity(value: str) -> str:
    return {
        "critical": "P1",
        "warning": "P2",
        "info": "P3",
    }.get(value.casefold(), "P3")
