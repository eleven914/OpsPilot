import json
from pathlib import Path

import pytest

from opspilot.training.generator import (
    DATASET_VERSION,
    DatasetBundle,
    generate_dataset,
)
from opspilot.training.validation import DatasetValidationError, validate_dataset
from opspilot.training.writer import write_dataset


def test_small_dataset_has_expected_shape_and_is_leak_free() -> None:
    bundle = generate_dataset(sft_variants=1, dpo_variants=1)
    report = validate_dataset(
        bundle,
        min_sft_count=1,
        min_dpo_count=1,
        min_test_sft_count=1,
    )
    assert report.sft_count == 72
    assert report.dpo_count == 60
    assert report.sft_by_split == {"train": 48, "validation": 12, "test": 12}
    assert report.dpo_by_split == {"train": 40, "validation": 10, "test": 10}
    assert report.services_by_split == {
        "test": ["inventory"],
        "train": ["gateway", "order", "payment"],
        "validation": ["notification"],
    }
    assert report.duplicate_count == 0
    assert report.human_reviewed is False
    assert report.eligible_for_final_benchmark is False


def test_default_dataset_meets_initial_size_targets() -> None:
    bundle = generate_dataset()
    report = validate_dataset(bundle)
    assert report.sft_count == 8_064
    assert report.dpo_count == 2_040
    assert report.sft_by_split["test"] == 1_344


def test_v02_prompts_expose_tool_contract_and_required_argument_values() -> None:
    assert DATASET_VERSION == "opspilot-synthetic-v0.2"
    bundle = generate_dataset(sft_variants=1, dpo_variants=1)
    metrics = next(record for record in bundle.sft if record.id.endswith("query_metrics"))
    metrics_context = json.loads(metrics.messages[-2].content)
    assert "query_metrics" in metrics.messages[0].content
    assert "instance_ids" in metrics.messages[0].content
    assert "scenario_id" not in metrics.expected_decision["arguments"]
    assert metrics.expected_decision["arguments"]["start"] == metrics_context[
        "observation_start"
    ]
    assert metrics.expected_decision["arguments"]["end"] == metrics_context[
        "observation_end"
    ]
    assert metrics.expected_decision["arguments"]["metric"] == metrics_context[
        "query_defaults"
    ]["metric"]

    logs = next(record for record in bundle.sft if record.id.endswith("query_logs"))
    logs_context = json.loads(logs.messages[-2].content)
    assert logs.expected_decision["arguments"]["keywords"] == logs_context[
        "search_terms"
    ]

    proposed = next(
        record
        for record in bundle.sft
        if record.id.endswith("terminal")
        and record.expected_decision["type"] == "proposed_action"
    )
    proposed_context = json.loads(proposed.messages[-2].content)
    assert proposed_context["candidate_action"]["arguments"] == proposed.expected_decision[
        "arguments"
    ]


def test_duplicate_learning_example_is_rejected() -> None:
    bundle = generate_dataset(sft_variants=1, dpo_variants=1)
    duplicated = DatasetBundle(sft=[*bundle.sft, bundle.sft[0]], dpo=bundle.dpo)
    with pytest.raises(DatasetValidationError, match="not unique|duplicate"):
        validate_dataset(
            duplicated,
            min_sft_count=1,
            min_dpo_count=1,
            min_test_sft_count=1,
        )


def test_unknown_service_cannot_be_silently_assigned_to_split() -> None:
    from opspilot.training.split import build_service_split

    with pytest.raises(ValueError, match="missing an isolated split"):
        build_service_split(["gateway", "unknown-service"])


def test_writer_emits_split_files_and_reproducible_manifest(tmp_path: Path) -> None:
    bundle = generate_dataset(sft_variants=1, dpo_variants=1)
    report = validate_dataset(
        bundle,
        min_sft_count=1,
        min_dpo_count=1,
        min_test_sft_count=1,
    )
    manifest = write_dataset(bundle, report, tmp_path)
    assert manifest["sft_count"] == 72
    assert manifest["files"]["sft_test.jsonl"]["records"] == 12
    assert len(manifest["files"]["sft_test.jsonl"]["sha256"]) == 64
    assert len((tmp_path / "sft_test.jsonl").read_text(encoding="utf-8").splitlines()) == 12
    assert (tmp_path / "manifest.json").is_file()
