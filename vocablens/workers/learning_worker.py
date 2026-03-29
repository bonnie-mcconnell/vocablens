from __future__ import annotations

import asyncio
from collections.abc import Callable

from vocablens.core.contracts import LEARNING_WORKER_CONCURRENCY
from vocablens.infrastructure.unit_of_work import UnitOfWork


class LearningWorker:
    """Parallel cursor-advancing worker for user learning state."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork], concurrency: int = LEARNING_WORKER_CONCURRENCY):
        self._uow_factory = uow_factory
        self._sem = asyncio.Semaphore(concurrency)

    async def _advance_user_cursor(self, user_id: int) -> None:
        async with self._sem:
            async with self._uow_factory() as uow:
                cursor = await uow.learning_state_cursors.get_or_create(user_id)
                attempts = await uow.learning_sessions.get_attempts_after_id(
                    user_id=user_id,
                    last_attempt_id=cursor.last_processed_attempt_id,
                    limit=500,
                )
                if not attempts:
                    await uow.commit()
                    return

                # Placeholder for skill model update pipeline.
                await uow.learning_state_cursors.update(
                    user_id,
                    last_processed_attempt_id=int(attempts[-1].id),
                )
                await uow.commit()

    async def run_batch(self, user_ids: list[int]) -> None:
        await asyncio.gather(*(self._advance_user_cursor(user_id) for user_id in user_ids))
