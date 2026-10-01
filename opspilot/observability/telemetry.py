from typing import Any

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from opspilot.config import get_settings

_provider: TracerProvider | None = None
_httpx_instrumented = False
_celery_instrumented = False


def configure_tracing() -> TracerProvider | None:
    global _provider
    settings = get_settings()
    if not settings.otel_enabled:
        return None
    if _provider is not None:
        return _provider
    provider = TracerProvider(
        resource=Resource.create({"service.name": settings.service_name})
    )
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
        )
    )
    trace.set_tracer_provider(provider)
    _provider = provider
    return provider


def instrument_fastapi(app: FastAPI) -> None:
    global _httpx_instrumented
    if configure_tracing() is None:
        return
    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls="health,metrics",
    )
    if not _httpx_instrumented:
        HTTPXClientInstrumentor().instrument()
        _httpx_instrumented = True


def instrument_celery() -> None:
    global _celery_instrumented
    if configure_tracing() is None or _celery_instrumented:
        return
    CeleryInstrumentor().instrument()  # type: ignore[no-untyped-call]
    _celery_instrumented = True


def shutdown_tracing(*_: Any) -> None:
    if _provider is not None:
        _provider.shutdown()
