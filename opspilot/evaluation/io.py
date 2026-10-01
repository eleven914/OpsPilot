import hashlib
import json
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from opspilot.evaluation.schemas import EvaluationReport, PredictionRecord
from opspilot.training.schemas import SFTRecord

RecordT = TypeVar("RecordT", bound=BaseModel)


def load_frozen_test_definition(path: Path) -> tuple[str, str]:
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Dataset manifest must be a JSON object")
    version = raw.get("dataset_version")
    files = raw.get("files")
    test_file = files.get("sft_test.jsonl") if isinstance(files, dict) else None
    digest = test_file.get("sha256") if isinstance(test_file, dict) else None
    if not isinstance(version, str) or not isinstance(digest, str):
        raise ValueError("Dataset manifest is missing the frozen SFT test definition")
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError("Frozen SFT test SHA-256 is invalid")
    return version, digest


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_jsonl(path: Path, model: type[RecordT]) -> list[RecordT]:
    records: list[RecordT] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            records.append(model.model_validate_json(line))
        except ValueError as error:
            raise ValueError(f"Invalid record at {path}:{line_number}") from error
    return records


def load_test_dataset(path: Path) -> list[SFTRecord]:
    records = load_jsonl(path, SFTRecord)
    if not records:
        raise ValueError("Evaluation dataset is empty")
    if any(record.split != "test" for record in records):
        raise ValueError("Evaluation accepts only the isolated test split")
    return records


def load_predictions(path: Path) -> list[PredictionRecord]:
    records = load_jsonl(path, PredictionRecord)
    if not records:
        raise ValueError("Prediction file is empty")
    return records


def load_report(path: Path) -> EvaluationReport:
    return EvaluationReport.model_validate_json(path.read_text(encoding="utf-8"))


def write_report(report: EvaluationReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
