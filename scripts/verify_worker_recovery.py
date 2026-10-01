"""Stop this project's worker, queue one read-only incident, then restore the worker."""

import json
import subprocess
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def worker(action: str) -> None:
    subprocess.run(
        ["docker", "compose", action, "worker"], cwd=ROOT, check=True,
    )


def main() -> None:
    with httpx.Client(
        base_url="http://127.0.0.1:8000", timeout=30, trust_env=False,
        headers={"X-User-Id": "recovery-test", "X-Role": "operator"},
    ) as client:
        (client.get("/health")).raise_for_status()
        try:
            worker("stop")
            response = client.post("/api/v1/incidents", json={
                "title": "Worker recovery probe",
                "description": "inventory false alarm is healthy",
                "severity": "P3", "service_name": "inventory",
            })
            response.raise_for_status()
            incident = response.json()
            assert incident["status"] == "QUEUED", incident["status"]
        finally:
            worker("start")
        started = time.monotonic()
        while time.monotonic() - started < 60:
            response = client.get(f"/api/v1/incidents/{incident['id']}")
            response.raise_for_status()
            incident = response.json()
            if incident["status"] in {"RESOLVED", "FAILED"}:
                break
            time.sleep(.2)
        assert incident["status"] == "RESOLVED", incident["status"]
        queued = [e for e in incident["trace"] if e["event_type"] == "task_queued"]
        starts = [e for e in incident["trace"] if e["event_type"] == "task_started"]
        assert len(queued) == len(starts) == 1
        assert queued[0]["payload"]["task_id"] == starts[0]["payload"]["task_id"]
        print(json.dumps({
            "incident_id": incident["id"], "before_restart": "QUEUED",
            "after_restart": incident["status"],
            "recovery_seconds": time.monotonic() - started,
            "task_started_count": len(starts),
            "scope": "graceful worker stop; queued task recovery, not in-flight crash recovery",
        }, indent=2))


if __name__ == "__main__":
    main()
