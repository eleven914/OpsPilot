import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass

from opspilot.agent.parser import ModelOutputError, parse_model_decision
from opspilot.agent.policies import PolicyViolationError, SafetyGuard
from opspilot.agent.schemas import FinalAnswerDecision, ProposedActionDecision
from opspilot.training.generator import DatasetBundle


class DatasetValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DatasetValidationReport:
    sft_count: int
    dpo_count: int
    sft_by_split: dict[str, int]
    dpo_by_split: dict[str, int]
    services_by_split: dict[str, list[str]]
    templates_by_split: dict[str, list[str]]
    duplicate_count: int
    human_reviewed: bool
    eligible_for_final_benchmark: bool


def validate_dataset(
    bundle: DatasetBundle,
    *,
    min_sft_count: int = 8_000,
    min_dpo_count: int = 2_000,
    min_test_sft_count: int = 500,
) -> DatasetValidationReport:
    errors: list[str] = []
    if len(bundle.sft) < min_sft_count:
        errors.append(f"SFT count {len(bundle.sft)} is below {min_sft_count}")
    if len(bundle.dpo) < min_dpo_count:
        errors.append(f"DPO count {len(bundle.dpo)} is below {min_dpo_count}")

    sft_ids = [record.id for record in bundle.sft]
    dpo_ids = [record.id for record in bundle.dpo]
    if len(sft_ids) != len(set(sft_ids)):
        errors.append("SFT record IDs are not unique")
    if len(dpo_ids) != len(set(dpo_ids)):
        errors.append("DPO record IDs are not unique")
    if set(sft_ids) & set(dpo_ids):
        errors.append("SFT and DPO record IDs overlap")

    duplicate_count = _duplicate_count(bundle)
    if duplicate_count:
        errors.append(f"Dataset contains {duplicate_count} duplicate learning examples")

    services_by_split = _group_values(bundle, "service")
    templates_by_split = _group_values(bundle, "template_id")
    _assert_disjoint(services_by_split, "service", errors)
    _assert_disjoint(templates_by_split, "template", errors)

    sft_by_split = {
        str(split): count
        for split, count in Counter(record.split for record in bundle.sft).items()
    }
    dpo_by_split = {
        str(split): count
        for split, count in Counter(record.split for record in bundle.dpo).items()
    }
    if sft_by_split.get("test", 0) < min_test_sft_count:
        errors.append(
            f"Test SFT count {sft_by_split.get('test', 0)} is below "
            f"{min_test_sft_count}"
        )

    _validate_dpo_preferences(bundle, errors)
    _validate_observable_sft_contract(bundle, errors)
    if errors:
        raise DatasetValidationError("; ".join(errors))
    return DatasetValidationReport(
        sft_count=len(bundle.sft),
        dpo_count=len(bundle.dpo),
        sft_by_split=sft_by_split,
        dpo_by_split=dpo_by_split,
        services_by_split=services_by_split,
        templates_by_split=templates_by_split,
        duplicate_count=duplicate_count,
        human_reviewed=False,
        eligible_for_final_benchmark=False,
    )


def _duplicate_count(bundle: DatasetBundle) -> int:
    fingerprints: list[str] = []
    for sft_record in bundle.sft:
        learning_content = [
            message.model_dump() for message in sft_record.messages
        ]
        fingerprints.append(_fingerprint(learning_content))
    for dpo_record in bundle.dpo:
        preference_content = {
            "prompt": [message.model_dump() for message in dpo_record.prompt],
            "chosen": dpo_record.chosen,
            "rejected": dpo_record.rejected,
            "preference_type": dpo_record.preference_type,
        }
        fingerprints.append(_fingerprint(preference_content))
    counts = Counter(fingerprints)
    return sum(count - 1 for count in counts.values() if count > 1)


def _fingerprint(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _group_values(bundle: DatasetBundle, attribute: str) -> dict[str, list[str]]:
    grouped: defaultdict[str, set[str]] = defaultdict(set)
    for sft_record in bundle.sft:
        grouped[sft_record.split].add(str(getattr(sft_record, attribute)))
    for dpo_record in bundle.dpo:
        grouped[dpo_record.split].add(str(getattr(dpo_record, attribute)))
    return {split: sorted(values) for split, values in sorted(grouped.items())}


def _assert_disjoint(
    grouped: dict[str, list[str]], label: str, errors: list[str]
) -> None:
    splits = sorted(grouped)
    for index, left in enumerate(splits):
        for right in splits[index + 1 :]:
            overlap = set(grouped[left]) & set(grouped[right])
            if overlap:
                errors.append(
                    f"{label.title()} leakage between {left} and {right}: "
                    f"{sorted(overlap)}"
                )


def _validate_dpo_preferences(
    bundle: DatasetBundle, errors: list[str]
) -> None:
    guard = SafetyGuard()
    for record in bundle.dpo:
        prompt_context = json.loads(record.prompt[-1].content)
        evidence_ids = set(prompt_context["evidence_ids"])
        chosen = parse_model_decision(record.chosen)
        if isinstance(chosen, ProposedActionDecision):
            guard.validate_action(chosen, evidence_ids)
        elif isinstance(chosen, FinalAnswerDecision):
            guard.validate_final_answer(chosen, evidence_ids)

        try:
            rejected = parse_model_decision(record.rejected)
            if isinstance(rejected, ProposedActionDecision):
                guard.validate_action(rejected, evidence_ids)
            elif isinstance(rejected, FinalAnswerDecision):
                guard.validate_final_answer(rejected, evidence_ids)
        except (ModelOutputError, PolicyViolationError):
            continue
        errors.append(f"Rejected DPO output unexpectedly passed safety: {record.id}")


def _validate_observable_sft_contract(
    bundle: DatasetBundle, errors: list[str]
) -> None:
    for record in bundle.sft:
        context = json.loads(record.messages[-2].content)
        expected = record.expected_decision
        if record.task_type == "single_tool":
            tool = expected["tool"]
            defaults = context["query_defaults"]
            common = {"service": context["service"]}
            visible_arguments: dict[str, object]
            if tool == "query_metrics":
                visible_arguments = {
                    **common,
                    "start": context["observation_start"],
                    "end": context["observation_end"],
                    "metric": defaults["metric"],
                }
            elif tool == "query_logs":
                visible_arguments = {
                    **common,
                    "start": context["observation_start"],
                    "end": context["observation_end"],
                    "keywords": context["search_terms"],
                    "limit": defaults["log_limit"],
                }
            elif tool == "get_service_info":
                visible_arguments = common
            else:
                visible_arguments = {
                    **common,
                    "query": context["incident"],
                    "top_k": defaults["top_k"],
                }
            if expected["arguments"] != visible_arguments:
                errors.append(f"Hidden tool arguments in SFT record: {record.id}")
            continue

        if expected["evidence_ids"] != context["evidence_ids"]:
            errors.append(f"Hidden evidence IDs in terminal record: {record.id}")
        if expected["type"] == "proposed_action":
            candidate = context["candidate_action"]
            if (
                candidate is None
                or expected["tool"] != candidate["tool"]
                or expected["arguments"] != candidate["arguments"]
                or expected["risk"] != candidate["risk"]
            ):
                errors.append(f"Hidden proposed action in terminal record: {record.id}")
        elif (
            expected["root_causes"] != [context["root_cause_candidate"]]
            or expected["insufficient_information"]
            != context["insufficient_information"]
        ):
            errors.append(f"Hidden diagnosis in terminal record: {record.id}")
