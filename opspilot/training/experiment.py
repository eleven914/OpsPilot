import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_experiment_manifest(
    *,
    run_id: str,
    stage: str,
    model_name: str,
    config_path: Path,
    dataset_manifest_path: Path,
    conversion_manifest_path: Path,
    seed: int,
    hardware: str,
    git_commit: str,
    git_dirty: bool,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    dataset_manifest: Any = json.loads(
        dataset_manifest_path.read_text(encoding="utf-8")
    )
    if not isinstance(dataset_manifest, dict):
        raise ValueError("Dataset manifest must be a JSON object")
    dataset_version = dataset_manifest.get("dataset_version")
    if not isinstance(dataset_version, str):
        raise ValueError("Dataset manifest is missing dataset_version")
    if stage not in {"sft", "dpo"}:
        raise ValueError("Experiment stage must be sft or dpo")
    conversion_manifest: Any = json.loads(
        conversion_manifest_path.read_text(encoding="utf-8")
    )
    if not isinstance(conversion_manifest, dict) or not isinstance(
        conversion_manifest.get("files"), dict
    ):
        raise ValueError("Conversion manifest is missing training file hashes")
    timestamp = created_at or datetime.now(UTC)
    return {
        "schema_version": "opspilot-experiment-v0.1",
        "run_id": run_id,
        "stage": stage,
        "created_at": timestamp.isoformat(),
        "model_name": model_name,
        "llamafactory_version": "0.9.5",
        "seed": seed,
        "hardware": hardware,
        "git": {"commit": git_commit, "dirty": git_dirty},
        "config": {
            "path": config_path.as_posix(),
            "sha256": file_sha256(config_path),
        },
        "dataset": {
            "version": dataset_version,
            "manifest_path": dataset_manifest_path.as_posix(),
            "manifest_sha256": file_sha256(dataset_manifest_path),
            "files": dataset_manifest.get("files", {}),
            "conversion_manifest_path": conversion_manifest_path.as_posix(),
            "conversion_manifest_sha256": file_sha256(conversion_manifest_path),
            "training_files": conversion_manifest["files"],
        },
    }
