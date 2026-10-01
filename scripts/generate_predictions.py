import argparse
import random
import time
from pathlib import Path
from typing import Any

from opspilot.evaluation.generation import (
    append_prediction,
    build_prompt_messages,
    load_resumable_predictions,
)
from opspilot.evaluation.io import load_test_dataset
from opspilot.evaluation.schemas import PredictionRecord


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate leak-free predictions for the frozen OpsPilot test split"
    )
    parser.add_argument("--model-name", default="Qwen/Qwen3-4B-Instruct-2507")
    parser.add_argument("--adapter", type=Path)
    parser.add_argument(
        "--dataset", type=Path, default=Path("data/generated/sft_test.jsonl")
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=20260925)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--resume", action="store_true")
    mode.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if args.max_new_tokens < 1:
        parser.error("--max-new-tokens must be positive")
    if args.temperature < 0:
        parser.error("--temperature cannot be negative")
    return args


def _load_ml_runtime() -> tuple[Any, Any, Any, Any]:
    try:
        import torch  # type: ignore[import-not-found]
        from peft import PeftModel  # type: ignore[import-not-found]
        from transformers import (  # type: ignore[import-not-found]
            AutoModelForCausalLM,
            AutoTokenizer,
            BitsAndBytesConfig,
        )
    except ImportError as error:
        raise RuntimeError(
            "Prediction generation requires torch, transformers, peft and bitsandbytes"
        ) from error
    return torch, PeftModel, AutoModelForCausalLM, (AutoTokenizer, BitsAndBytesConfig)


def main() -> None:
    args = parse_args()
    records = load_test_dataset(args.dataset)
    expected_ids = {record.id for record in records}
    if args.output.exists() and not args.resume and not args.overwrite:
        raise FileExistsError(
            f"Prediction file already exists: {args.output}; use --resume or --overwrite"
        )
    if args.overwrite:
        args.output.unlink(missing_ok=True)
    completed = load_resumable_predictions(
        args.output, expected_sample_ids=expected_ids
    )
    pending = [record for record in records if record.id not in completed]
    print(f"Evaluation samples: {len(records)}")
    print(f"Already completed: {len(completed)}")
    print(f"Pending: {len(pending)}")
    if not pending:
        print("Prediction generation already complete")
        return

    torch, peft_model, auto_model, tokenizer_runtime = _load_ml_runtime()
    auto_tokenizer, quantization_config_type = tokenizer_runtime
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)

    tokenizer_source = str(args.adapter) if args.adapter else args.model_name
    tokenizer = auto_tokenizer.from_pretrained(
        tokenizer_source, trust_remote_code=True
    )
    quantization_config = quantization_config_type(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    model = auto_model.from_pretrained(
        args.model_name,
        trust_remote_code=True,
        device_map="auto",
        dtype=torch.bfloat16,
        quantization_config=quantization_config,
    )
    if args.adapter:
        model = peft_model.from_pretrained(model, str(args.adapter), is_trainable=False)
    model.eval()
    if args.temperature == 0:
        model.generation_config.do_sample = False
        model.generation_config.temperature = None
        model.generation_config.top_p = None
        model.generation_config.top_k = None

    for index, record in enumerate(pending, len(completed) + 1):
        messages = build_prompt_messages(record)
        encoded = tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_tensors="pt",
            return_dict=True,
            enable_thinking=False,
        )
        encoded = {key: value.to(model.device) for key, value in encoded.items()}
        input_tokens = int(encoded["attention_mask"].sum().item())
        generation_args: dict[str, Any] = {
            "max_new_tokens": args.max_new_tokens,
            "do_sample": args.temperature > 0,
            "pad_token_id": tokenizer.pad_token_id,
            "eos_token_id": tokenizer.eos_token_id,
        }
        if args.temperature > 0:
            generation_args["temperature"] = args.temperature
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        started = time.perf_counter()
        with torch.inference_mode():
            generated = model.generate(**encoded, **generation_args)
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        latency_ms = (time.perf_counter() - started) * 1000
        generated_tokens = generated[0, encoded["input_ids"].shape[1] :]
        output = tokenizer.decode(generated_tokens, skip_special_tokens=True).strip()
        prediction = PredictionRecord(
            sample_id=record.id,
            output=output,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=int(generated_tokens.shape[0]),
        )
        append_prediction(args.output, prediction)
        print(
            f"[{index}/{len(records)}] {record.id} "
            f"output_tokens={prediction.output_tokens} latency_ms={latency_ms:.1f}",
            flush=True,
        )
    print(f"Predictions saved to {args.output}")


if __name__ == "__main__":
    main()
