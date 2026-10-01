"""Measure an isolated ASGI/SQLite/mock baseline; never touches the configured DB."""

import argparse
import asyncio
import json
import os
import platform
import statistics
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

import httpx


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


async def measure(requests: int, concurrency: int) -> dict[str, object]:
    # Imports must follow environment setup in main: settings/engine are cached.
    from apps.api.main import app
    from opspilot.db.session import engine
    from opspilot.models import Base

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    semaphore = asyncio.Semaphore(concurrency)
    samples: list[dict[str, object]] = []
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://benchmark") as client:
            await client.get("/health")

            async def request(index: int) -> None:
                async with semaphore:
                    started = perf_counter()
                    response = await client.post(
                        "/api/v1/incidents",
                        headers={"X-User-Id": "benchmark", "X-Role": "operator"},
                        json={
                            "title": f"Benchmark {index}",
                            "description": "inventory false alarm is healthy",
                            "severity": "P3",
                            "service_name": "inventory",
                        },
                    )
                    elapsed = (perf_counter() - started) * 1000
                    body = response.json()
                    samples.append({
                        "index": index,
                        "latency_ms": elapsed,
                        "http_status": response.status_code,
                        "success": response.status_code == 201
                        and body.get("status") == "RESOLVED",
                    })

            started = perf_counter()
            await asyncio.gather(*(request(index) for index in range(requests)))
            duration = perf_counter() - started
    latencies = [float(str(sample["latency_ms"])) for sample in samples]
    errors = sum(not sample["success"] for sample in samples)
    return {
        "requests": requests,
        "concurrency": concurrency,
        "duration_seconds": duration,
        "throughput_requests_per_second": requests / duration,
        "errors": errors,
        "error_rate": errors / requests,
        "latency_ms": {
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "mean": statistics.mean(latencies),
            "max": max(latencies),
        },
        "samples": sorted(samples, key=lambda item: int(str(item["index"]))),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=int, default=40)
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1:
        parser.error("requests and concurrency must be positive")
    os.environ.update({
        "OPSPILOT_MODEL_PROVIDER": "mock",
        "OPSPILOT_TASK_MODE": "inline",
        "OPSPILOT_OTEL_ENABLED": "false",
        "OPSPILOT_LOG_LEVEL": "ERROR",
    })
    with tempfile.TemporaryDirectory(prefix="opspilot-benchmark-") as directory:
        database = Path(directory) / "benchmark.db"
        os.environ["OPSPILOT_DATABASE_URL"] = f"sqlite+aiosqlite:///{database.as_posix()}"
        report = {
            "measured_at": datetime.now(UTC).isoformat(),
            "git_revision": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True
            ).strip(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "scope": "in-process ASGI / isolated SQLite / inline / mock",
            "limitations": [
                "No network, Redis, Celery or container overhead measured",
                "One read-only simulator scenario; no real model inference",
                "Concurrency is closed-loop; latency excludes semaphore queue time",
            ],
            "gpu_memory_bytes": None,
            "process_memory_bytes": None,
            "model_tokens": None,
            "model_cost": None,
            "results": asyncio.run(measure(args.requests, args.concurrency)),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
