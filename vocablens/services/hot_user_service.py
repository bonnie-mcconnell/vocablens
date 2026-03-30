from __future__ import annotations

import logging
from collections.abc import Callable
from enum import Enum
from time import perf_counter_ns

from vocablens.core.contracts import HOT_QUEUE_MAX, LOCK_WAIT_FAILFAST_MS
from vocablens.core.time import utc_now
from vocablens.core.runtime_metrics import runtime_metrics
from vocablens.core.errors import HotUserBackpressureError
from vocablens.infrastructure.unit_of_work import UnitOfWork


_OVERLOAD_DEPTH_THRESHOLD = 400
_OVERLOAD_SUSTAINED_SECONDS = 30
_logger = logging.getLogger(__name__)


class MutationType(str, Enum):
    ADD_XP = "ADD_XP"
    SET_STREAK = "SET_STREAK"


class HotUserService:
    """Durable enqueue path for hot-user write mode."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork], max_queue: int = HOT_QUEUE_MAX):
        self._uow_factory = uow_factory
        self._max_queue = max_queue

    async def enqueue(self, *, user_id: int, payload: dict, idempotency_key: str) -> dict[str, str | int]:
        command_seq = 0
        async with self._uow_factory() as uow:
            lock_wait_start = perf_counter_ns()
            await uow.core_state.get_for_update(user_id)
            lock_wait_ms = (perf_counter_ns() - lock_wait_start) / 1_000_000
            runtime_metrics().observe_lock_wait_ms(component="hot_user_enqueue", value_ms=lock_wait_ms)
            if lock_wait_ms > float(LOCK_WAIT_FAILFAST_MS):
                raise HotUserBackpressureError("hot_user_lock_wait_backpressure")

            depth = await uow.mutation_queue.count(user_id)
            runtime_metrics().observe_queue_depth(component="hot_user_queue", value=depth)
            if depth >= self._max_queue:
                raise HotUserBackpressureError("hot_user_backpressure")

            oldest_created = await uow.mutation_queue.oldest_created_at(user_id=user_id)
            if oldest_created is not None:
                normalized_oldest = oldest_created
                if getattr(normalized_oldest, "tzinfo", None) is not None:
                    normalized_oldest = normalized_oldest.replace(tzinfo=None)
                runtime_metrics().observe_queue_lag_ms(
                    component="hot_user_queue",
                    value_ms=max(0.0, (utc_now() - normalized_oldest).total_seconds() * 1000),
                )

            overloaded = await uow.mutation_queue.is_overloaded(
                user_id=user_id,
                depth_threshold=_OVERLOAD_DEPTH_THRESHOLD,
                sustained_seconds=_OVERLOAD_SUSTAINED_SECONDS,
            )
            mutation_type = str(payload.get("mutation_type", ""))
            if overloaded and mutation_type == MutationType.ADD_XP.value and "xp_delta" in payload:
                xp_delta = int(payload.get("xp_delta", 0) or 0)
                if xp_delta == 0:
                    _logger.warning("hot_queue_drop_redundant user_id=%s idempotency_key=%s", user_id, idempotency_key)
                    command_seq = await uow.mutation_queue.latest_seq(user_id=user_id)
                    await uow.command_receipts.upsert(
                        user_id=user_id,
                        command_id=idempotency_key,
                        command_seq=int(command_seq),
                        mode="hot",
                    )
                    await uow.commit()
                    return {"command_id": idempotency_key, "mode": "hot", "command_seq": command_seq}
                coalesced = await uow.mutation_queue.coalesce_latest_xp_delta(user_id=user_id, xp_delta=xp_delta)
                if coalesced:
                    _logger.warning("hot_queue_coalesced user_id=%s idempotency_key=%s", user_id, idempotency_key)
                    command_seq = await uow.mutation_queue.latest_seq(user_id=user_id)
                    await uow.command_receipts.upsert(
                        user_id=user_id,
                        command_id=idempotency_key,
                        command_seq=int(command_seq),
                        mode="hot",
                    )
                    await uow.commit()
                    return {"command_id": idempotency_key, "mode": "hot", "command_seq": command_seq}
            elif overloaded and mutation_type and mutation_type != MutationType.ADD_XP.value:
                _logger.warning(
                    "hot_queue_skip_coalesce_non_additive user_id=%s idempotency_key=%s mutation_type=%s",
                    user_id,
                    idempotency_key,
                    mutation_type,
                )

            seq = await uow.mutation_queue.next_seq(user_id)
            item = await uow.mutation_queue.insert_with_seq(
                user_id=user_id,
                seq=seq,
                idempotency_key=idempotency_key,
                payload=dict(payload),
            )
            command_seq = int(item.seq)
            await uow.command_receipts.upsert(
                user_id=user_id,
                command_id=idempotency_key,
                command_seq=int(command_seq),
                mode="hot",
            )
            await uow.commit()

        return {"command_id": idempotency_key, "mode": "hot", "command_seq": command_seq}
