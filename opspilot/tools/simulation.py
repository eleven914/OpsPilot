"""Independent, deterministic verification of a sandbox action fixture."""

from datetime import UTC, datetime
from typing import Any

from opspilot.tools.scenarios import ScenarioDefinition, scenario_version


def verify_simulated_change(
    scenario: ScenarioDefinition,
    tool_name: str,
    arguments: dict[str, Any],
    action_result: dict[str, Any],
) -> dict[str, Any]:
    """Compare simulated post-action observations with scenario-owned criteria."""
    result: dict[str, Any] = {
        "status": "inconclusive",
        "source_uri": f"mock://verification/{scenario.id}",
        "observed_at": datetime.now(UTC).isoformat(),
        "scenario_id": scenario.id,
        "scenario_version": scenario_version(scenario),
        "checks": [],
        "message": (
            "No real service health check was performed; "
            "sandbox verification is inconclusive"
        ),
    }
    action, fixture = scenario.action, scenario.verification
    if action is None or fixture is None:
        return result
    if tool_name != action.tool or arguments.get("service") != scenario.service:
        result["message"] = "Sandbox action does not match the scenario target"
        return result
    target_keys = ("instance_ids", "target_version")
    if any(
        arguments.get(key) != action.arguments.get(key)
        for key in target_keys
        if key in action.arguments
    ):
        result["message"] = "Sandbox action parameters do not match the scenario target"
        return result
    if action_result.get("status") != "succeeded":
        result["status"] = "failed"
        result["message"] = "Sandbox action failed; no real service health check was performed"
        return result

    checks: list[dict[str, Any]] = []
    for criterion in fixture.checks:
        before = scenario.metrics[criterion.metric][-1]
        after = fixture.metrics_after[criterion.metric][-1]
        passed = (
            after <= criterion.threshold
            if criterion.operator == "le"
            else after >= criterion.threshold
        )
        checks.append(
            {
                "metric": criterion.metric,
                "before": before,
                "after": after,
                "operator": criterion.operator,
                "threshold": criterion.threshold,
                "passed": passed,
            }
        )
    log_passed = any(fixture.required_log in line for line in fixture.logs_after)
    checks.append(
        {
            "log_contains": fixture.required_log,
            "passed": log_passed,
        }
    )
    result["checks"] = checks
    result["status"] = "passed" if all(check["passed"] for check in checks) else "failed"
    result["message"] = (
        "Sandbox observations satisfy the scenario criteria; "
        "no real service health check was performed"
        if result["status"] == "passed"
        else "Sandbox observations did not satisfy the scenario criteria; "
        "no real service health check was performed"
    )
    return result
