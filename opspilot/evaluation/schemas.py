from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ModelGroup = Literal["base", "sft", "sft_dpo"]


class StrictEvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PredictionRecord(StrictEvaluationModel):
    sample_id: str = Field(min_length=1)
    output: str = Field(min_length=1)
    latency_ms: float | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class EvaluationRunMetadata(StrictEvaluationModel):
    model_group: ModelGroup
    model_name: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    temperature: float = Field(default=0.0, ge=0)
    max_tokens: int = Field(default=1024, ge=1)


class EvaluationMetrics(StrictEvaluationModel):
    tool_selection_accuracy: float = Field(ge=0, le=1)
    argument_schema_match_rate: float = Field(ge=0, le=1)
    argument_exact_match_rate: float = Field(ge=0, le=1)
    invalid_tool_call_rate: float = Field(ge=0, le=1)
    unsafe_action_rate: float = Field(ge=0, le=1)
    evidence_citation_precision: float = Field(ge=0, le=1)
    task_success_rate: float = Field(ge=0, le=1)
    average_tool_calls_per_task: float = Field(ge=0)
    hallucination_rate: float = Field(ge=0, le=1)
    valid_decision_rate: float = Field(ge=0, le=1)


class EvaluationCounts(StrictEvaluationModel):
    samples: int
    tasks: int
    tool_samples: int
    terminal_samples: int
    valid_decisions: int
    successful_tasks: int
    unsafe_outputs: int
    hallucinated_terminal_outputs: int


class SampleFailure(StrictEvaluationModel):
    sample_id: str
    reasons: list[str]


class EvaluationReport(StrictEvaluationModel):
    schema_version: Literal["opspilot-eval-v0.1"] = "opspilot-eval-v0.1"
    metadata: EvaluationRunMetadata
    metrics: EvaluationMetrics
    counts: EvaluationCounts
    failures: list[SampleFailure]
    comparable: bool = True
    notes: list[str] = Field(
        default_factory=lambda: [
            "Metrics are measured from supplied predictions, not estimated.",
            "Comparisons are valid only when dataset hash and generation settings match.",
        ]
    )


class EvaluationComparison(StrictEvaluationModel):
    schema_version: Literal["opspilot-comparison-v0.1"] = (
        "opspilot-comparison-v0.1"
    )
    dataset_version: str
    dataset_sha256: str
    temperature: float
    max_tokens: int
    metrics_by_group: dict[ModelGroup, EvaluationMetrics]
    models_by_group: dict[ModelGroup, str]
    comparable: Literal[True] = True
