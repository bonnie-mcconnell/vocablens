from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from time import monotonic

from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.mutations import apply_xp_delta


_logger = logging.getLogger(__name__)


class HotUserWorker:
    """Durable queue flusher for hot-user mode."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork], batch_size: int = 100):
        self._uow_factory = uow_factory
        self._batch_size = batch_size
        self._gap_wait_seconds = 2.0

    async def _wait_for_missing_seq(self, uow, *, user_id: int, missing_seq: int) -> bool:
        deadline = monotonic() + self._gap_wait_seconds
        while monotonic() < deadline:
            if await uow.mutation_queue.has_seq(user_id=user_id, seq=missing_seq):
                return True
            await asyncio.sleep(0.05)
        return False

    async def flush_user(self, user_id: int) -> int:
        async with self._uow_factory() as uow:
            rows = await uow.mutation_queue.claim_batch(user_id=user_id, limit=self._batch_size)
            if not rows:
                await uow.commit()
                return 0

            rows = sorted(rows, key=lambda row: int(row.seq))
            last_applied_seq = await uow.mutation_queue.get_last_applied_seq(user_id)
            expected_seq = int(last_applied_seq) + 1

            first_seq = int(rows[0].seq)
            if first_seq > expected_seq:
                found = await self._wait_for_missing_seq(uow, user_id=user_id, missing_seq=expected_seq)
                if found:
                    rows = await uow.mutation_queue.claim_batch(user_id=user_id, limit=self._batch_size)
                    rows = sorted(rows, key=lambda row: int(row.seq))
                    first_seq = int(rows[0].seq)
                if first_seq > expected_seq:
                    _logger.critical(
                        "hot_queue_gap_skip user_id=%s expected_seq=%s actual_seq=%s",
                        user_id,
                        expected_seq,
                        first_seq,
                    )
                    expected_seq = first_seq

            state = await uow.core_state.get_for_update(user_id)
            processed = 0
            for row in rows:
                row_seq = int(row.seq)
                if row_seq > expected_seq:
                    found = await self._wait_for_missing_seq(uow, user_id=user_id, missing_seq=expected_seq)
                    if not found:
                        _logger.critical(
                            "hot_queue_gap_skip user_id=%s expected_seq=%s actual_seq=%s",
                            user_id,
                            expected_seq,
                            row_seq,
                        )
                    expected_seq = row_seq
                xp_delta = int((row.payload or {}).get("xp_delta", 0))
                state = apply_xp_delta(state, xp_delta=xp_delta)
                await uow.mutation_ledger.insert(
                    user_id=user_id,
                    idempotency_key=row.idempotency_key,
                    source="hot_user_worker",
                    reference_id=str(row.id),
                    result_code=202,
                )
                expected_seq = row_seq + 1
                processed += 1

            await uow.core_state.update(user_id, state)
            await uow.mutation_queue.delete_ids([int(row.id) for row in rows])
            if rows:
                await uow.mutation_queue.set_last_applied_seq(user_id=user_id, seq=int(rows[-1].seq))
            await uow.commit()
            return processed
