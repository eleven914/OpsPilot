import json
import subprocess
import sys
from pathlib import Path


def test_local_demo_uses_isolated_database_and_mock_evidence(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    audit_path = tmp_path / "audit.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(root / "scripts/demo_local_simulation.py"),
            "--audit-output",
            str(audit_path),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    summary = json.loads(completed.stdout.strip())
    assert summary["status"] == "SIMULATION_COMPLETE"
    assert summary["verification_status"] == "passed"
    assert summary["approval_decision"] == "approved"
    assert summary["evidence_count"] == 5
    assert summary["simulation_only"] is True
    assert len(summary["scenario_version"]) == 64
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["incident"]["id"] == summary["incident_id"]
    assert all(item["source_uri"].startswith("mock://") for item in audit["evidence"])
    assert any(item["event_type"] == "verification" for item in audit["trace"])

    repeated = subprocess.run(
        [
            sys.executable,
            str(root / "scripts/demo_local_simulation.py"),
            "--audit-output",
            str(audit_path),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert repeated.returncode != 0
    assert json.loads(audit_path.read_text(encoding="utf-8")) == audit
