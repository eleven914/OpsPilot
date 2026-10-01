import uuid


class DiagnosisDispatchError(RuntimeError):
    """The diagnosis could not be submitted to the task broker."""


def new_task_id() -> str:
    return str(uuid.uuid4())


def dispatch_diagnosis(incident_id: str, description: str, task_id: str) -> None:
    from opspilot.tasks.celery_app import celery_app

    try:
        with celery_app.connection_for_write(
            connect_timeout=2,
            transport_options={
                "max_retries": 0,
                "socket_connect_timeout": 2,
                "socket_timeout": 2,
            },
        ) as connection:
            celery_app.send_task(
                "opspilot.diagnose_incident",
                args=[incident_id, description],
                task_id=task_id,
                connection=connection,
                ignore_result=True,
                retry=False,
            )
    except Exception as error:
        raise DiagnosisDispatchError("Diagnosis task broker is unavailable") from error
