import hashlib
import json
from pathlib import Path
from typing import Any

from opspilot.training.schemas import DPORecord, SFTRecord


def prepare_llamafactory_data(source_dir: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, dict[str, str | int]] = {}
    for split in ("train", "validation"):
        sft_source = source_dir / f"sft_{split}.jsonl"
        dpo_source = source_dir / f"dpo_{split}.jsonl"
        sft_records = _load_records(sft_source, SFTRecord)
        dpo_records = _load_records(dpo_source, DPORecord)
        files[f"sft_{split}.jsonl"] = _write_jsonl(
            output_dir / f"sft_{split}.jsonl",
            [
                {
                    "messages": [
                        message.model_dump() for message in item.messages
                    ]
                }
                for item in sft_records
            ],
        )
        files[f"dpo_{split}.jsonl"] = _write_jsonl(
            output_dir / f"dpo_{split}.jsonl",
            [_convert_dpo(item) for item in dpo_records],
        )

    dataset_info = _dataset_info()
    info_content = json.dumps(dataset_info, ensure_ascii=False, indent=2) + "\n"
    (output_dir / "dataset_info.json").write_text(info_content, encoding="utf-8")
    manifest = {
        "format": "llamafactory-sharegpt-v1",
        "source_dir": source_dir.as_posix(),
        "files": files,
        "dataset_info_sha256": hashlib.sha256(info_content.encode()).hexdigest(),
    }
    (output_dir / "conversion_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def _convert_dpo(record: DPORecord) -> dict[str, Any]:
    system_messages = [item.content for item in record.prompt if item.role == "system"]
    conversations = []
    role_map = {"user": "human", "assistant": "gpt"}
    for message in record.prompt:
        if message.role == "system":
            continue
        conversations.append({"from": role_map[message.role], "value": message.content})
    return {
        "conversations": conversations,
        "system": "\n".join(system_messages),
        "chosen": {"from": "gpt", "value": record.chosen},
        "rejected": {"from": "gpt", "value": record.rejected},
    }


def _load_records(path: Path, model: type[SFTRecord] | type[DPORecord]) -> list[Any]:
    records = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            records.append(model.model_validate_json(line))
        except ValueError as error:
            raise ValueError(f"Invalid source record at {path}:{line_number}") from error
    if not records:
        raise ValueError(f"Source dataset is empty: {path}")
    return records


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> dict[str, str | int]:
    content = "".join(
        json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        for record in records
    )
    path.write_text(content, encoding="utf-8")
    return {
        "records": len(records),
        "sha256": hashlib.sha256(content.encode()).hexdigest(),
    }


def _dataset_info() -> dict[str, Any]:
    openai_tags = {
        "role_tag": "role",
        "content_tag": "content",
        "user_tag": "user",
        "assistant_tag": "assistant",
        "system_tag": "system",
    }
    sharegpt_tags = {
        "role_tag": "from",
        "content_tag": "value",
        "user_tag": "human",
        "assistant_tag": "gpt",
        "system_tag": "system",
    }
    result: dict[str, Any] = {}
    for split in ("train", "validation"):
        result[f"opspilot_sft_{split}"] = {
            "file_name": f"sft_{split}.jsonl",
            "formatting": "sharegpt",
            "columns": {"messages": "messages"},
            "tags": openai_tags,
        }
        result[f"opspilot_dpo_{split}"] = {
            "file_name": f"dpo_{split}.jsonl",
            "formatting": "sharegpt",
            "ranking": True,
            "columns": {
                "messages": "conversations",
                "system": "system",
                "chosen": "chosen",
                "rejected": "rejected",
            },
            "tags": sharegpt_tags,
        }
    return result
