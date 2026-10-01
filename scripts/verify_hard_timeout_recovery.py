"""Force a Celery hard time limit and verify worker-lost redelivery."""

import json
import subprocess
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def docker(*args: str, capture: bool = False, check: bool = True) -> str:
    result = subprocess.run(
        ["docker", *args],
        cwd=ROOT,
        check=check,
        capture_output=capture,
        text=True,
    )
    return f"{result.stdout}\n{result.stderr}" if capture else ""


def wait_for_worker(container_name: str, timeout_seconds: float = 30) -> None:
    started = time.monotonic()
    while time.monotonic() - started < timeout_seconds:
        logs = docker("logs", container_name, capture=True, check=False)
        if "ready." in logs:
            return
        time.sleep(0.25)
    raise TimeoutError(f"{container_name} did not become ready")


def main() -> None:
    container_name = f"opspilot-worker-timeout-chaos-{time.time_ns()}"
    incident: dict[str, object] | None = None
    running_at: float | None = None

    docker("compose", "stop", "worker")
    try:
        docker(
            "compose",
            "run",
            "-d",
            "--no-deps",
            "--name",
            container_name,
            "--volume",
            f"{ROOT / 'opspilot'}:/app/opspilot:ro",
            "-e",
            "OPSPILOT_WORKER_CONCURRENCY=1",
            "-e",
            "OPSPILOT_TASK_SOFT_TIME_LIMIT_SECONDS=30",
            "-e",
            "OPSPILOT_TASK_TIME_LIMIT_SECONDS=60",
            "-e",
            "OPSPILOT_BROKER_VISIBILITY_TIMEOUT_SECONDS=15",
            "-e",
            "OPSPILOT_CHAOS_TASK_DELAY_SECONDS=70",
            "-e",
            "OPSPILOT_CHAOS_IGNORE_SOFT_TIME_LIMIT=true",
            "worker",
        )
        wait_for_worker(container_name)

        with httpx.Client(
            base_url="http://127.0.0.1:8000",
            timeout=15,
            trust_env=False,
            headers={"X-User-Id": "hard-timeout-test", "X-Role": "operator"},
        ) as client:
            response = client.post(
                "/api/v1/incidents",
                json={
                    "title": f"Hard timeout recovery probe {time.time_ns()}",
                    "description": "inventory false alarm is healthy",
                    "severity": "P3",
                    "service_name": "inventory",
                },
            )
            response.raise_for_status()
            incident = response.json()

            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                incident = client.get(
                    f"/api/v1/incidents/{incident['id']}"
                ).json()
                if incident["status"] == "RUNNING":
                    running_at = time.monotonic()
                    break
                time.sleep(0.1)
            assert incident["status"] == "RUNNING", incident["status"]

            for _ in range(260):
                incident = client.get(
                    f"/api/v1/incidents/{incident['id']}"
                ).json()
                if incident["status"] in {"RESOLVED", "FAILED"}:
                    break
                time.sleep(0.5)

        assert incident is not None
        logs = docker("logs", container_name, capture=True, check=False)
        if incident["status"] != "RESOLVED":
            print(logs[-8000:])
        assert incident["status"] == "RESOLVED", incident["status"]
        starts = [
            event
            for event in incident["trace"]
            if event["event_type"] in {"task_started", "task_restarted"}
        ]
        assert [event["event_type"] for event in starts] == [
            "task_started",
            "task_restarted",
        ]
        task_ids = {event["payload"]["task_id"] for event in starts}
        assert len(task_ids) == 1, task_ids
        assert running_at is not None
        elapsed = time.monotonic() - running_at
        assert elapsed >= 55, elapsed
        assert "Hard time limit (60s) exceeded" in logs, logs[-2000:]
        print(
            json.dumps(
                {
                    "incident_id": incident["id"],
                    "final_status": incident["status"],
                    "recovery_seconds": round(elapsed, 3),
                    "task_id": next(iter(task_ids)),
                    "trace_events": [event["event_type"] for event in starts],
                    "soft_limit_seconds": 30,
                    "hard_limit_seconds": 60,
                    "visibility_timeout_seconds": 15,
                    "hard_limit_log_verified": True,
                },
                indent=2,
            )
        )
    finally:
        docker(
            "stop",
            "--timeout",
            "3",
            container_name,
            capture=True,
            check=False,
        )
        docker("rm", "--force", container_name, capture=True, check=False)
        docker("compose", "start", "worker")


if __name__ == "__main__":
    main()
