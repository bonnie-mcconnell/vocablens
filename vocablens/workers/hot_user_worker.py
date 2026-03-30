from __future__ import annotations

from collections.abc import Callable

from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.mutations import apply_xp_delta


class HotUserWorker:
    """Durable queue flusher for hot-user mode."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork], batch_size: int = 100):
        self._uow_factory = uow_factory
        self._batch_size = batch_size

    async def flush_user(self, user_id: int) -> int:
        async with self._uow_factory() as uow:
            rows = await uow.mutation_queue.claim_batch(user_id=user_id, limit=self._batch_size)
            if not rows:
                await uow.commit()
                return 0

            rows = sorted(rows, key=lambda row: int(row.seq))
            prev_seq = None
            for row in rows:
                seq = int(row.seq)
                if prev_seq is not None and seq != prev_seq + 1:
                    raise RuntimeError(f"Hot queue gap detected for user {user_id}: {prev_seq} -> {seq}")
                prev_seq = seq

            state = await uow.core_state.get_for_update(user_id)
            for row in rows:
                xp_delta = int((row.payload or {}).get("xp_delta", 0))
                state = apply_xp_delta(state, xp_delta=xp_delta)
                await uow.mutation_ledger.insert(
                    user_id=user_id,
                    idempotency_key=row.idempotency_key,
                    source="hot_user_worker",
                    reference_id=str(row.id),
                    result_code=202,
                )

            await uow.core_state.update(user_id, state)
            await uow.mutation_queue.delete_ids([int(row.id) for row in rows])
            await uow.commit()
            return len(rows)
