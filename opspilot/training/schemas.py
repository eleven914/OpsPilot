import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opspilot.agent.parser import parse_model_decision

DatasetSplit = Literal["train", "validation", "test"]
PreferenceType = Literal[
    "correct_tool",
    "valid_arguments",
    "evidence_grounded",
    "approval_required",
    "honest_uncertainty",
]


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatMessage(StrictRecord):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1)


class DatasetMetadata(StrictRecord):
    dataset_version: str
    source: Literal["programmatic_synthetic"] = "programmatic_synthetic"
    review_status: Literal["rule_validated_not_human_reviewed"] = (
        "rule_validated_not_human_reviewed"
    )
    seed: int
    variant: int = Field(ge=0)


class SFTRecord(StrictRecord):
    id: str
    split: DatasetSplit
    task_type: Literal["single_tool", "multi_step"]
    template_id: str
    service: str
    messages: list[ChatMessage] = Field(min_length=3)
    expected_decision: dict[str, Any]
    metadata: DatasetMetadata

    @model_validator(mode="after")
    def validate_assistant_decision(self) -> "SFTRecord":
        if self.messages[-1].role != "assistant":
            raise ValueError("Last SFT message must be the assistant decision")
        parsed = parse_model_decision(self.messages[-1].content)
        if parsed.model_dump(mode="json") != self.expected_decision:
            raise ValueError("Assistant output does not match expected_decision")
        return self


class DPORecord(StrictRecord):
    id: str
    split: DatasetSplit
    preference_type: PreferenceType
    template_id: str
    service: str
    prompt: list[ChatMessage] = Field(min_length=2)
    chosen: str
    rejected: str
    metadata: DatasetMetadata

    @model_validator(mode="after")
    def validate_preference_pair(self) -> "DPORecord":
        parse_model_decision(self.chosen)
        if self.chosen == self.rejected:
            raise ValueError("Chosen and rejected outputs must differ")
        json.loads(self.rejected)
        return self
