import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from opspilot.agent.prompt import READ_TOOLS, SYSTEM_POLICY
from opspilot.agent.schemas import (
    FinalAnswerDecision,
    ProposedActionDecision,
    ToolCallDecision,
)
from opspilot.tools.scenarios import ScenarioDefinition
from opspilot.training.schemas import (
    ChatMessage,
    DatasetMetadata,
    DatasetSplit,
    DPORecord,
    PreferenceType,
    SFTRecord,
)
from opspilot.training.split import build_service_split

DATASET_VERSION = "opspilot-synthetic-v0.2"


@dataclass(frozen=True, slots=True)
class DatasetBundle:
    sft: list[SFTRecord]
    dpo: list[DPORecord]


def load_scenarios(path: Path | None = None) -> list[ScenarioDefinition]:
    source = path or (
        Path(__file__).resolve().parents[2]
        / "simulator"
        / "scenarios"
        / "scenarios.json"
    )
    raw: list[dict[str, Any]] = json.loads(source.read_text(encoding="utf-8"))
    return [ScenarioDefinition.model_validate(item) for item in raw]


def generate_dataset(
    *,
    sft_variants: int = 112,
    dpo_variants: int = 34,
    seed: int = 20260925,
    scenarios_path: Path | None = None,
) -> DatasetBundle:
    if sft_variants <= 0 or dpo_variants <= 0:
        raise ValueError("Variant counts must be positive")
    scenarios = load_scenarios(scenarios_path)
    split_by_service = build_service_split(scenario.service for scenario in scenarios)
    sft: list[SFTRecord] = []
    dpo: list[DPORecord] = []
    for scenario in scenarios:
        split = split_by_service[scenario.service]
        for variant in range(sft_variants):
            sft.extend(_sft_records(scenario, split, variant, seed))
        for variant in range(dpo_variants):
            dpo.extend(_dpo_records(scenario, split, variant, seed))
    return DatasetBundle(sft=sft, dpo=dpo)


def _sft_records(
    scenario: ScenarioDefinition, split: DatasetSplit, variant: int, seed: int
) -> list[SFTRecord]:
    metadata = DatasetMetadata(seed=seed, variant=variant, dataset_version=DATASET_VERSION)
    description = _description(scenario, variant)
    records: list[SFTRecord] = []
    for tool_index, tool_name in enumerate(READ_TOOLS):
        decision = ToolCallDecision(
            tool=tool_name,
            arguments=_tool_arguments(tool_name, scenario, description, variant),
            reason=f"Collect {tool_name} evidence before making a diagnosis",
        )
        records.append(
            SFTRecord(
                id=f"sft:{scenario.id}:{variant:04d}:{tool_name}",
                split=split,
                task_type="single_tool",
                template_id=scenario.id,
                service=scenario.service,
                messages=[
                    ChatMessage(role="system", content=SYSTEM_POLICY),
                    ChatMessage(
                        role="user",
                        content=_user_context(
                            scenario, description, variant, step=tool_index
                        ),
                    ),
                    ChatMessage(role="assistant", content=decision.model_dump_json()),
                ],
                expected_decision=decision.model_dump(mode="json"),
                metadata=metadata,
            )
        )
    evidence_ids = _evidence_ids(scenario, variant)
    terminal = _terminal_decision(scenario, evidence_ids)
    records.append(
        SFTRecord(
            id=f"sft:{scenario.id}:{variant:04d}:terminal",
            split=split,
            task_type="multi_step",
            template_id=scenario.id,
            service=scenario.service,
            messages=[
                ChatMessage(role="system", content=SYSTEM_POLICY),
                ChatMessage(
                    role="user",
                    content=_terminal_context(
                        scenario, description, evidence_ids
                    ),
                ),
                ChatMessage(role="assistant", content=terminal.model_dump_json()),
            ],
            expected_decision=terminal.model_dump(mode="json"),
            metadata=metadata,
        )
    )
    return records


def _dpo_records(
    scenario: ScenarioDefinition, split: DatasetSplit, variant: int, seed: int
) -> list[DPORecord]:
    metadata = DatasetMetadata(seed=seed, variant=variant, dataset_version=DATASET_VERSION)
    description = _description(scenario, variant)
    evidence_ids = _evidence_ids(scenario, variant)
    chosen_decision = _terminal_decision(scenario, evidence_ids)
    chosen = chosen_decision.model_dump_json()
    prompt = [
        ChatMessage(role="system", content=SYSTEM_POLICY),
        ChatMessage(
            role="user",
            content=_terminal_context(scenario, description, evidence_ids),
        ),
    ]
    rejected_by_type = _rejected_outputs(scenario, evidence_ids)
    return [
        DPORecord(
            id=f"dpo:{scenario.id}:{variant:04d}:{preference_type}",
            split=split,
            preference_type=preference_type,
            template_id=scenario.id,
            service=scenario.service,
            prompt=prompt,
            chosen=chosen,
            rejected=rejected,
            metadata=metadata,
        )
        for preference_type, rejected in rejected_by_type.items()
    ]


def _terminal_decision(
    scenario: ScenarioDefinition, evidence_ids: list[str]
) -> ProposedActionDecision | FinalAnswerDecision:
    if scenario.action is not None:
        return ProposedActionDecision(
            tool=scenario.action.tool,
            arguments=scenario.action.arguments,
            risk=scenario.action.risk,
            evidence_ids=evidence_ids,
            rollback_plan=scenario.action.rollback_plan,
        )
    return FinalAnswerDecision(
        summary=f"Evidence supports the {scenario.fault_type} diagnosis",
        root_causes=[scenario.root_cause],
        confidence=0.86,
        evidence_ids=evidence_ids,
        next_steps=scenario.recommended_steps,
    )


def _tool_arguments(
    tool_name: str,
    scenario: ScenarioDefinition,
    description: str,
    variant: int,
) -> dict[str, Any]:
    start, end = _observation_window(variant)
    common = {"service": scenario.service}
    if tool_name == "query_metrics":
        return {**common, "metric": "health", "start": start, "end": end}
    if tool_name == "query_logs":
        return {
            **common,
            "keywords": scenario.keywords[:5],
            "start": start,
            "end": end,
            "limit": 50,
        }
    if tool_name == "get_service_info":
        return common
    return {**common, "query": description, "top_k": 3}


def _user_context(
    scenario: ScenarioDefinition, description: str, variant: int, step: int
) -> str:
    start, end = _observation_window(variant)
    return json.dumps(
        {
            "incident": description,
            "service": scenario.service,
            "state": "COLLECTING_EVIDENCE",
            "next_evidence_step": step + 1,
            "sample_variant": variant,
            "observation_start": start.isoformat().replace("+00:00", "Z"),
            "observation_end": end.isoformat().replace("+00:00", "Z"),
            "search_terms": scenario.keywords[:5],
            "query_defaults": {
                "metric": "health",
                "log_level": None,
                "log_limit": 50,
                "top_k": 3,
            },
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _terminal_context(
    scenario: ScenarioDefinition, description: str, evidence_ids: list[str]
) -> str:
    candidate_action: dict[str, object] | None = None
    if scenario.action is not None:
        candidate_action = {
            "tool": scenario.action.tool,
            "arguments": scenario.action.arguments,
            "risk": scenario.action.risk,
            "rollback_plan": scenario.action.rollback_plan,
        }
    return json.dumps(
        {
            "incident": description,
            "state": "DIAGNOSING",
            "evidence_ids": evidence_ids,
            "root_cause_candidate": scenario.root_cause,
            "recommended_steps": scenario.recommended_steps,
            "candidate_action": candidate_action,
            "recommended_confidence": 0.86,
            "insufficient_information": False,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _observation_window(variant: int) -> tuple[datetime, datetime]:
    end = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=variant)
    return end - timedelta(minutes=15), end


def _description(scenario: ScenarioDefinition, variant: int) -> str:
    keyword = scenario.keywords[variant % len(scenario.keywords)]
    return (
        f"{scenario.service} alert indicates {keyword}; fault type may be "
        f"{scenario.fault_type}; observation window variant {variant:04d}"
    )


def _evidence_ids(scenario: ScenarioDefinition, variant: int) -> list[str]:
    return [
        f"evidence:{scenario.id}:{variant:04d}:{index}" for index in range(1, 6)
    ]


def _rejected_outputs(
    scenario: ScenarioDefinition, evidence_ids: list[str]
) -> dict[PreferenceType, str]:
    return {
        "correct_tool": json.dumps(
            {
                "type": "tool_call",
                "tool": "run_shell",
                "arguments": {"command": "inspect production"},
                "reason": "Use an unavailable tool instead of the approved schema",
            }
        ),
        "valid_arguments": json.dumps(
            {
                "type": "tool_call",
                "tool": "query_metrics",
                "arguments": {"service": scenario.service},
                "reason": "Call metrics with required arguments missing",
            }
        ),
        "evidence_grounded": FinalAnswerDecision(
            summary="The incident has definitely been diagnosed without evidence",
            root_causes=[scenario.root_cause],
            confidence=0.99,
            evidence_ids=[],
            next_steps=scenario.recommended_steps,
        ).model_dump_json(),
        "approval_required": json.dumps(
            {
                "type": "tool_call",
                "tool": "restart_service",
                "arguments": {"service": scenario.service},
                "reason": "Execute a change directly without approval",
            }
        ),
        "honest_uncertainty": FinalAnswerDecision(
            summary="A root cause is asserted using an invented evidence reference",
            root_causes=[scenario.root_cause],
            confidence=0.98,
            evidence_ids=[f"invented:{evidence_ids[0]}"],
            next_steps=["Execute immediately"],
        ).model_dump_json(),
    }
