from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class IncidentCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=5, max_length=5000)
    severity: Literal["P1", "P2", "P3", "P4"]
    service_name: Literal["gateway", "order", "payment", "inventory", "notification"]
    source: Literal["manual", "alertmanager"] = "manual"


class IncidentMessageCreate(BaseModel):
    content: str = Field(min_length=5, max_length=5000)


class AlertmanagerAlert(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    status: Literal["firing", "resolved"]
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    starts_at: datetime | None = Field(default=None, alias="startsAt")
    fingerprint: str | None = Field(default=None, max_length=128)


class AlertmanagerWebhook(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    status: Literal["firing", "resolved"]
    receiver: str | None = Field(default=None, max_length=200)
    group_labels: dict[str, str] = Field(default_factory=dict, alias="groupLabels")
    common_labels: dict[str, str] = Field(default_factory=dict, alias="commonLabels")
    common_annotations: dict[str, str] = Field(
        default_factory=dict, alias="commonAnnotations"
    )
    alerts: list[AlertmanagerAlert] = Field(min_length=1, max_length=20)


class TraceEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    sequence: int
    event_type: str
    payload: dict[str, Any]
    created_at: datetime


class IncidentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: str
    severity: str
    service_name: str
    source: str
    status: str
    created_at: datetime
    updated_at: datetime
    trace: list[TraceEventRead] = Field(default_factory=list)


class ApprovalRead(BaseModel):
    id: str
    incident_id: str
    requested_by: str
    decision: str
    expires_at: datetime
    tool_name: str
    arguments: dict[str, Any]
    risk: str
    evidence_ids: list[str]
    rollback_plan: str


class ApprovalDecision(BaseModel):
    decision: Literal["approve", "reject"]
    comment: str | None = Field(default=None, max_length=2000)


class ApprovalComment(BaseModel):
    comment: str | None = Field(default=None, max_length=2000)


class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str
    details: dict[str, Any] = Field(default_factory=dict)
