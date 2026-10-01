import argparse
import json
from pathlib import Path

from opspilot.evaluation.comparison import compare_reports
from opspilot.evaluation.io import load_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare fair Base, SFT and SFT+DPO evaluation reports"
    )
    parser.add_argument("reports", nargs=3, type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evaluation/reports/generated/comparison.json"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    comparison = compare_reports([load_report(path) for path in args.reports])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        comparison.model_dump(mode="json"), ensure_ascii=False, indent=2
    )
    args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
