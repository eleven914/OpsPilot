import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from opspilot.training.experiment import build_experiment_manifest, file_sha256


def test_experiment_manifest_records_reproducibility_inputs(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    dataset_manifest = tmp_path / "dataset.json"
    conversion_manifest = tmp_path / "conversion.json"
    config.write_text("stage: sft\nseed: 7\n", encoding="utf-8")
    dataset_manifest.write_text(
        json.dumps({"dataset_version": "data-v1", "files": {"train": {}}}),
        encoding="utf-8",
    )
    conversion_manifest.write_text(
        json.dumps({"files": {"sft_train.jsonl": {"sha256": "b" * 64}}}),
        encoding="utf-8",
    )
    created_at = datetime(2026, 9, 25, tzinfo=UTC)
    manifest = build_experiment_manifest(
        run_id="sft-001",
        stage="sft",
        model_name="test/model",
        config_path=config,
        dataset_manifest_path=dataset_manifest,
        conversion_manifest_path=conversion_manifest,
        seed=7,
        hardware="fixture GPU",
        git_commit="a" * 40,
        git_dirty=False,
        created_at=created_at,
    )
    assert manifest["created_at"] == "2026-09-25T00:00:00+00:00"
    assert manifest["config"]["sha256"] == file_sha256(config)
    assert manifest["dataset"]["version"] == "data-v1"
    assert manifest["dataset"]["training_files"]["sft_train.jsonl"] == {
        "sha256": "b" * 64
    }
    assert manifest["git"] == {"commit": "a" * 40, "dirty": False}
    assert manifest["llamafactory_version"] == "0.9.5"


def test_experiment_manifest_rejects_unknown_stage(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    dataset_manifest = tmp_path / "dataset.json"
    conversion_manifest = tmp_path / "conversion.json"
    config.write_text("stage: invalid\n", encoding="utf-8")
    dataset_manifest.write_text(
        json.dumps({"dataset_version": "data-v1"}), encoding="utf-8"
    )
    conversion_manifest.write_text(json.dumps({"files": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="sft or dpo"):
        build_experiment_manifest(
            run_id="bad",
            stage="invalid",
            model_name="test/model",
            config_path=config,
            dataset_manifest_path=dataset_manifest,
            conversion_manifest_path=conversion_manifest,
            seed=7,
            hardware="fixture GPU",
            git_commit="a" * 40,
            git_dirty=True,
        )
