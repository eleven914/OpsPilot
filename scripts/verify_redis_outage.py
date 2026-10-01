"""Stop this project's Redis, verify fast audited dispatch failure, then restore it."""

import json
import subprocess
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def redis(action: str) -> None:
    subprocess.run(
        ["docker", "compose", action, "redis"],
        cwd=ROOT,
        check=True,
    )


def main() -> None:
    title = f"Redis outage probe {time.time_ns()}"
    response_status: int | None = None
    elapsed_seconds: float | None = None

    with httpx.Client(
        base_url="http://127.0.0.1:8000",
        timeout=15,
        trust_env=False,
        headers={"X-User-Id": "redis-outage-test", "X-Role": "operator"},
    ) as client:
        client.get("/health").raise_for_status()
        try:
            redis("stop")
            started = time.monotonic()
            response = client.post(
                "/api/v1/incidents",
                json={
                    "title": title,
                    "description": "inventory false alarm is healthy",
                    "severity": "P3",
                    "service_name": "inventory",
                },
            )
            elapsed_seconds = time.monotonic() - started
            response_status = response.status_code
        finally:
            redis("start")

        assert response_status == 503, response_status
        assert elapsed_seconds is not None and elapsed_seconds < 5, elapsed_seconds

        incidents = client.get("/api/v1/incidents").json()
        incident = next(item for item in incidents if item["title"] == title)
        assert incident["status"] == "FAILED", incident["status"]
        assert incident["trace"][-1]["event_type"] == "task_dispatch_failed"

        print(
            json.dumps(
                {
                    "incident_id": incident["id"],
                    "http_status": response_status,
                    "failure_seconds": round(elapsed_seconds, 3),
                    "stored_status": incident["status"],
                    "last_trace_event": incident["trace"][-1]["event_type"],
                    "redis_restored": True,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
