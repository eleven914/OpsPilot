from typing import Literal

from pydantic import BaseModel, Field


class ScenarioAction(BaseModel):
    tool: Literal["restart_service", "rollback_deployment"]
    arguments: dict[str, object]
    risk: Literal["medium", "high"]
    rollback_plan: str = Field(min_length=10)


class ScenarioDefinition(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    fault_type: str = Field(min_length=2)
    service: str = Field(min_length=1, max_length=64)
    keywords: list[str] = Field(min_length=1)
    root_cause: str = Field(min_length=5)
    metrics: dict[str, list[float | int]]
    logs: list[str]
    topology: list[str]
    runbook: str
    previous_incident: str
    recommended_steps: list[str] = Field(min_length=1)
    forbidden_actions: list[str] = Field(min_length=1)
    alternatives: list[str] = Field(min_length=1)
    action: ScenarioAction | None = None
