import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from apps.api.routes.approvals import router as approvals_router
from apps.api.routes.incidents import router as incidents_router
from apps.api.routes.webhooks import router as webhooks_router
from opspilot.approvals.service import expire_pending_approvals
from opspilot.config import get_settings
from opspilot.db.session import SessionFactory, engine
from opspilot.observability.logging import configure_logging, current_request_id
from opspilot.observability.middleware import ObservabilityMiddleware
from opspilot.observability.telemetry import instrument_fastapi, shutdown_tracing

logger = logging.getLogger(__name__)


async def _approval_expiry_loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            async with SessionFactory() as session:
                expired = await expire_pending_approvals(session)
                if expired:
                    await session.commit()
        except Exception:
            logger.exception("Approval expiry scan failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=30)
        except TimeoutError:
            pass


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    stop = asyncio.Event()
    expiry_task = asyncio.create_task(_approval_expiry_loop(stop))
    yield
    stop.set()
    await expiry_task
    await engine.dispose()
    shutdown_tracing()


app = FastAPI(title="OpsPilot API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=[
        "Content-Type",
        "Authorization",
        "X-Request-ID",
        "X-User-Id",
        "X-Role",
    ],
    expose_headers=["X-Request-ID"],
)
app.add_middleware(ObservabilityMiddleware)
app.include_router(incidents_router, prefix="/api/v1")
app.include_router(approvals_router, prefix="/api/v1")
app.include_router(webhooks_router, prefix="/api/v1")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    if not get_settings().metrics_enabled:
        return Response(status_code=404)
    return Response(
        content=generate_latest(), headers={"Content-Type": CONTENT_TYPE_LATEST}
    )


@app.exception_handler(Exception)
async def unhandled_exception(_: Request, exc: Exception) -> JSONResponse:
    request_id = current_request_id() or str(uuid.uuid4())
    return JSONResponse(
        status_code=500,
        content={
            "code": "INTERNAL_ERROR",
            "message": "Unexpected server error",
            "request_id": request_id,
            "details": {"type": type(exc).__name__},
        },
    )


instrument_fastapi(app)
