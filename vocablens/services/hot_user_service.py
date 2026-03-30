from __future__ import annotations

from collections.abc import Callable
from time import monotonic

from vocablens.core.contracts import HOT_QUEUE_MAX, READ_YOUR_WRITES_TTL_SECONDS
from vocablens.core.errors import HotUserBackpressureError
from vocablens.infrastructure.unit_of_work import UnitOfWork


class HotUserService:
    """Durable enqueue path for hot-user write mode."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork], max_queue: int = HOT_QUEUE_MAX):
        self._uow_factory = uow_factory
        self._max_queue = max_queue
        self._ryw_cache: dict[tuple[int, str], tuple[float, dict]] = {}

    async def enqueue(self, *, user_id: int, payload: dict, idempotency_key: str) -> dict[str, str | int]:
        async with self._uow_factory() as uow:
            await uow.core_state.get_for_update(user_id)
            depth = await uow.mutation_queue.count(user_id)
            if depth >= self._max_queue:
                raise HotUserBackpressureError("hot_user_backpressure")

            seq = await uow.mutation_queue.next_seq(user_id)
            item = await uow.mutation_queue.insert_with_seq(
                user_id=user_id,
                seq=seq,
                idempotency_key=idempotency_key,
                payload=dict(payload),
            )
            await uow.commit()

        self._cache_command(user_id=user_id, command_id=idempotency_key, payload=dict(payload))

        return {"command_id": idempotency_key, "mode": "hot", "seq": item.seq}

    def _cache_command(self, *, user_id: int, command_id: str, payload: dict) -> None:
        expires_at = monotonic() + READ_YOUR_WRITES_TTL_SECONDS
        self._ryw_cache[(int(user_id), str(command_id))] = (expires_at, dict(payload))

    def get_cached_command_payload(self, *, user_id: int, command_id: str) -> dict | None:
        key = (int(user_id), str(command_id))
        entry = self._ryw_cache.get(key)
        if entry is None:
            return None
        expires_at, payload = entry
        if monotonic() > expires_at:
            self._ryw_cache.pop(key, None)
            return None
        return dict(payload)
