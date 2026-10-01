import logging
import uuid
from time import perf_counter

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from opspilot.config import get_settings
from opspilot.observability.logging import bind_request_id, reset_request_id
from opspilot.observability.metrics import HTTP_DURATION, HTTP_REQUESTS

logger = logging.getLogger(__name__)


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        supplied_request_id = request.headers.get("X-Request-ID", "")
        request_id = (
            supplied_request_id
            if 0 < len(supplied_request_id) <= 128
            else str(uuid.uuid4())
        )
        token = bind_request_id(request_id)
        started = perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            duration = perf_counter() - started
            route = request.scope.get("route")
            route_path = getattr(route, "path", "unmatched")
            if get_settings().metrics_enabled:
                HTTP_REQUESTS.labels(
                    request.method, route_path, str(status_code)
                ).inc()
                HTTP_DURATION.labels(request.method, route_path).observe(duration)
            logger.info(
                "HTTP request completed",
                extra={
                    "event": "http_request",
                    "http_method": request.method,
                    "http_route": route_path,
                    "http_status_code": status_code,
                    "duration_ms": round(duration * 1000, 3),
                },
            )
            reset_request_id(token)
