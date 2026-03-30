from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from time import monotonic

from vocablens.core.contracts import HOT_QUEUE_MAX, READ_YOUR_WRITES_TTL_SECONDS
from vocablens.core.errors import HotUserBackpressureError
from vocablens.domain.models import UserCoreState
from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.mutations import apply_xp_delta


_OVERLOAD_DEPTH_THRESHOLD = 400
_OVERLOAD_SUSTAINED_SECONDS = 30
_logger = logging.getLogger(__name__)


class HotUserService:
    """Durable enqueue path for hot-user write mode."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork], max_queue: int = HOT_QUEUE_MAX):
        self._uow_factory = uow_factory
        self._max_queue = max_queue
        self._ryw_cache: dict[tuple[int, str], tuple[float, UserCoreState]] = {}
        self._latest_projected_state: dict[int, tuple[float, UserCoreState]] = {}

    async def enqueue(self, *, user_id: int, payload: dict, idempotency_key: str) -> dict[str, str | int]:
        command_seq = 0
        async with self._uow_factory() as uow:
            state = await uow.core_state.get_for_update(user_id)
            depth = await uow.mutation_queue.count(user_id)
            if depth >= self._max_queue:
                raise HotUserBackpressureError("hot_user_backpressure")

            projected_base = self._latest_cached_state_for_user(user_id=user_id, fallback=state)
            projected = self._project_state(projected_base, payload)

            overloaded = await uow.mutation_queue.is_overloaded(
                user_id=user_id,
                depth_threshold=_OVERLOAD_DEPTH_THRESHOLD,
                sustained_seconds=_OVERLOAD_SUSTAINED_SECONDS,
            )
            if overloaded and "xp_delta" in payload:
                xp_delta = int(payload.get("xp_delta", 0))
                if xp_delta == 0:
                    _logger.warning("hot_queue_drop_redundant user_id=%s idempotency_key=%s", user_id, idempotency_key)
                    await uow.commit()
                    self._cache_command(user_id=user_id, command_id=idempotency_key, projected_state=projected)
                    return {"command_id": idempotency_key, "mode": "hot", "seq": command_seq}
                coalesced = await uow.mutation_queue.coalesce_latest_xp_delta(user_id=user_id, xp_delta=xp_delta)
                if coalesced:
                    _logger.warning("hot_queue_coalesced user_id=%s idempotency_key=%s", user_id, idempotency_key)
                    await uow.commit()
                    self._cache_command(user_id=user_id, command_id=idempotency_key, projected_state=projected)
                    return {"command_id": idempotency_key, "mode": "hot", "seq": command_seq}

            seq = await uow.mutation_queue.next_seq(user_id)
            item = await uow.mutation_queue.insert_with_seq(
                user_id=user_id,
                seq=seq,
                idempotency_key=idempotency_key,
                payload=dict(payload),
            )
            command_seq = int(item.seq)
            await uow.commit()

        self._cache_command(user_id=user_id, command_id=idempotency_key, projected_state=projected)

        return {"command_id": idempotency_key, "mode": "hot", "seq": command_seq}

    def _cache_command(self, *, user_id: int, command_id: str, projected_state: UserCoreState) -> None:
        expires_at = monotonic() + READ_YOUR_WRITES_TTL_SECONDS
        state_copy = replace(projected_state)
        self._ryw_cache[(int(user_id), str(command_id))] = (expires_at, state_copy)
        self._latest_projected_state[int(user_id)] = (expires_at, state_copy)

    def get_cached_command_state(self, *, user_id: int, command_id: str) -> UserCoreState | None:
        key = (int(user_id), str(command_id))
        entry = self._ryw_cache.get(key)
        if entry is None:
            return None
        expires_at, cached_state = entry
        if monotonic() > expires_at:
            self._ryw_cache.pop(key, None)
            return None
        return replace(cached_state)

    def _latest_cached_state_for_user(self, *, user_id: int, fallback: UserCoreState) -> UserCoreState:
        entry = self._latest_projected_state.get(int(user_id))
        if entry is None:
            return replace(fallback)
        expires_at, cached_state = entry
        if monotonic() > expires_at:
            self._latest_projected_state.pop(int(user_id), None)
            return replace(fallback)
        return replace(cached_state)

    def _project_state(self, state: UserCoreState, payload: dict) -> UserCoreState:
        if "xp_delta" in payload:
            return apply_xp_delta(state, xp_delta=int(payload.get("xp_delta", 0)))
        return replace(state)
