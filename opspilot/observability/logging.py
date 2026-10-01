import json
import logging
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def bind_request_id(request_id: str) -> Token[str | None]:
    return _request_id.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    _request_id.reset(token)


def current_request_id() -> str | None:
    return _request_id.get()


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        span = trace.get_current_span().get_span_context()
        document: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = current_request_id()
        if request_id:
            document["request_id"] = request_id
        if span.is_valid:
            document["trace_id"] = format(span.trace_id, "032x")
            document["span_id"] = format(span.span_id, "016x")
        for field in (
            "event",
            "http_method",
            "http_route",
            "http_status_code",
            "duration_ms",
            "incident_id",
            "task_id",
            "outcome",
        ):
            value = getattr(record, field, None)
            if value is not None:
                document[field] = value
        if record.exc_info:
            document["exception"] = self.formatException(record.exc_info)
        return json.dumps(document, ensure_ascii=False, default=str)


def configure_logging(level: str, log_format: str) -> None:
    root = logging.getLogger()
    root.setLevel(level)
    handler = next(
        (
            item
            for item in root.handlers
            if getattr(item, "_opspilot_handler", False)
        ),
        None,
    )
    if handler is None:
        handler = logging.StreamHandler()
        handler._opspilot_handler = True  # type: ignore[attr-defined]
        root.handlers.clear()
        root.addHandler(handler)
    formatter: logging.Formatter
    if log_format == "json":
        formatter = JsonFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"
        )
    handler.setFormatter(formatter)
