import json
from pathlib import Path

from opspilot.evaluation.schemas import PredictionRecord
from opspilot.training.schemas import SFTRecord


def build_prompt_messages(record: SFTRecord) -> list[dict[str, str]]:
    """Return only the messages visible to the model at inference time."""
    if record.messages[-1].role != "assistant":
        raise ValueError("Evaluation record must end with the expected assistant answer")
    prompt = record.messages[:-1]
    if not prompt or prompt[-1].role != "user":
        raise ValueError("Evaluation prompt must end with a user message")
    return [message.model_dump(mode="json") for message in prompt]


def load_resumable_predictions(
    path: Path, *, expected_sample_ids: set[str]
) -> dict[str, PredictionRecord]:
    """Load a partial JSONL prediction file while rejecting poisoned resumes."""
    if not path.exists():
        return {}
    predictions: dict[str, PredictionRecord] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            prediction = PredictionRecord.model_validate_json(line)
        except ValueError as error:
            raise ValueError(f"Invalid prediction at {path}:{line_number}") from error
        if prediction.sample_id not in expected_sample_ids:
            raise ValueError(f"Unexpected sample_id in resume file: {prediction.sample_id}")
        if prediction.sample_id in predictions:
            raise ValueError(f"Duplicate sample_id in resume file: {prediction.sample_id}")
        predictions[prediction.sample_id] = prediction
    return predictions


def append_prediction(path: Path, prediction: PredictionRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as destination:
        destination.write(
            json.dumps(prediction.model_dump(mode="json"), ensure_ascii=False) + "\n"
        )
        destination.flush()
