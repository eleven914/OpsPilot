import json
import logging

from fastapi.testclient import TestClient

from apps.api.main import app
from opspilot.observability.logging import JsonFormatter, bind_request_id, reset_request_id


def test_request_id_and_prometheus_metrics_are_exposed() -> None:
    with TestClient(app) as client:
        health = client.get("/health", headers={"X-Request-ID": "request-test-1"})
        metrics = client.get("/metrics")

    assert health.status_code == 200
    assert health.headers["X-Request-ID"] == "request-test-1"
    assert metrics.status_code == 200
    assert metrics.headers["content-type"].startswith("text/plain")
    assert "opspilot_http_requests_total" in metrics.text
    assert 'route="/health"' in metrics.text


def test_json_logs_include_request_correlation_without_message_parsing() -> None:
    token = bind_request_id("log-request-1")
    try:
        record = logging.LogRecord(
            name="opspilot.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="request completed",
            args=(),
            exc_info=None,
        )
        record.event = "test_event"
        document = json.loads(JsonFormatter().format(record))
    finally:
        reset_request_id(token)

    assert document["message"] == "request completed"
    assert document["request_id"] == "log-request-1"
    assert document["event"] == "test_event"
