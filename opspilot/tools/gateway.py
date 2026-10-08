import json
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from threading import Lock
from typing import Any, cast

from pydantic import BaseModel, ValidationError

from opspilot.tools.actions import SandboxActionExecutor
from opspilot.tools.resilience import ToolResilience, sanitize_output
from opspilot.tools.scenarios import ScenarioAction, ScenarioDefinition, scenario_version
from opspilot.tools.schemas import (
    LogsQuery,
    MetricsQuery,
    RestartServiceQuery,
    RollbackDeploymentQuery,
    SearchQuery,
    ServiceInfoQuery,
)
from opspilot.tools.simulation import verify_simulated_change


class ToolValidationError(ValueError):
    pass


class ToolAuthorizationError(PermissionError):
    pass


class ToolGateway:
    """Validate and execute allow-listed read-only tools against deterministic scenarios."""

    _schemas: dict[str, type[BaseModel]] = {
        "query_metrics": MetricsQuery,
        "query_logs": LogsQuery,
        "get_service_info": ServiceInfoQuery,
        "search_runbook": SearchQuery,
        "search_incidents": SearchQuery,
        "restart_service": RestartServiceQuery,
        "rollback_deployment": RollbackDeploymentQuery,
    }
    _change_tools = frozenset({"restart_service", "rollback_deployment"})

    def __init__(
        self,
        scenarios_path: Path | None = None,
        action_executor: SandboxActionExecutor | None = None,
        read_executor: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
        resilience: ToolResilience | None = None,
    ) -> None:
        path = scenarios_path or (
            Path(__file__).resolve().parents[2] / "simulator" / "scenarios" / "scenarios.json"
        )
        raw_scenarios = json.loads(path.read_text(encoding="utf-8"))
        self._scenarios = [
            ScenarioDefinition.model_validate(item) for item in raw_scenarios
        ]
        self._action_executor = action_executor or SandboxActionExecutor()
        self._read_executor = read_executor or self._execute_read
        self._resilience = resilience or ToolResilience()
        self._idempotency_cache: dict[str, tuple[str, dict[str, Any]]] = {}
        self._idempotency_lock = Lock()

    @property
    def allowed_tools(self) -> tuple[str, ...]:
        return tuple(self._schemas)

    def close(self) -> None:
        self._resilience.close()

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool_name in self._change_tools:
            raise ToolAuthorizationError(
                f"Change tool {tool_name} requires the approved execution path"
            )
        schema = self._schemas.get(tool_name)
        if schema is None:
            raise ToolValidationError(f"Unknown or disallowed tool: {tool_name}")
        try:
            validated = schema.model_validate(arguments)
        except ValidationError as exc:
            raise ToolValidationError(str(exc)) from exc

        values = validated.model_dump(mode="json")
        result = self._resilience.call(
            tool_name, lambda: self._read_executor(tool_name, values)
        )
        return cast(dict[str, Any], sanitize_output(result))

    def _execute_read(self, tool_name: str, values: dict[str, Any]) -> dict[str, Any]:
        scenario = self._scenario_for(values["service"], values.get("scenario_id"))
        observed_at = datetime.now().astimezone().isoformat()
        payloads: dict[str, Any] = {
            "query_metrics": {"series": scenario.metrics, "source_uri": "mock://prometheus"},
            "query_logs": {"entries": scenario.logs, "source_uri": "mock://loki"},
            "get_service_info": {
                "owner": "platform-team",
                "version": "2.4.1" if values["service"] == "order" else "1.8.0",
                "dependencies": scenario.topology,
                "source_uri": "mock://cmdb",
            },
            "search_runbook": {
                "documents": [scenario.runbook],
                "source_uri": "mock://runbooks",
                "untrusted": True,
            },
            "search_incidents": {
                "incidents": [scenario.previous_incident],
                "source_uri": "mock://incidents",
            },
        }
        return {
            "tool": tool_name,
            "arguments": values,
            "observed_at": observed_at,
            "scenario_version": scenario_version(scenario),
            **payloads[tool_name],
        }

    def execute_approved_change(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        approval_id: str,
        approved: bool,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if tool_name not in self._change_tools:
            raise ToolValidationError(f"Not a change tool: {tool_name}")
        if not approved or not approval_id or not idempotency_key:
            raise ToolAuthorizationError("A valid approval is required")
        schema = self._schemas[tool_name]
        try:
            values = schema.model_validate(arguments).model_dump(mode="json")
        except ValidationError as exc:
            raise ToolValidationError(str(exc)) from exc
        fingerprint = sha256(
            json.dumps(
                {"tool": tool_name, "arguments": values, "approval_id": approval_id},
                sort_keys=True,
            ).encode()
        ).hexdigest()
        with self._idempotency_lock:
            cached = self._idempotency_cache.get(idempotency_key)
            if cached is not None:
                cached_fingerprint, cached_result = cached
                if cached_fingerprint != fingerprint:
                    raise ToolValidationError(
                        "Idempotency key reused for a different request"
                    )
                return deepcopy(cached_result)
            operation = getattr(self._action_executor, tool_name)
            result = cast(
                dict[str, Any],
                sanitize_output(
                    {
                        "tool": tool_name,
                        "approval_id": approval_id,
                        "executed_at": datetime.now().astimezone().isoformat(),
                        **operation(**values),
                    }
                ),
            )
            self._idempotency_cache[idempotency_key] = (
                fingerprint,
                deepcopy(result),
            )
            return result

    def select_scenario(self, service: str, description: str) -> str:
        candidates = [scenario for scenario in self._scenarios if scenario.service == service]
        if not candidates:
            return "unknown"
        normalized = description.casefold()
        selected = max(
            candidates,
            key=lambda scenario: (
                sum(
                    keyword.casefold() in normalized
                    for keyword in scenario.keywords
                ),
                sum(
                    len(keyword)
                    for keyword in scenario.keywords
                    if keyword.casefold() in normalized
                ),
            ),
        )
        return selected.id

    def root_cause_for(self, service: str, scenario_id: str | None = None) -> str:
        return self._scenario_for(service, scenario_id).root_cause

    def recommended_steps_for(
        self, service: str, scenario_id: str | None = None
    ) -> list[str]:
        return self._scenario_for(service, scenario_id).recommended_steps

    def action_for(
        self, service: str, scenario_id: str | None = None
    ) -> ScenarioAction | None:
        return self._scenario_for(service, scenario_id).action

    def verify_simulated_change(
        self,
        service: str,
        evidence_version: str,
        tool_name: str,
        arguments: dict[str, Any],
        action_result: dict[str, Any],
    ) -> dict[str, Any]:
        scenario = self.scenario_for_version(service, evidence_version)
        if scenario is None:
            raise ToolValidationError("Approved scenario version is no longer available")
        return verify_simulated_change(scenario, tool_name, arguments, action_result)

    def scenario_for_version(
        self, service: str, evidence_version: str
    ) -> ScenarioDefinition | None:
        return next(
            (
                scenario
                for scenario in self._scenarios
                if scenario.service == service and scenario_version(scenario) == evidence_version
            ),
            None,
        )

    def _scenario_for(
        self, service: str, scenario_id: str | None = None
    ) -> ScenarioDefinition:
        for scenario in self._scenarios:
            if scenario.service == service and (
                scenario_id is None or scenario.id == scenario_id
            ):
                return scenario
        return ScenarioDefinition(
            id="unknown",
            fault_type="未知故障",
            service=service,
            keywords=["unknown"],
            root_cause="信息不足，需人工进一步排查",
            metrics={},
            logs=[],
            topology=[],
            runbook="没有匹配的 Runbook。",
            previous_incident="没有匹配的历史事件。",
            recommended_steps=["转交人工进一步排查"],
            forbidden_actions=["不得执行未经证据支持的变更"],
            alternatives=["扩大只读证据采集时间窗"],
        )
