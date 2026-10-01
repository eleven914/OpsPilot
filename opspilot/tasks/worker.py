import os
from pathlib import Path

from opspilot.config import get_settings


def prepare_prometheus_multiprocess_dir(raw_path: str) -> Path:
    configured_path = Path(raw_path).expanduser()
    if not configured_path.is_absolute():
        raise ValueError("PROMETHEUS_MULTIPROC_DIR must be an absolute path")
    metrics_dir = configured_path.resolve()

    metrics_dir.mkdir(parents=True, exist_ok=True)
    for metric_file in metrics_dir.glob("*.db"):
        if metric_file.is_file():
            metric_file.unlink()
    return metrics_dir


def main() -> None:
    metrics_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if metrics_dir:
        prepare_prometheus_multiprocess_dir(metrics_dir)
    concurrency = get_settings().worker_concurrency

    os.execvp(
        "celery",
        [
            "celery",
            "--app=opspilot.tasks.celery_app:celery_app",
            "worker",
            "--loglevel=INFO",
            f"--concurrency={concurrency}",
        ],
    )


if __name__ == "__main__":
    main()
