import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from opspilot.tools.scenarios import ScenarioDefinition, scenario_version
from opspilot.tools.simulation import verify_simulated_change

SCENARIOS: list[dict[str, Any]] = json.loads(
    (Path(__file__).resolve().parents[2] / "simulator/scenarios/scenarios.json")
    .read_text(encoding="utf-8")
)
ACTION_SCENARIOS = [item for item in SCENARIOS if item["action"] is not None]


@pytest.mark.parametrize("raw", ACTION_SCENARIOS, ids=lambda item: item["id"])
def test_each_sandbox_action_has_independent_passing_fixture(raw: dict[str, Any]) -> None:
    scenario = ScenarioDefinition.model_validate(raw)
    assert scenario.action is not None
    result = verify_simulated_change(
        scenario,
        scenario.action.tool,
        scenario.action.arguments,
        {"status": "succeeded"},
    )
    assert result["status"] == "passed"
    assert result["source_uri"] == f"mock://verification/{scenario.id}"
    assert result["scenario_version"] == scenario_version(scenario)
    assert len(result["checks"]) >= 2
    assert all(check["passed"] for check in result["checks"])


def test_wrong_target_is_inconclusive_even_if_sandbox_executor_succeeded() -> None:
    scenario = ScenarioDefinition.model_validate(ACTION_SCENARIOS[0])
    assert scenario.action is not None
    arguments = {**scenario.action.arguments, "instance_ids": ["gateway-2"]}
    result = verify_simulated_change(
        scenario, scenario.action.tool, arguments, {"status": "succeeded"}
    )
    assert result["status"] == "inconclusive"
    assert result["checks"] == []


def test_bad_post_action_metric_fails_verification() -> None:
    raw = deepcopy(ACTION_SCENARIOS[0])
    raw["verification"]["metrics_after"]["cpu_usage"][-1] = 99
    scenario = ScenarioDefinition.model_validate(raw)
    assert scenario.action is not None
    result = verify_simulated_change(
        scenario, scenario.action.tool, scenario.action.arguments, {"status": "succeeded"}
    )
    assert result["status"] == "failed"
    assert any(not check["passed"] for check in result["checks"])


def test_missing_post_action_log_fails_verification() -> None:
    raw = deepcopy(ACTION_SCENARIOS[0])
    raw["verification"]["logs_after"] = ["WARN instance not ready"]
    scenario = ScenarioDefinition.model_validate(raw)
    assert scenario.action is not None
    result = verify_simulated_change(
        scenario, scenario.action.tool, scenario.action.arguments, {"status": "succeeded"}
    )
    assert result["status"] == "failed"


def test_failed_sandbox_action_fails_verification() -> None:
    scenario = ScenarioDefinition.model_validate(ACTION_SCENARIOS[0])
    assert scenario.action is not None
    result = verify_simulated_change(
        scenario, scenario.action.tool, scenario.action.arguments, {"status": "failed"}
    )
    assert result["status"] == "failed"
