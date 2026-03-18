from vocablens.infrastructure.jobs.celery_app import celery_app
from vocablens.config.settings import settings
from vocablens.infrastructure.logging.logger import get_logger
from vocablens.infrastructure.observability.metrics import JOB_EVENTS


logger = get_logger("jobs.dead_letter")


@celery_app.task(name="jobs.dead_letter", queue=settings.JOB_DEAD_LETTER_QUEUE)
def dead_letter_task(task_name: str, task_id: str | None, error: str, traceback_text: str = ""):
    JOB_EVENTS.labels(task=task_name or "unknown", event="dead_lettered").inc()
    logger.error(
        "task_dead_lettered",
        extra={
            "task": task_name,
            "task_id": task_id,
            "error": error,
            "traceback": traceback_text[:2000],
        },
    )
