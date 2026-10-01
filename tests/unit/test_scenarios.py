import json
from pathlib import Path
from typing import Any

import pytest

from opspilot.agent.orchestrator import MockOrchestrator
from opspilot.tools.gateway import ToolGateway
from opspilot.tools.scenarios import ScenarioDefinition

SCENARIOS_PATH = (
    Path(__file__).resolve().parents[2] / "simulator" / "scenarios" / "scenarios.json"
)
RAW_SCENARIOS: list[dict[str, Any]] = json.loads(
    SCENARIOS_PATH.read_text(encoding="utf-8")
)


def test_exactly_twelve_complete_scenarios_are_defined() -> None:
    scenarios = [ScenarioDefinition.model_validate(item) for item in RAW_SCENARIOS]
    assert len(scenarios) == 12
    assert len({scenario.id for scenario in scenarios}) == 12
    assert {scenario.fault_type for scenario in scenarios} == {
        "CPU 饱和",
        "内存泄漏",
        "线程池耗尽",
        "数据库连接池耗尽",
        "Redis 超时",
        "下游依赖 5xx",
        "慢查询",
        "磁盘空间不足",
        "错误配置",
        "新版本发布回归",
        "单实例异常",
        "告警误报",
    }


@pytest.mark.parametrize(
    ("scenario_id", "service", "keyword"),
    [
        (item["id"], item["service"], item["keywords"][0])
        for item in RAW_SCENARIOS
    ],
)
def test_description_selects_matching_scenario(
    scenario_id: str, service: str, keyword: str
) -> None:
    assert ToolGateway().select_scenario(service, f"alert reports {keyword}") == scenario_id


def test_specific_fault_phrase_wins_when_description_also_names_service() -> None:
    selected = ToolGateway().select_scenario(
        "payment", "payment false alarm recovered without user impact"
    )
    assert selected == "payment_false_alarm"


@pytest.mark.parametrize("scenario", RAW_SCENARIOS, ids=lambda item: item["id"])
def test_every_scenario_produces_consistent_trace(scenario: dict[str, Any]) -> None:
    events = MockOrchestrator().run(
        scenario["service"], f"alert reports {scenario['keywords'][0]}"
    )
    tool_events = [event for event in events if event["event_type"] == "tool_call"]
    assert len(tool_events) == 5
    assert all(
        event["payload"]["arguments"]["scenario_id"] == scenario["id"]
        for event in tool_events
    )
    if scenario["action"] is None:
        final = next(
            event for event in events if event["event_type"] == "final_answer"
        )
        assert final["payload"]["root_causes"] == [scenario["root_cause"]]
        assert events[-1]["payload"]["state"] == "DIAGNOSED"
    else:
        action = next(
            event for event in events if event["event_type"] == "proposed_action"
        )
        assert action["payload"]["tool"] == scenario["action"]["tool"]
        assert events[-1]["payload"]["state"] == "WAITING_APPROVAL"
