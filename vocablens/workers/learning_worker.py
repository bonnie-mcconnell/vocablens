from __future__ import annotations

import asyncio
from collections.abc import Callable

from vocablens.core.contracts import (
    LEARNING_WORKER_BACKLOG_LIMIT,
    LEARNING_WORKER_CONCURRENCY,
    LEARNING_WORKER_MAX_LAG_SECONDS,
    LEARNING_WORKER_MAX_USERS_PER_TICK,
)
from vocablens.core.runtime_metrics import runtime_metrics
from vocablens.core.time import utc_now
from vocablens.infrastructure.unit_of_work import UnitOfWork


class LearningWorker:
    """Parallel cursor-advancing worker for user learning state."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork], concurrency: int = LEARNING_WORKER_CONCURRENCY):
        self._uow_factory = uow_factory
        self._sem = asyncio.Semaphore(concurrency)
        self._failure_threshold = 3
        self._quarantine_seconds = 300

    async def _advance_user_cursor(self, user_id: int) -> None:
        async with self._sem:
            async with self._uow_factory() as uow:
                if await uow.learning_worker_failures.is_quarantined(user_id):
                    await uow.commit()
                    return
                cursor = await uow.learning_state_cursors.get_or_create(user_id)
                try:
                    attempts = await uow.learning_sessions.get_attempts_after_id(
                        user_id=user_id,
                        last_attempt_id=cursor.last_processed_attempt_id,
                        limit=500,
                    )
                    if attempts and (utc_now() - attempts[0].created_at).total_seconds() > float(LEARNING_WORKER_MAX_LAG_SECONDS):
                        attempts = await uow.learning_sessions.get_attempts_after_id(
                            user_id=user_id,
                            last_attempt_id=cursor.last_processed_attempt_id,
                            limit=LEARNING_WORKER_BACKLOG_LIMIT,
                        )
                    if not attempts:
                        await uow.learning_worker_failures.clear(user_id)
                        await uow.commit()
                        return

                    # Placeholder for skill model update pipeline.
                    await uow.learning_state_cursors.update(
                        user_id,
                        last_processed_attempt_id=int(attempts[-1].id),
                    )
                    await uow.learning_worker_failures.clear(user_id)
                    await uow.commit()
                    runtime_metrics().observe_worker_throughput(component="learning_worker", count=len(attempts))
                    runtime_metrics().observe_queue_lag_ms(
                        component="learning_worker",
                        value_ms=max(0.0, (utc_now() - attempts[0].created_at).total_seconds() * 1000),
                    )
                except Exception as exc:
                    result = await uow.learning_worker_failures.record_failure(
                        user_id=user_id,
                        error=str(exc),
                        threshold=self._failure_threshold,
                        quarantine_seconds=self._quarantine_seconds,
                    )
                    await uow.commit()
                    if result.get("quarantined_until") is not None:
                        runtime_metrics().increment_dlq(component="learning_worker_quarantine", count=1)

    async def run_batch(self, user_ids: list[int]) -> None:
        batch = [int(user_id) for user_id in user_ids[:LEARNING_WORKER_MAX_USERS_PER_TICK]]
        await asyncio.gather(*(self._advance_user_cursor(user_id) for user_id in batch))
