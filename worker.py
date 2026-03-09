from celery import Celery

celery = Celery(
    "vocablens",
    broker="redis://redis:6379/0",
)

@celery.task
def process_ocr(user_id, text, target_lang):
    print("Processing OCR async")


# NEW

from celery import Celery

celery = Celery(
    "vocablens",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/0",
)

celery.autodiscover_tasks(["vocablens.tasks"])