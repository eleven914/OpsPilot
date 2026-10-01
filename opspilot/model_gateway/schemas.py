from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatMessage(StrictModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1)


class ModelUsage(StrictModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class ModelResponse(StrictModel):
    content: str = Field(min_length=1)
    model: str = Field(min_length=1)
    usage: ModelUsage = Field(default_factory=ModelUsage)
    latency_ms: int = Field(ge=0)
