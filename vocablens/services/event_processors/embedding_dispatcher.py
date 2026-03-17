from vocablens.infrastructure.jobs.base import JobQueue, JobOptions, RetryPolicy


class EmbeddingDispatchProcessor:
    """Enqueues embedding generation for learned words."""

    SUPPORTED = {"word_learned"}

    def __init__(self, jobs: JobQueue):
        self._jobs = jobs

    def supports(self, event_type: str) -> bool:
        return event_type in self.SUPPORTED

    def handle(self, event_type: str, user_id: int, payload: dict) -> None:
        word = payload.get("source_text")
        item_id = payload.get("item_id")
        if not word or not item_id:
            return

        opts = JobOptions(
            idempotency_key=f"embed:{item_id}",
            retry=RetryPolicy(max_attempts=3, backoff_seconds=20),
        )
        self._jobs.enqueue(
            "jobs.generate_embedding",
            {
                "user_id": user_id,
                "word": word,
            },
            opts,
        )
