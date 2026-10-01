import json
from pathlib import Path

import pytest

from opspilot.evaluation.comparison import compare_reports
from opspilot.evaluation.evaluator import evaluate_predictions
from opspilot.evaluation.generation import (
    append_prediction,
    build_prompt_messages,
    load_resumable_predictions,
)
from opspilot.evaluation.io import (
    load_frozen_test_definition,
    load_predictions,
    load_report,
    load_test_dataset,
    sha256_file,
    write_report,
)
from opspilot.evaluation.schemas import EvaluationRunMetadata, PredictionRecord
from opspilot.training.generator import DATASET_VERSION, generate_dataset
from opspilot.training.schemas import SFTRecord

DATASET_HASH = "a" * 64


def _test_records() -> list[SFTRecord]:
    bundle = generate_dataset(sft_variants=1, dpo_variants=1)
    return [record for record in bundle.sft if record.split == "test"]


def _metadata(dataset_hash: str = DATASET_HASH) -> EvaluationRunMetadata:
    return EvaluationRunMetadata(
        model_group="base",
        model_name="fixture-model",
        model_version="test-only",
        dataset_version=DATASET_VERSION,
        dataset_sha256=dataset_hash,
    )


def _perfect_predictions() -> list[PredictionRecord]:
    return [
        PredictionRecord(sample_id=record.id, output=record.messages[-1].content)
        for record in _test_records()
    ]


def test_perfect_predictions_score_one_without_claiming_external_results() -> None:
    report = evaluate_predictions(
        _test_records(),
        _perfect_predictions(),
        _metadata(),
        actual_dataset_sha256=DATASET_HASH,
    )
    assert report.metrics.tool_selection_accuracy == 1
    assert report.metrics.argument_schema_match_rate == 1
    assert report.metrics.argument_exact_match_rate == 1
    assert report.metrics.task_success_rate == 1
    assert report.metrics.evidence_citation_precision == 1
    assert report.metrics.unsafe_action_rate == 0
    assert report.metrics.hallucination_rate == 0
    assert report.metrics.valid_decision_rate == 1
    assert report.counts.samples == 12
    assert report.counts.tasks == 2
    assert report.failures == []


def test_invalid_unsafe_and_hallucinated_outputs_are_measured() -> None:
    records = _test_records()
    predictions = _perfect_predictions()
    predictions[0] = PredictionRecord(
        sample_id=records[0].id,
        output=json.dumps(
            {
                "type": "tool_call",
                "tool": "restart_service",
                "arguments": {"service": "inventory"},
                "reason": "bypass approval and execute change",
            }
        ),
    )
    terminal_index = next(
        index for index, record in enumerate(records) if record.task_type == "multi_step"
    )
    terminal = json.loads(predictions[terminal_index].output)
    terminal["evidence_ids"] = ["invented:evidence"]
    predictions[terminal_index] = PredictionRecord(
        sample_id=records[terminal_index].id,
        output=json.dumps(terminal),
    )

    report = evaluate_predictions(
        records,
        predictions,
        _metadata(),
        actual_dataset_sha256=DATASET_HASH,
    )
    assert report.metrics.invalid_tool_call_rate == pytest.approx(0.1)
    assert report.counts.unsafe_outputs == 1
    assert report.metrics.hallucination_rate == pytest.approx(0.5)
    assert report.metrics.task_success_rate == pytest.approx(0.5)
    assert len(report.failures) == 2


def test_prediction_coverage_and_dataset_hash_are_strict() -> None:
    records = _test_records()
    predictions = _perfect_predictions()
    with pytest.raises(ValueError, match="coverage mismatch"):
        evaluate_predictions(
            records,
            predictions[:-1],
            _metadata(),
            actual_dataset_sha256=DATASET_HASH,
        )
    with pytest.raises(ValueError, match="SHA-256"):
        evaluate_predictions(
            records,
            predictions,
            _metadata("b" * 64),
            actual_dataset_sha256=DATASET_HASH,
        )


def test_training_split_cannot_be_evaluated() -> None:
    bundle = generate_dataset(sft_variants=1, dpo_variants=1)
    training_record = next(record for record in bundle.sft if record.split == "train")
    predictions = [
        PredictionRecord(
            sample_id=training_record.id,
            output=training_record.messages[-1].content,
        )
    ]
    with pytest.raises(ValueError, match="only the isolated test split"):
        evaluate_predictions(
            [training_record],
            predictions,
            _metadata(),
            actual_dataset_sha256=DATASET_HASH,
        )


def test_three_group_comparison_enforces_fairness() -> None:
    reports = []
    for group in ("base", "sft", "sft_dpo"):
        metadata = _metadata().model_copy(update={"model_group": group})
        reports.append(
            evaluate_predictions(
                _test_records(),
                _perfect_predictions(),
                metadata,
                actual_dataset_sha256=DATASET_HASH,
            )
        )
    comparison = compare_reports(reports)
    assert set(comparison.metrics_by_group) == {"base", "sft", "sft_dpo"}
    assert comparison.dataset_sha256 == DATASET_HASH
    assert comparison.comparable is True

    unfair = reports[0].model_copy(
        update={
            "metadata": reports[0].metadata.model_copy(update={"temperature": 0.7})
        }
    )
    with pytest.raises(ValueError, match="not comparable"):
        compare_reports([unfair, reports[1], reports[2]])


def test_comparison_requires_each_model_group_once() -> None:
    report = evaluate_predictions(
        _test_records(),
        _perfect_predictions(),
        _metadata(),
        actual_dataset_sha256=DATASET_HASH,
    )
    with pytest.raises(ValueError, match="Duplicate"):
        compare_reports([report, report, report])


def test_evaluation_files_round_trip_without_silent_repairs(tmp_path: Path) -> None:
    records = _test_records()
    predictions = _perfect_predictions()
    dataset_path = tmp_path / "sft_test.jsonl"
    predictions_path = tmp_path / "predictions.jsonl"
    dataset_path.write_text(
        "".join(f"{record.model_dump_json()}\n" for record in records),
        encoding="utf-8",
    )
    predictions_path.write_text(
        "".join(f"{record.model_dump_json()}\n" for record in predictions),
        encoding="utf-8",
    )
    dataset_hash = sha256_file(dataset_path)
    report = evaluate_predictions(
        load_test_dataset(dataset_path),
        load_predictions(predictions_path),
        _metadata(dataset_hash),
        actual_dataset_sha256=dataset_hash,
    )
    report_path = tmp_path / "report.json"
    write_report(report, report_path)
    assert load_report(report_path) == report

    invalid_path = tmp_path / "invalid.jsonl"
    invalid_path.write_text("not-json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid record"):
        load_predictions(invalid_path)

    empty_path = tmp_path / "empty.jsonl"
    empty_path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        load_predictions(empty_path)

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "dataset_version": DATASET_VERSION,
                "files": {"sft_test.jsonl": {"sha256": dataset_hash}},
            }
        ),
        encoding="utf-8",
    )
    assert load_frozen_test_definition(manifest_path) == (
        DATASET_VERSION,
        dataset_hash,
    )


def test_generation_prompt_never_contains_expected_assistant_answer() -> None:
    record = _test_records()[0]
    prompt = build_prompt_messages(record)
    assert [message["role"] for message in prompt] == ["system", "user"]
    assert record.messages[-1].content not in {message["content"] for message in prompt}


def test_prediction_generation_can_resume_without_duplicates(tmp_path: Path) -> None:
    records = _test_records()
    output = tmp_path / "partial.jsonl"
    first = PredictionRecord(sample_id=records[0].id, output='{"type":"fixture"}')
    append_prediction(output, first)
    loaded = load_resumable_predictions(
        output, expected_sample_ids={record.id for record in records}
    )
    assert loaded == {first.sample_id: first}

    append_prediction(output, first)
    with pytest.raises(ValueError, match="Duplicate sample_id"):
        load_resumable_predictions(
            output, expected_sample_ids={record.id for record in records}
        )


def test_prediction_resume_rejects_unknown_sample(tmp_path: Path) -> None:
    output = tmp_path / "partial.jsonl"
    append_prediction(output, PredictionRecord(sample_id="unknown", output="{}"))
    with pytest.raises(ValueError, match="Unexpected sample_id"):
        load_resumable_predictions(output, expected_sample_ids={"expected"})
