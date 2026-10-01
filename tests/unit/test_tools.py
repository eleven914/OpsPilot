import pytest

from opspilot.tools.gateway import (
    ToolAuthorizationError,
    ToolGateway,
    ToolValidationError,
)


def test_unknown_tool_is_rejected() -> None:
    with pytest.raises(ToolValidationError, match="Unknown or disallowed"):
        ToolGateway().execute("run_shell", {"command": "rm -rf /"})


def test_service_info_has_source() -> None:
    result = ToolGateway().execute("get_service_info", {"service": "gateway"})
    assert result["source_uri"] == "mock://cmdb"


def test_change_tool_cannot_bypass_approval_path() -> None:
    with pytest.raises(ToolAuthorizationError, match="approved execution path"):
        ToolGateway().execute(
            "restart_service",
            {
                "service": "gateway",
                "instance_ids": ["gateway-1"],
                "reason": "CPU saturation requires a safe restart",
            },
        )


def test_approved_change_uses_predefined_sandbox_action() -> None:
    result = ToolGateway().execute_approved_change(
        "rollback_deployment",
        {
            "service": "order",
            "target_version": "2.3.7",
            "reason": "Release caused an error-rate regression",
        },
        approval_id="approval-1",
        approved=True,
        idempotency_key="action-1",
    )
    assert result["status"] == "succeeded"
    assert result["target_version"] == "2.3.7"


def test_false_approval_is_rejected() -> None:
    with pytest.raises(ToolAuthorizationError, match="valid approval"):
        ToolGateway().execute_approved_change(
            "restart_service",
            {
                "service": "gateway",
                "instance_ids": ["gateway-1"],
                "reason": "CPU saturation requires a safe restart",
            },
            approval_id="approval-1",
            approved=False,
            idempotency_key="action-2",
        )
