import argparse
import json
from pathlib import Path

from opspilot.training.llamafactory import prepare_llamafactory_data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert validated OpsPilot data to LlamaFactory datasets"
    )
    parser.add_argument("--source", type=Path, default=Path("data/generated"))
    parser.add_argument(
        "--output", type=Path, default=Path("data/generated/llamafactory")
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = prepare_llamafactory_data(args.source, args.output)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
