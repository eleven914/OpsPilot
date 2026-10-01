"""Kill an active worker container and verify Redis visibility-timeout redelivery."""

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


def start_standard_worker() -> None:
    docker("compose", "start", "worker")


def main() -> None:
    container_name = f"opspilot-worker-container-chaos-{time.time_ns()}"
    incident: dict[str, object] | None = None
    killed_at: float | None = None
    standard_worker_started = False

    docker("compose", "stop", "worker")
    try:
        docker(
            "compose",
            "run",
            "--rm",
            "-d",
            "--no-deps",
            "--name",
            container_name,
            "--volume",
            f"{ROOT / 'opspilot'}:/app/opspilot:ro",
            "-e",
            "OPSPILOT_WORKER_CONCURRENCY=1",
            "-e",
            "OPSPILOT_CHAOS_TASK_DELAY_SECONDS=20",
            "worker",
        )
        wait_for_worker(container_name)

        with httpx.Client(
            base_url="http://127.0.0.1:8000",
            timeout=15,
            trust_env=False,
            headers={"X-User-Id": "container-crash-test", "X-Role": "operator"},
        ) as client:
            response = client.post(
                "/api/v1/incidents",
                json={
                    "title": f"Worker container crash probe {time.time_ns()}",
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
                    break
                time.sleep(0.1)
            assert incident["status"] == "RUNNING", incident["status"]

            docker("kill", "--signal", "KILL", container_name)
            killed_at = time.monotonic()
            start_standard_worker()
            standard_worker_started = True

            deadline = time.monotonic() + 100
            while time.monotonic() < deadline:
                incident = client.get(
                    f"/api/v1/incidents/{incident['id']}"
                ).json()
                if incident["status"] in {"RESOLVED", "FAILED"}:
                    break
                time.sleep(0.5)

        assert incident is not None
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
        assert killed_at is not None
        print(
            json.dumps(
                {
                    "incident_id": incident["id"],
                    "final_status": incident["status"],
                    "recovery_seconds": round(time.monotonic() - killed_at, 3),
                    "task_id": next(iter(task_ids)),
                    "trace_events": [event["event_type"] for event in starts],
                    "killed_process": "entire worker container",
                    "redelivery_mechanism": "Redis visibility timeout",
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
        if not standard_worker_started:
            start_standard_worker()


if __name__ == "__main__":
    main()
