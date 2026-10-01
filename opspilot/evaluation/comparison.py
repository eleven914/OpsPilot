from opspilot.evaluation.schemas import (
    EvaluationComparison,
    EvaluationReport,
    ModelGroup,
)

REQUIRED_GROUPS: frozenset[ModelGroup] = frozenset({"base", "sft", "sft_dpo"})


def compare_reports(reports: list[EvaluationReport]) -> EvaluationComparison:
    by_group: dict[ModelGroup, EvaluationReport] = {}
    for report in reports:
        group = report.metadata.model_group
        if group in by_group:
            raise ValueError(f"Duplicate evaluation report for model group: {group}")
        by_group[group] = report
    missing = REQUIRED_GROUPS - by_group.keys()
    extra = by_group.keys() - REQUIRED_GROUPS
    if missing or extra:
        raise ValueError(
            f"Comparison requires exactly base, sft, sft_dpo; missing={sorted(missing)}"
        )

    fairness_keys = {
        (
            report.metadata.dataset_version,
            report.metadata.dataset_sha256,
            report.metadata.temperature,
            report.metadata.max_tokens,
        )
        for report in reports
    }
    if len(fairness_keys) != 1:
        raise ValueError(
            "Reports are not comparable: dataset or generation settings differ"
        )
    dataset_version, dataset_sha256, temperature, max_tokens = fairness_keys.pop()
    return EvaluationComparison(
        dataset_version=dataset_version,
        dataset_sha256=dataset_sha256,
        temperature=temperature,
        max_tokens=max_tokens,
        metrics_by_group={group: by_group[group].metrics for group in sorted(by_group)},
        models_by_group={
            group: (
                f"{by_group[group].metadata.model_name}@"
                f"{by_group[group].metadata.model_version}"
            )
            for group in sorted(by_group)
        },
    )
