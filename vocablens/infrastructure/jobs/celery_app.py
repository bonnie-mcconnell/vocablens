from celery import Celery
from kombu import Queue

from vocablens.config.settings import settings
from vocablens.infrastructure.observability.metrics import JOB_EVENTS

celery_app = Celery(
    "vocablens",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    imports=(
        "vocablens.infrastructure.jobs.tasks.embedding",
        "vocablens.infrastructure.jobs.tasks.enrichment",
        "vocablens.infrastructure.jobs.tasks.skills",
        "vocablens.infrastructure.jobs.tasks.dead_letter",
    ),
    task_ignore_result=False,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=30,
    task_time_limit=60,
    result_expires=3600,
    task_default_queue="celery",
    task_queues=(
        Queue("celery"),
        Queue(settings.JOB_DEAD_LETTER_QUEUE),
    ),
    task_routes={
        "jobs.dead_letter": {"queue": settings.JOB_DEAD_LETTER_QUEUE},
    },
    task_send_sent_event=True,
    worker_send_task_events=True,
    broker_transport_options={"visibility_timeout": 3600},
)

# Monitoring hooks
from celery import signals  # noqa: E402
from vocablens.infrastructure.logging.logger import get_logger  # noqa: E402

logger = get_logger("celery")


@signals.task_failure.connect
def _task_failure_handler(sender=None, task_id=None, exception=None, einfo=None, **kwargs):
    task_name = sender.name if sender else None
    JOB_EVENTS.labels(task=task_name or "unknown", event="failed").inc()
    logger.error("task_failed", extra={"task": task_name, "task_id": task_id, "error": str(exception)})
    request = kwargs.get("request")
    retries = getattr(request, "retries", 0)
    max_retries = getattr(sender, "max_retries", 0) if sender else 0
    if task_name and retries >= max_retries:
        celery_app.send_task(
            "jobs.dead_letter",
            kwargs={
                "task_name": task_name,
                "task_id": task_id,
                "error": str(exception),
                "traceback_text": str(einfo) if einfo else "",
            },
            queue=settings.JOB_DEAD_LETTER_QUEUE,
        )


@signals.task_success.connect
def _task_success_handler(sender=None, **kwargs):
    task_name = sender.name if sender else None
    JOB_EVENTS.labels(task=task_name or "unknown", event="succeeded").inc()
    logger.info("task_succeeded", extra={"task": task_name})


@signals.task_retry.connect
def _task_retry_handler(sender=None, request=None, reason=None, **kwargs):
    task_name = sender.name if sender else None
    JOB_EVENTS.labels(task=task_name or "unknown", event="retried").inc()
    logger.warning(
        "task_retried",
        extra={
            "task": task_name,
            "task_id": getattr(request, "id", None),
            "retries": getattr(request, "retries", 0),
            "reason": str(reason),
        },
    )


# Ensure task registration in both app and worker imports.
from vocablens.infrastructure.jobs.tasks import dead_letter as _dead_letter  # noqa: F401,E402
from vocablens.infrastructure.jobs.tasks import embedding as _embedding  # noqa: F401,E402
from vocablens.infrastructure.jobs.tasks import enrichment as _enrichment  # noqa: F401,E402
from vocablens.infrastructure.jobs.tasks import skills as _skills  # noqa: F401,E402
