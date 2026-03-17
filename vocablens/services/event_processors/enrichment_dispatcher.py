from vocablens.infrastructure.jobs.base import JobQueue, JobOptions, RetryPolicy


class EnrichmentDispatchProcessor:
    """Enqueues enrichment jobs for learned words."""

    SUPPORTED = {"word_learned"}

    def __init__(self, jobs: JobQueue):
        self._jobs = jobs

    def supports(self, event_type: str) -> bool:
        return event_type in self.SUPPORTED

    def handle(self, event_type: str, user_id: int, payload: dict) -> None:
        item_id = payload.get("item_id")
        source_text = payload.get("source_text")
        source_lang = payload.get("source_lang")
        target_lang = payload.get("target_lang")

        if not item_id or not source_text:
            return

        opts = JobOptions(
            idempotency_key=f"enrich:{item_id}",
            retry=RetryPolicy(max_attempts=3, backoff_seconds=10),
        )
        self._jobs.enqueue(
            "jobs.enrich_vocabulary",
            {
                "user_id": user_id,
                "item_id": item_id,
                "source_text": source_text,
                "source_lang": source_lang,
                "target_lang": target_lang,
            },
            opts,
        )
