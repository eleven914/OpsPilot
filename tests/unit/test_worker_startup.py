from pathlib import Path

import pytest

from opspilot.tasks.worker import prepare_prometheus_multiprocess_dir


def test_prepare_prometheus_multiprocess_dir_removes_only_metric_databases(
    tmp_path: Path,
) -> None:
    metrics_dir = tmp_path / "prometheus"
    metrics_dir.mkdir()
    stale_metric = metrics_dir / "counter_123.db"
    unrelated = metrics_dir / "keep.txt"
    nested = metrics_dir / "nested"
    stale_metric.write_text("stale", encoding="utf-8")
    unrelated.write_text("keep", encoding="utf-8")
    nested.mkdir()
    (nested / "counter_456.db").write_text("nested", encoding="utf-8")

    prepared = prepare_prometheus_multiprocess_dir(str(metrics_dir))

    assert prepared == metrics_dir.resolve()
    assert not stale_metric.exists()
    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert (nested / "counter_456.db").exists()


def test_prepare_prometheus_multiprocess_dir_creates_missing_directory(
    tmp_path: Path,
) -> None:
    metrics_dir = tmp_path / "new-prometheus"

    prepared = prepare_prometheus_multiprocess_dir(str(metrics_dir))

    assert prepared == metrics_dir.resolve()
    assert metrics_dir.is_dir()


def test_prepare_prometheus_multiprocess_dir_rejects_relative_path() -> None:
    with pytest.raises(ValueError, match="absolute path"):
        prepare_prometheus_multiprocess_dir("relative-prometheus")
