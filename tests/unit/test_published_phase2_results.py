import json
from pathlib import Path

from opspilot.evaluation.comparison import compare_reports
from opspilot.evaluation.io import load_report
from opspilot.evaluation.schemas import EvaluationComparison

REPORT_DIR = (
    Path(__file__).resolve().parents[2]
    / "evaluation"
    / "reports"
    / "experiments"
    / "opspilot-synthetic-v0.2"
)


def test_published_phase2_reports_pass_fairness_gate() -> None:
    reports = [
        load_report(REPORT_DIR / "base.json"),
        load_report(REPORT_DIR / "sft.json"),
        load_report(REPORT_DIR / "sft_dpo.json"),
    ]
    actual = compare_reports(reports)
    published = EvaluationComparison.model_validate_json(
        (REPORT_DIR / "comparison.json").read_text(encoding="utf-8")
    )

    assert actual == published
    assert published.comparable is True
    assert published.dataset_version == "opspilot-synthetic-v0.2"


def test_published_phase2_report_counts_match_frozen_run() -> None:
    reports = {
        name: json.loads((REPORT_DIR / f"{name}.json").read_text(encoding="utf-8"))
        for name in ("base", "sft", "sft_dpo")
    }

    assert {report["counts"]["samples"] for report in reports.values()} == {1344}
    assert {report["counts"]["tasks"] for report in reports.values()} == {224}
    assert len(reports["base"]["failures"]) == 1232
    assert reports["sft"]["failures"] == []
    assert reports["sft_dpo"]["failures"] == []
