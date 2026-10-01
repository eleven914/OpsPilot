import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from opspilot.incidents import service as incident_service

SCENARIOS = json.loads(
    (Path(__file__).resolve().parents[2] / "simulator/scenarios/scenarios.json")
    .read_text(encoding="utf-8")
)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda item: item["id"])
def test_each_scenario_completes_through_api(scenario: dict[str, object]) -> None:
    service = str(scenario["service"])
    keywords = scenario["keywords"]
    assert isinstance(keywords, list)
    description = f"alert reports {keywords[0]}"
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/incidents",
            headers={"X-User-Id": "scenario-operator", "X-Role": "operator"},
            json={
                "title": f"Scenario {scenario['id']}",
                "description": description,
                "severity": "P2",
                "service_name": service,
            },
        )
    assert response.status_code == 201
    incident = response.json()
    trace = incident["trace"]
    tools = [item["payload"]["tool"] for item in trace if item["event_type"] == "tool_call"]
    assert tools == [
        "query_metrics", "query_logs", "get_service_info",
        "search_runbook", "search_incidents",
    ]
    expected_status = "WAITING_APPROVAL" if scenario["action"] else "DIAGNOSED"
    assert incident["status"] == expected_status
    assert trace[-1]["payload"]["state"] == expected_status


@pytest.mark.asyncio
async def test_inline_diagnoses_do_not_hold_sqlite_write_lock_during_model_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = 0
    maximum_active = 0

    async def slow_diagnosis(*_: object) -> list[dict[str, object]]:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.2)
        active -= 1
        return [{"event_type": "state_transition", "payload": {"state": "DIAGNOSED"}}]

    monkeypatch.setattr(incident_service, "_diagnosis_events", slow_diagnosis)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async def create(index: int) -> httpx.Response:
            return await client.post(
                "/api/v1/incidents",
                headers={"X-User-Id": "concurrent-operator", "X-Role": "operator"},
                json={
                    "title": f"Concurrent diagnosis {index}",
                    "description": "inventory false alarm is healthy",
                    "severity": "P3",
                    "service_name": "inventory",
                },
            )

        responses = await asyncio.wait_for(asyncio.gather(create(1), create(2)), timeout=3)

    assert maximum_active == 2
    assert [response.status_code for response in responses] == [201, 201]
    assert [response.json()["status"] for response in responses] == ["DIAGNOSED", "DIAGNOSED"]


def test_create_incident_requires_approval_then_executes_action() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/incidents",
            headers={"X-User-Id": "alice", "X-Role": "operator"},
            json={
                "title": "Gateway latency alert",
                "description": "gateway latency and cpu are increasing",
                "severity": "P2",
                "service_name": "gateway",
                "source": "manual",
            },
        )
        assert response.status_code == 201
        incident = response.json()
        assert incident["status"] == "WAITING_APPROVAL"
        tool_calls = [
            event
            for event in incident["trace"]
            if event["event_type"] == "tool_call"
        ]
        assert len(tool_calls) == 5
        proposal = next(
            event
            for event in incident["trace"]
            if event["event_type"] == "proposed_action"
        )
        assert proposal["payload"]["tool"] == "restart_service"
        assert len(proposal["payload"]["evidence_ids"]) == 5

        pending = client.get(
            "/api/v1/approvals",
            headers={"X-User-Id": "bob", "X-Role": "approver"},
        )
        assert pending.status_code == 200
        approval = next(
            item for item in pending.json() if item["incident_id"] == incident["id"]
        )
        assert approval["risk"] == "medium"

        self_approval = client.post(
            f"/api/v1/approvals/{approval['id']}/decision",
            headers={"X-User-Id": "alice", "X-Role": "approver"},
            json={"decision": "approve"},
        )
        assert self_approval.status_code == 403

        approved = client.post(
            f"/api/v1/approvals/{approval['id']}/decision",
            headers={"X-User-Id": "bob", "X-Role": "approver"},
            json={"decision": "approve", "comment": "Evidence reviewed"},
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "SIMULATION_COMPLETE"
        event_types = [event["event_type"] for event in approved.json()["trace"]]
        assert "tool_result" in event_types
        assert "verification" in event_types
        verification = next(
            event for event in approved.json()["trace"]
            if event["event_type"] == "verification"
        )
        assert "no real service health check" in verification["payload"]["message"]
        assert approved.json()["trace"][-1]["payload"]["state"] == "SIMULATION_COMPLETE"

        duplicate = client.post(
            f"/api/v1/approvals/{approval['id']}/decision",
            headers={"X-User-Id": "carol", "X-Role": "approver"},
            json={"decision": "approve"},
        )
        assert duplicate.status_code == 409


def test_invalid_service_is_rejected_before_agent() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/incidents",
            headers={"X-User-Id": "alice", "X-Role": "operator"},
            json={
                "title": "Unknown service",
                "description": "something is wrong",
                "severity": "P2",
                "service_name": "production-root",
            },
        )
    assert response.status_code == 422


def test_audit_export_contains_linked_records_and_enforces_owner_access() -> None:
    owner = {"X-User-Id": "audit-owner", "X-Role": "operator"}
    other = {"X-User-Id": "audit-other", "X-Role": "operator"}
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/incidents",
            headers=owner,
            json={
                "title": "Inventory false alarm",
                "description": "inventory false alarm is healthy",
                "severity": "P3",
                "service_name": "inventory",
            },
        )
        assert created.status_code == 201
        incident_id = created.json()["id"]

        response = client.get(f"/api/v1/incidents/{incident_id}/audit", headers=owner)
        assert response.status_code == 200
        assert response.headers["content-disposition"].endswith(
            f'opspilot-incident-{incident_id}-audit.json"'
        )
        report = response.json()
        assert report["schema_version"] == 1
        assert report["incident"]["id"] == incident_id
        assert report["incident"]["created_by"] == "audit-owner"
        assert len(report["agent_runs"]) == 1
        assert len(report["tool_calls"]) == 5
        assert len(report["evidence"]) == 5
        assert [event["sequence"] for event in report["trace"]] == list(
            range(1, len(report["trace"]) + 1)
        )
        assert {item["id"] for item in report["evidence"]} == {
            evidence_id
            for call in report["tool_calls"]
            for evidence_id in call["evidence_ids"]
        }

        hidden = client.get(f"/api/v1/incidents/{incident_id}/audit", headers=other)
        assert hidden.status_code == 404


def test_viewer_cannot_create_incident() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/incidents",
            headers={"X-User-Id": "viewer-1", "X-Role": "viewer"},
            json={
                "title": "Payment timeout",
                "description": "payment redis timeout is increasing",
                "severity": "P2",
                "service_name": "payment",
            },
        )
    assert response.status_code == 403


def test_approver_can_reject_high_risk_rollback() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/incidents",
            headers={"X-User-Id": "operator-2", "X-Role": "operator"},
            json={
                "title": "Order release regression",
                "description": "order 5xx increased immediately after release",
                "severity": "P1",
                "service_name": "order",
            },
        )
        assert created.status_code == 201
        assert created.json()["status"] == "WAITING_APPROVAL"

        pending = client.get(
            "/api/v1/approvals",
            headers={"X-User-Id": "approver-2", "X-Role": "approver"},
        ).json()
        approval = next(
            item for item in pending if item["incident_id"] == created.json()["id"]
        )
        assert approval["tool_name"] == "rollback_deployment"
        assert approval["risk"] == "high"

        rejected = client.post(
            f"/api/v1/approvals/{approval['id']}/reject",
            headers={"X-User-Id": "approver-2", "X-Role": "approver"},
            json={"comment": "Need a maintenance window"},
        )
        assert rejected.status_code == 200
        assert rejected.json()["status"] == "REJECTED"
        rejected_items = client.get(
            "/api/v1/approvals?status=rejected",
            headers={"X-User-Id": "approver-2", "X-Role": "approver"},
        )
        assert any(item["id"] == approval["id"] for item in rejected_items.json())


def test_read_only_diagnosis_completes_without_claiming_repair() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/incidents",
            headers={"X-User-Id": "operator-3", "X-Role": "operator"},
            json={
                "title": "Payment Redis timeout",
                "description": "payment redis timeouts are increasing",
                "severity": "P2",
                "service_name": "payment",
            },
        )
    assert created.status_code == 201
    assert created.json()["status"] == "DIAGNOSED"
    assert not any(
        event["event_type"] in {"tool_result", "verification"}
        for event in created.json()["trace"]
    )
    final = next(
        event
        for event in created.json()["trace"]
        if event["event_type"] == "final_answer"
    )
    assert len(final["payload"]["evidence_ids"]) == 5


def test_resolved_incident_events_are_available_as_sse() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/incidents",
            headers={"X-User-Id": "sse-operator", "X-Role": "operator"},
            json={
                "title": "Inventory diagnostic",
                "description": "inventory health check needs investigation",
                "severity": "P3",
                "service_name": "inventory",
            },
        )
        incident_id = created.json()["id"]
        events = client.get(
            f"/api/v1/incidents/{incident_id}/events",
            headers={"X-User-Id": "sse-viewer", "X-Role": "viewer"},
        )
    assert events.status_code == 200
    assert events.headers["content-type"].startswith("text/event-stream")
    assert "event: tool_call" in events.text
    assert "event: final_answer" in events.text
    assert '"sequence": 1' in events.text


def test_operator_cannot_read_another_operators_incident() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/incidents",
            headers={"X-User-Id": "owner-operator", "X-Role": "operator"},
            json={
                "title": "Private operator incident",
                "description": "payment redis timeout is increasing",
                "severity": "P2",
                "service_name": "payment",
            },
        )
        incident_id = created.json()["id"]
        hidden = client.get(
            f"/api/v1/incidents/{incident_id}",
            headers={"X-User-Id": "other-operator", "X-Role": "operator"},
        )
        hidden_stream = client.get(
            f"/api/v1/incidents/{incident_id}/events",
            headers={"X-User-Id": "other-operator", "X-Role": "operator"},
        )
        owner_visible = client.get(
            f"/api/v1/incidents/{incident_id}",
            headers={"X-User-Id": "owner-operator", "X-Role": "operator"},
        )
        viewer_visible = client.get(
            f"/api/v1/incidents/{incident_id}",
            headers={"X-User-Id": "audit-viewer", "X-Role": "viewer"},
        )
    assert hidden.status_code == 404
    assert hidden_stream.status_code == 404
    assert owner_visible.status_code == 200
    assert viewer_visible.status_code == 200
