import os

from celery import Celery  # type: ignore[import-untyped]
from celery.signals import worker_process_shutdown, worker_ready  # type: ignore[import-untyped]
from prometheus_client import CollectorRegistry, multiprocess, start_http_server

from opspilot.config import get_settings
from opspilot.observability.logging import configure_logging
from opspilot.observability.telemetry import instrument_celery

settings = get_settings()
configure_logging(settings.log_level, settings.log_format)
instrument_celery()

celery_app = Celery(
    "opspilot",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["opspilot.tasks.diagnosis"],
)
celery_app.conf.update(
    accept_content=["json"],
    task_serializer="json",
    result_serializer="json",
    task_acks_late=True,
    task_acks_on_failure_or_timeout=False,
    task_reject_on_worker_lost=True,
    task_publish_retry=False,
    broker_connection_timeout=2,
    broker_connection_retry_on_startup=True,
    broker_transport_options={
        "socket_connect_timeout": 2,
        "socket_timeout": 2,
        "visibility_timeout": settings.broker_visibility_timeout_seconds,
    },
    worker_prefetch_multiplier=1,
    worker_hijack_root_logger=False,
    task_soft_time_limit=settings.task_soft_time_limit_seconds,
    task_time_limit=settings.task_time_limit_seconds,
)


@worker_ready.connect  # type: ignore[untyped-decorator]
def start_worker_metrics(**_: object) -> None:
    if settings.metrics_enabled:
        if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
            registry = CollectorRegistry()
            multiprocess.MultiProcessCollector(registry)  # type: ignore[no-untyped-call]
            start_http_server(settings.metrics_port, registry=registry)
        else:
            start_http_server(settings.metrics_port)


@worker_process_shutdown.connect  # type: ignore[untyped-decorator]
def mark_worker_process_dead(pid: int | None = None, **_: object) -> None:
    if pid is not None and os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        multiprocess.mark_process_dead(pid)  # type: ignore[no-untyped-call]
