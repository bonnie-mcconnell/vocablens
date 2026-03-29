from __future__ import annotations

from collections.abc import Callable

from vocablens.core.contracts import HOT_QUEUE_MAX
from vocablens.core.errors import HotUserBackpressureError
from vocablens.infrastructure.unit_of_work import UnitOfWork


class HotUserService:
    """Durable enqueue path for hot-user write mode."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork], max_queue: int = HOT_QUEUE_MAX):
        self._uow_factory = uow_factory
        self._max_queue = max_queue

    async def enqueue(self, *, user_id: int, payload: dict, idempotency_key: str) -> dict[str, str]:
        async with self._uow_factory() as uow:
            depth = await uow.mutation_queue.count(user_id)
            if depth >= self._max_queue:
                raise HotUserBackpressureError("hot_user_backpressure")

            await uow.mutation_queue.insert(
                user_id=user_id,
                idempotency_key=idempotency_key,
                payload=dict(payload),
            )
            await uow.commit()

        return {"command_id": idempotency_key}
