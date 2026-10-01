"""Measure a running OpsPilot API; creates read-only benchmark incidents."""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from time import perf_counter

import httpx
from benchmark_local import percentile


async def run(
    url: str, count: int, concurrency: int, completion_timeout: float
) -> dict[str, object]:
    semaphore = asyncio.Semaphore(concurrency)
    samples: list[dict[str, object]] = []
    async with httpx.AsyncClient(
        base_url=url,
        timeout=httpx.Timeout(completion_timeout, connect=10.0),
        trust_env=False,
        headers={"X-User-Id": "http-benchmark", "X-Role": "operator"},
    ) as client:
        (await client.get("/health")).raise_for_status()

        async def one(index: int) -> None:
            async with semaphore:
                started = perf_counter()
                sample: dict[str, object] = {"index": index, "success": False}
                try:
                    response = await client.post("/api/v1/incidents", json={
                        "title": f"HTTP benchmark {index}",
                        "description": "inventory false alarm is healthy",
                        "severity": "P3", "service_name": "inventory",
                    })
                    sample["accept_ms"] = (perf_counter() - started) * 1000
                    sample["http_status"] = response.status_code
                    if response.is_error:
                        sample["error_detail"] = response.text[:500]
                    response.raise_for_status()
                    incident = response.json()
                    sample["incident_id"] = incident["id"]
                    while incident["status"] not in {
                        "RESOLVED", "FAILED", "NEEDS_HUMAN", "WAITING_APPROVAL", "REJECTED",
                    }:
                        if perf_counter() - started > completion_timeout:
                            raise TimeoutError(
                                f"Diagnosis exceeded {completion_timeout:g} seconds"
                            )
                        await asyncio.sleep(0.1)
                        response = await client.get(f"/api/v1/incidents/{incident['id']}")
                        response.raise_for_status()
                        incident = response.json()
                    sample["state"] = incident["status"]
                    sample["success"] = incident["status"] == "RESOLVED"
                    usage_event = next(
                        (
                            event
                            for event in reversed(incident.get("trace", []))
                            if event.get("event_type") == "model_usage"
                        ),
                        None,
                    )
                    sample["model_usage"] = (
                        usage_event.get("payload") if usage_event else None
                    )
                except (httpx.HTTPError, TimeoutError) as error:
                    sample["error_type"] = type(error).__name__
                sample["completion_ms"] = (perf_counter() - started) * 1000
                samples.append(sample)

        started = perf_counter()
        await asyncio.gather(*(one(i) for i in range(count)))
        duration = perf_counter() - started
    successful = [s for s in samples if s["success"]]
    latencies = [float(str(s["completion_ms"])) for s in successful]
    model_usage = [
        usage
        for sample in successful
        if isinstance((usage := sample.get("model_usage")), dict)
    ]
    model_latencies = [float(str(usage["latency_ms"])) for usage in model_usage]
    return {
        "measured_at": datetime.now(UTC).isoformat(),
        "requests": count, "concurrency": concurrency,
        "completion_timeout_seconds": completion_timeout,
        "successful": len(successful), "error_rate": 1 - len(successful) / count,
        "duration_seconds": duration,
        "successful_per_second": len(successful) / duration,
        "successful_completion_ms": {
            "p50": percentile(latencies, .5), "p95": percentile(latencies, .95),
        } if latencies else None,
        "model_usage": {
            "measured_runs": len(model_usage),
            "input_tokens": sum(int(usage["input_tokens"]) for usage in model_usage),
            "output_tokens": sum(int(usage["output_tokens"]) for usage in model_usage),
            "estimated_cost_usd": sum(
                float(usage["estimated_cost_usd"]) for usage in model_usage
            ),
            "model_latency_ms": {
                "p50": percentile(model_latencies, .5),
                "p95": percentile(model_latencies, .95),
            } if model_latencies else None,
            "pricing_status": (
                "not_measured"
                if not model_usage
                else "priced"
                if any(
                    float(usage["estimated_cost_usd"]) > 0 for usage in model_usage
                )
                else "unpriced"
            ),
        },
        "notes": "Closed-loop; excludes semaphore wait; completion polling interval 100 ms",
        "samples": sorted(samples, key=lambda s: int(str(s["index"]))),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--completion-timeout", type=float, default=240)
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1 or args.completion_timeout <= 0:
        parser.error("requests, concurrency and completion timeout must be positive")
    result = asyncio.run(run(
        args.url, args.requests, args.concurrency, args.completion_timeout
    ))
    print(json.dumps(result, indent=2))
    if result["successful"] != result["requests"]:
        raise SystemExit(1)
