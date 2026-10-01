import argparse
import json
import subprocess
from pathlib import Path

from opspilot.training.experiment import build_experiment_manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Record immutable metadata before an OpsPilot training run"
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--stage", choices=("sft", "dpo"), required=True)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--hardware", required=True)
    parser.add_argument(
        "--git-commit",
        help="Source commit for exported archives that do not include a .git directory",
    )
    parser.add_argument(
        "--git-dirty",
        action="store_true",
        help="Mark an explicitly supplied source commit as having local modifications",
    )
    parser.add_argument("--seed", type=int, default=20260925)
    parser.add_argument(
        "--dataset-manifest",
        type=Path,
        default=Path("data/manifests/opspilot-synthetic-v0.2.json"),
    )
    parser.add_argument(
        "--conversion-manifest",
        type=Path,
        default=Path("data/generated/llamafactory/conversion_manifest.json"),
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def _git(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *command],
        check=False,
        capture_output=True,
        text=True,
    )


def main() -> None:
    args = parse_args()
    if args.git_commit:
        git_commit = args.git_commit
        git_dirty = args.git_dirty
    else:
        if args.git_dirty:
            raise ValueError("--git-dirty requires --git-commit")
        revision = _git(["rev-parse", "HEAD"])
        if revision.returncode != 0:
            raise RuntimeError(
                "Cannot resolve the current Git commit; exported archives must pass "
                "--git-commit"
            )
        dirty_check = _git(["diff", "--quiet", "HEAD", "--"])
        if dirty_check.returncode not in {0, 1}:
            raise RuntimeError("Cannot determine whether the Git worktree is dirty")
        git_commit = revision.stdout.strip()
        git_dirty = dirty_check.returncode == 1
    manifest = build_experiment_manifest(
        run_id=args.run_id,
        stage=args.stage,
        model_name=args.model_name,
        config_path=args.config,
        dataset_manifest_path=args.dataset_manifest,
        conversion_manifest_path=args.conversion_manifest,
        seed=args.seed,
        hardware=args.hardware,
        git_commit=git_commit,
        git_dirty=git_dirty,
    )
    output = args.output or (
        Path("training/experiments/generated") / f"{args.run_id}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(manifest, ensure_ascii=False, indent=2)
    output.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
