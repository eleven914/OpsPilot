import time
from typing import Any

import pytest

from opspilot.tools.actions import SandboxActionExecutor
from opspilot.tools.gateway import ToolGateway, ToolValidationError
from opspilot.tools.resilience import (
    CircuitOpenError,
    ToolExecutionError,
    ToolResilience,
    ToolTimeoutError,
    sanitize_output,
)


def test_transient_read_failure_is_retried_once() -> None:
    attempts = 0

    def operation() -> dict[str, Any]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionError("temporary outage")
        return {"status": "ok"}

    result = ToolResilience(max_retries=1).call("query_metrics", operation)
    assert result == {"status": "ok"}
    assert attempts == 2


def test_permanent_adapter_error_is_mapped_without_retry() -> None:
    attempts = 0

    def operation() -> dict[str, Any]:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("internal adapter detail")

    with pytest.raises(ToolExecutionError, match="failed after retries"):
        ToolResilience(max_retries=2).call("query_logs", operation)
    assert attempts == 1


def test_slow_tool_is_mapped_to_timeout() -> None:
    def operation() -> dict[str, Any]:
        time.sleep(0.03)
        return {"status": "too late"}

    with pytest.raises(ToolTimeoutError, match="exceeded"):
        ToolResilience(timeout_seconds=0.005, max_retries=0).call(
            "query_metrics", operation
        )


def test_circuit_opens_and_recovers_after_cooldown() -> None:
    now = [100.0]
    resilience = ToolResilience(
        max_retries=0,
        failure_threshold=2,
        recovery_seconds=10,
        clock=lambda: now[0],
    )

    def failing() -> dict[str, Any]:
        raise ConnectionError("down")

    for _ in range(2):
        with pytest.raises(ToolExecutionError):
            resilience.call("query_logs", failing)
    with pytest.raises(CircuitOpenError, match="Circuit is open"):
        resilience.call("query_logs", lambda: {"status": "not called"})

    now[0] += 11
    assert resilience.call("query_logs", lambda: {"status": "recovered"}) == {
        "status": "recovered"
    }


def test_output_is_recursively_redacted_and_trimmed() -> None:
    result = sanitize_output(
        {
            "authorization": "Bearer visible-secret",
            "nested": {
                "api-key": "key-value",
                "line": "request token=abc123 Authorization: Bearer xyz",
            },
            "long": "x" * 20,
        },
        max_string_length=8,
    )
    assert result["authorization"] == "[REDACTED]"
    assert result["nested"]["api-key"] == "[REDACTED]"
    assert "abc123" not in result["nested"]["line"]
    assert result["long"].endswith("...[TRUNCATED]")


class CountingExecutor(SandboxActionExecutor):
    def __init__(self) -> None:
        self.calls = 0

    def restart_service(
        self, service: str, instance_ids: list[str], reason: str
    ) -> dict[str, Any]:
        self.calls += 1
        return super().restart_service(service, instance_ids, reason)


def test_change_action_is_executed_once_for_same_idempotency_key() -> None:
    executor = CountingExecutor()
    gateway = ToolGateway(action_executor=executor)
    arguments = {
        "service": "gateway",
        "instance_ids": ["gateway-1"],
        "reason": "Restart one saturated instance safely",
    }
    first = gateway.execute_approved_change(
        "restart_service",
        arguments,
        approval_id="approval-1",
        approved=True,
        idempotency_key="same-action",
    )
    second = gateway.execute_approved_change(
        "restart_service",
        arguments,
        approval_id="approval-1",
        approved=True,
        idempotency_key="same-action",
    )
    assert first == second
    assert executor.calls == 1


def test_idempotency_key_cannot_be_reused_for_different_action() -> None:
    gateway = ToolGateway()
    gateway.execute_approved_change(
        "restart_service",
        {
            "service": "gateway",
            "instance_ids": ["gateway-1"],
            "reason": "Restart one saturated instance safely",
        },
        approval_id="approval-1",
        approved=True,
        idempotency_key="conflicting-action",
    )
    with pytest.raises(ToolValidationError, match="different request"):
        gateway.execute_approved_change(
            "restart_service",
            {
                "service": "gateway",
                "instance_ids": ["gateway-2"],
                "reason": "Restart another saturated instance safely",
            },
            approval_id="approval-1",
            approved=True,
            idempotency_key="conflicting-action",
        )
