import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from opspilot.training.generator import DATASET_VERSION, DatasetBundle
from opspilot.training.validation import DatasetValidationReport


def write_dataset(
    bundle: DatasetBundle,
    report: DatasetValidationReport,
    output_dir: Path,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, dict[str, str | int]] = {}
    for kind, records in (("sft", bundle.sft), ("dpo", bundle.dpo)):
        for split in ("train", "validation", "test"):
            selected = [record for record in records if record.split == split]
            path = output_dir / f"{kind}_{split}.jsonl"
            content = "".join(
                f"{record.model_dump_json()}\n" for record in selected
            )
            path.write_text(content, encoding="utf-8")
            files[path.name] = {
                "records": len(selected),
                "sha256": hashlib.sha256(content.encode()).hexdigest(),
            }
    manifest = {
        "dataset_version": DATASET_VERSION,
        "sft_count": report.sft_count,
        "dpo_count": report.dpo_count,
        "sft_by_split": report.sft_by_split,
        "dpo_by_split": report.dpo_by_split,
        "services_by_split": report.services_by_split,
        "templates_by_split": report.templates_by_split,
        "review_status": "rule_validated_not_human_reviewed",
        "eligible_for_final_benchmark": report.eligible_for_final_benchmark,
        "preference_types": dict(
            sorted(Counter(record.preference_type for record in bundle.dpo).items())
        ),
        "files": files,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest
