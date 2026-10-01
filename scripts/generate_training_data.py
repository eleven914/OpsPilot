import argparse
import json
from pathlib import Path

from opspilot.training.generator import generate_dataset
from opspilot.training.validation import validate_dataset
from opspilot.training.writer import write_dataset


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate reproducible OpsPilot data")
    parser.add_argument("--output", type=Path, default=Path("data/generated"))
    parser.add_argument("--sft-variants", type=int, default=112)
    parser.add_argument("--dpo-variants", type=int, default=34)
    parser.add_argument("--seed", type=int, default=20260925)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    bundle = generate_dataset(
        sft_variants=args.sft_variants,
        dpo_variants=args.dpo_variants,
        seed=args.seed,
    )
    report = validate_dataset(bundle)
    manifest = write_dataset(bundle, report, args.output)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
