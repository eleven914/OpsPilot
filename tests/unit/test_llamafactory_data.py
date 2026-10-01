import json
from pathlib import Path

from opspilot.training.generator import generate_dataset
from opspilot.training.llamafactory import prepare_llamafactory_data
from opspilot.training.validation import validate_dataset
from opspilot.training.writer import write_dataset


def test_prepare_llamafactory_data_exports_only_train_and_validation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    output = tmp_path / "llamafactory"
    bundle = generate_dataset(sft_variants=1, dpo_variants=1)
    report = validate_dataset(
        bundle, min_sft_count=1, min_dpo_count=1, min_test_sft_count=1
    )
    write_dataset(bundle, report, source)

    manifest = prepare_llamafactory_data(source, output)

    assert manifest["files"]["sft_train.jsonl"]["records"] == 48
    assert manifest["files"]["dpo_validation.jsonl"]["records"] == 10
    assert not (output / "sft_test.jsonl").exists()
    assert not (output / "dpo_test.jsonl").exists()

    sft = json.loads((output / "sft_train.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert [message["role"] for message in sft["messages"]] == [
        "system",
        "user",
        "assistant",
    ]

    dpo = json.loads((output / "dpo_train.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert dpo["conversations"][0]["from"] == "human"
    assert dpo["chosen"]["from"] == "gpt"
    assert dpo["rejected"]["value"] != dpo["chosen"]["value"]

    dataset_info = json.loads((output / "dataset_info.json").read_text(encoding="utf-8"))
    assert dataset_info["opspilot_dpo_train"]["ranking"] is True
    assert set(dataset_info) == {
        "opspilot_sft_train",
        "opspilot_sft_validation",
        "opspilot_dpo_train",
        "opspilot_dpo_validation",
    }
