from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opspilot.tools.schemas import (
    LogsQuery,
    MetricsQuery,
    SearchQuery,
    ServiceInfoQuery,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolCallDecision(StrictModel):
    type: Literal["tool_call"] = "tool_call"
    tool: Literal[
        "query_metrics",
        "query_logs",
        "get_service_info",
        "search_runbook",
        "search_incidents",
    ]
    arguments: dict[str, Any]
    reason: str = Field(min_length=5, max_length=500)

    @model_validator(mode="after")
    def validate_tool_arguments(self) -> "ToolCallDecision":
        schemas: dict[str, type[BaseModel]] = {
            "query_metrics": MetricsQuery,
            "query_logs": LogsQuery,
            "get_service_info": ServiceInfoQuery,
            "search_runbook": SearchQuery,
            "search_incidents": SearchQuery,
        }
        self.arguments = schemas[self.tool].model_validate(self.arguments).model_dump(
            mode="json", exclude_none=True
        )
        return self


class RestartServiceArguments(StrictModel):
    service: str = Field(min_length=1, max_length=64)
    instance_ids: list[str] = Field(min_length=1, max_length=10)
    reason: str = Field(min_length=5, max_length=500)


class RollbackDeploymentArguments(StrictModel):
    service: str = Field(min_length=1, max_length=64)
    target_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    reason: str = Field(min_length=5, max_length=500)


class ProposedActionDecision(StrictModel):
    type: Literal["proposed_action"] = "proposed_action"
    tool: Literal["restart_service", "rollback_deployment"]
    arguments: dict[str, Any]
    risk: Literal["medium", "high"]
    evidence_ids: list[str] = Field(min_length=1, max_length=20)
    rollback_plan: str = Field(min_length=10, max_length=2000)

    @model_validator(mode="after")
    def validate_tool_contract(self) -> "ProposedActionDecision":
        if self.tool == "restart_service":
            validated_arguments = RestartServiceArguments.model_validate(
                self.arguments
            ).model_dump()
            expected_risk = "medium"
        else:
            validated_arguments = RollbackDeploymentArguments.model_validate(
                self.arguments
            ).model_dump()
            expected_risk = "high"
        if self.risk != expected_risk:
            raise ValueError(f"{self.tool} requires risk={expected_risk}")
        self.arguments = validated_arguments
        return self


class FinalAnswerDecision(StrictModel):
    type: Literal["final_answer"] = "final_answer"
    summary: str = Field(min_length=5, max_length=2000)
    root_causes: list[str] = Field(default_factory=list, max_length=10)
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    next_steps: list[str] = Field(default_factory=list, max_length=20)
    insufficient_information: bool = False


ModelDecision = ToolCallDecision | ProposedActionDecision | FinalAnswerDecision
