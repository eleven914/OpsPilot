import json
from hashlib import sha256
from math import isfinite
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator


class ScenarioAction(BaseModel):
    tool: Literal["restart_service", "rollback_deployment"]
    arguments: dict[str, object]
    risk: Literal["medium", "high"]
    rollback_plan: str = Field(min_length=10)


class VerificationCheck(BaseModel):
    metric: str = Field(min_length=1)
    operator: Literal["le", "ge"]
    threshold: float


class ScenarioVerification(BaseModel):
    metrics_after: dict[str, list[float | int]]
    logs_after: list[str] = Field(min_length=1)
    required_log: str = Field(min_length=1)
    checks: list[VerificationCheck] = Field(min_length=1)


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
    verification: ScenarioVerification | None = None

    @model_validator(mode="after")
    def validate_verification(self) -> Self:
        if (self.action is None) != (self.verification is None):
            raise ValueError("Action scenarios require a verification fixture")
        if self.verification is not None:
            for check in self.verification.checks:
                if not self.metrics.get(check.metric):
                    raise ValueError("Verification metric must exist before action")
                after = self.verification.metrics_after.get(check.metric)
                if not after:
                    raise ValueError("Verification metric must have post-action samples")
                if not isfinite(check.threshold) or not all(
                    isfinite(float(value)) for value in after
                ):
                    raise ValueError("Verification values must be finite")
        return self


def scenario_version(scenario: ScenarioDefinition) -> str:
    """Stable content digest for audit, independent of local file paths."""
    content = json.dumps(scenario.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    return sha256(content.encode()).hexdigest()
