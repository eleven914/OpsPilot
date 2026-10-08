"""Run an isolated end-to-end sandbox demonstration without external services."""

import argparse
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


def run_demo() -> tuple[dict[str, Any], dict[str, Any]]:
    # Set process-local configuration before importing the API or DB engine.
    with TemporaryDirectory(prefix="opspilot-local-demo-") as temporary:
        database = Path(temporary) / "demo.db"
        os.environ["OPSPILOT_DATABASE_URL"] = f"sqlite+aiosqlite:///{database.as_posix()}"
        os.environ["OPSPILOT_MODEL_PROVIDER"] = "mock"
        os.environ["OPSPILOT_TASK_MODE"] = "inline"
        os.environ["OPSPILOT_OTEL_ENABLED"] = "false"
        os.environ["OPSPILOT_LOG_LEVEL"] = "ERROR"

        from fastapi.testclient import TestClient
        from sqlalchemy import create_engine

        from opspilot.models import Base

        schema_engine = create_engine(f"sqlite:///{database.as_posix()}")
        try:
            Base.metadata.create_all(schema_engine)
        finally:
            schema_engine.dispose()

        from apps.api.main import app

        operator = {"X-User-Id": "local-demo-operator", "X-Role": "operator"}
        approver = {"X-User-Id": "local-demo-approver", "X-Role": "approver"}
        with TestClient(app) as client:
            created = client.post(
                "/api/v1/incidents",
                headers=operator,
                json={
                    "title": "Local gateway CPU saturation demo",
                    "description": "gateway cpu and latency are increasing",
                    "severity": "P2",
                    "service_name": "gateway",
                },
            )
            created.raise_for_status()
            incident = created.json()
            if incident["status"] != "WAITING_APPROVAL":
                raise RuntimeError("Demo did not request an approval")

            listed = client.get("/api/v1/approvals", headers=approver)
            listed.raise_for_status()
            approval = next(
                item for item in listed.json() if item["incident_id"] == incident["id"]
            )
            decided = client.post(
                f"/api/v1/approvals/{approval['id']}/decision",
                headers=approver,
                json={"decision": "approve", "comment": "Local simulation only"},
            )
            decided.raise_for_status()
            result = decided.json()
            exported = client.get(
                f"/api/v1/incidents/{incident['id']}/audit", headers=operator
            )
            exported.raise_for_status()
            audit: dict[str, Any] = exported.json()

        verifications = [
            item["payload"]
            for item in result["trace"]
            if item["event_type"] == "verification"
        ]
        if result["status"] != "SIMULATION_COMPLETE" or len(verifications) != 1:
            raise RuntimeError("Demo did not complete its sandbox verification")
        verification = verifications[0]
        if verification["status"] != "passed" or not all(
            check["passed"] for check in verification["checks"]
        ):
            raise RuntimeError("Demo verification criteria did not pass")
        if not audit["evidence"] or not all(
            item["source_uri"].startswith("mock://") for item in audit["evidence"]
        ):
            raise RuntimeError("Demo contains non-simulated evidence")
        summary = {
            "incident_id": incident["id"],
            "status": result["status"],
            "evidence_count": len(audit["evidence"]),
            "approval_decision": audit["approvals"][0]["decision"],
            "verification_status": verification["status"],
            "scenario_version": verification["scenario_version"],
            "simulation_only": True,
        }
        return summary, audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--audit-output",
        type=Path,
        help="Create a new JSON audit file; existing files are never overwritten",
    )
    arguments = parser.parse_args()
    summary, audit = run_demo()
    if arguments.audit_output is not None:
        with arguments.audit_output.open("x", encoding="utf-8") as output:
            json.dump(audit, output, ensure_ascii=False, indent=2)
        summary["audit_output"] = str(arguments.audit_output)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
