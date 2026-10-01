import argparse
import json
from pathlib import Path

from opspilot.evaluation.evaluator import evaluate_predictions
from opspilot.evaluation.io import (
    load_frozen_test_definition,
    load_predictions,
    load_test_dataset,
    sha256_file,
    write_report,
)
from opspilot.evaluation.schemas import EvaluationRunMetadata, ModelGroup
from opspilot.training.generator import DATASET_VERSION


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate one model group on the frozen OpsPilot test split"
    )
    parser.add_argument("--model-group", choices=("base", "sft", "sft_dpo"), required=True)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--model-version", required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument(
        "--dataset", type=Path, default=Path("data/generated/sft_test.jsonl")
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/manifests/opspilot-synthetic-v0.2.json"),
    )
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model_group: ModelGroup = args.model_group
    dataset_hash = sha256_file(args.dataset)
    frozen_version, frozen_hash = load_frozen_test_definition(args.manifest)
    if frozen_version != DATASET_VERSION or frozen_hash != dataset_hash:
        raise ValueError("Evaluation dataset does not match the frozen test manifest")
    metadata = EvaluationRunMetadata(
        model_group=model_group,
        model_name=args.model_name,
        model_version=args.model_version,
        dataset_version=DATASET_VERSION,
        dataset_sha256=dataset_hash,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )
    report = evaluate_predictions(
        load_test_dataset(args.dataset),
        load_predictions(args.predictions),
        metadata,
        actual_dataset_sha256=dataset_hash,
    )
    output = args.output or Path("evaluation/reports/generated") / f"{model_group}.json"
    write_report(report, output)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
