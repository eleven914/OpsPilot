from fastapi.testclient import TestClient

from apps.api.main import app

OPERATOR_HEADERS = {"X-User-Id": "message-operator", "X-Role": "operator"}


def test_operator_message_is_appended_and_starts_new_agent_run() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/incidents",
            headers=OPERATOR_HEADERS,
            json={
                "title": "Payment warning",
                "description": "payment redis timeout was reported",
                "severity": "P2",
                "service_name": "payment",
            },
        )
        assert created.json()["status"] == "DIAGNOSED"
        incident_id = created.json()["id"]

        followed_up = client.post(
            f"/api/v1/incidents/{incident_id}/messages",
            headers=OPERATOR_HEADERS,
            json={
                "content": "payment false alarm recovered with no user impact"
            },
        )
    assert followed_up.status_code == 200
    incident = followed_up.json()
    assert incident["status"] == "DIAGNOSED"
    messages = [
        event for event in incident["trace"] if event["event_type"] == "user_message"
    ]
    assert messages[-1]["payload"]["created_by"] == "message-operator"
    final_answers = [
        event for event in incident["trace"] if event["event_type"] == "final_answer"
    ]
    assert len(final_answers) == 2
    tool_calls = [
        event for event in incident["trace"] if event["event_type"] == "tool_call"
    ]
    assert tool_calls[-1]["payload"]["arguments"]["scenario_id"] == (
        "payment_false_alarm"
    )


def test_message_cannot_start_while_approval_is_pending() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/incidents",
            headers=OPERATOR_HEADERS,
            json={
                "title": "Gateway CPU warning",
                "description": "gateway cpu saturation and latency",
                "severity": "P2",
                "service_name": "gateway",
            },
        )
        blocked = client.post(
            f"/api/v1/incidents/{created.json()['id']}/messages",
            headers=OPERATOR_HEADERS,
            json={"content": "Additional CPU evidence is available"},
        )
    assert blocked.status_code == 409


def test_alertmanager_webhook_is_authenticated_and_idempotent() -> None:
    payload = {
        "status": "firing",
        "receiver": "opspilot",
        "commonLabels": {"service": "gateway", "severity": "critical"},
        "commonAnnotations": {"description": "gateway cpu latency is increasing"},
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "GatewayHighCPU"},
                "annotations": {},
                "startsAt": "2026-09-25T00:00:00Z",
                "fingerprint": "gateway-high-cpu-1",
            }
        ],
    }
    with TestClient(app) as client:
        unauthorized = client.post("/api/v1/webhooks/alertmanager", json=payload)
        first = client.post(
            "/api/v1/webhooks/alertmanager",
            headers={"X-Webhook-Token": "change-me"},
            json=payload,
        )
        duplicate = client.post(
            "/api/v1/webhooks/alertmanager",
            headers={"X-Webhook-Token": "change-me"},
            json=payload,
        )
    assert unauthorized.status_code == 401
    assert first.status_code == 200
    assert len(first.json()) == 1
    assert first.json()[0]["source"] == "alertmanager"
    assert first.json()[0]["severity"] == "P1"
    assert first.json()[0]["status"] == "WAITING_APPROVAL"
    assert duplicate.status_code == 200
    assert duplicate.json()[0]["id"] == first.json()[0]["id"]
    assert len(duplicate.json()[0]["trace"]) == len(first.json()[0]["trace"])


def test_resolved_alert_does_not_create_incident() -> None:
    payload = {
        "status": "resolved",
        "alerts": [
            {
                "status": "resolved",
                "labels": {"service": "payment"},
                "annotations": {},
                "fingerprint": "resolved-payment-1",
            }
        ],
    }
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/webhooks/alertmanager",
            headers={"X-Webhook-Token": "change-me"},
            json=payload,
        )
    assert response.status_code == 200
    assert response.json() == []
