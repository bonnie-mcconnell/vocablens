from __future__ import annotations

import hashlib
import json
import time
from dataclasses import replace
from collections.abc import Callable
from typing import Any

from vocablens.core.contracts import LOCK_WAIT_FAILFAST_MS, MUTATION_CPU_BUDGET_MS
from vocablens.core.runtime_metrics import runtime_metrics
from vocablens.core.errors import MutationTooSlowError
from vocablens.domain.models import UserCoreState


class CoreMutationGuard:
    """Runtime CPU budget guard for mutation functions."""

    def execute(self, fn: Callable[[UserCoreState], UserCoreState], state: UserCoreState) -> UserCoreState:
        start_cpu_ns = time.process_time_ns()
        result = fn(state)
        elapsed_ms = (time.process_time_ns() - start_cpu_ns) / 1_000_000
        if elapsed_ms > float(MUTATION_CPU_BUDGET_MS):
            raise MutationTooSlowError(
                f"mutation_fn CPU budget exceeded: {elapsed_ms:.3f}ms > {float(MUTATION_CPU_BUDGET_MS):.3f}ms"
            )
        return result


class Mutator:
    """Single transactional entry-point for all core-state mutations."""

    def __init__(self, uow_factory: Callable[[], Any], guard: CoreMutationGuard | None = None):
        self._uow_factory = uow_factory
        self._guard = guard or CoreMutationGuard()

    async def mutate(
        self,
        *,
        user_id: int,
        mutation_fn: Callable[[UserCoreState], UserCoreState],
        idempotency_key: str,
        source: str,
        reference_id: str | None = None,
    ) -> UserCoreState:
        async with self._uow_factory() as uow:
            lock_wait_start = time.perf_counter_ns()
            state = await uow.core_state.get_for_update(user_id)
            lock_wait_ms = (time.perf_counter_ns() - lock_wait_start) / 1_000_000
            runtime_metrics().observe_lock_wait_ms(component="mutator", value_ms=lock_wait_ms)
            if lock_wait_ms > float(LOCK_WAIT_FAILFAST_MS):
                raise MutationTooSlowError(
                    f"lock wait exceeded threshold: {lock_wait_ms:.3f}ms > {float(LOCK_WAIT_FAILFAST_MS):.3f}ms"
                )

            existing = await uow.mutation_ledger.get(user_id=user_id, idempotency_key=idempotency_key)
            if existing is not None:
                await uow.commit()
                return state

            new_state = self._guard.execute(mutation_fn, state)
            write_state = replace(new_state, version=int(state.version) + 1)
            updated = await uow.core_state.update(user_id, write_state)

            await uow.mutation_ledger.insert(
                user_id=user_id,
                idempotency_key=idempotency_key,
                source=source,
                reference_id=reference_id,
                result_code=200,
                result_hash=self._hash_state(updated),
                response_etag=self._state_etag(updated),
            )

            await uow.outbox_events.insert(
                user_id=user_id,
                dedupe_key=f"{user_id}:{idempotency_key}",
                event_type=source,
                payload={"delta": self._delta(state, updated)},
            )
            await uow.commit()
            return updated

    def _delta(self, old: UserCoreState, new: UserCoreState) -> dict[str, int | float]:
        return {
            "xp_delta": int(new.xp) - int(old.xp),
            "level_delta": int(new.level) - int(old.level),
            "streak_delta": int(new.current_streak) - int(old.current_streak),
            "momentum_delta": round(float(new.momentum_score) - float(old.momentum_score), 3),
            "total_sessions_delta": int(new.total_sessions) - int(old.total_sessions),
        }

    def _hash_state(self, state: UserCoreState) -> str:
        payload = {
            "user_id": state.user_id,
            "xp": state.xp,
            "level": state.level,
            "current_streak": state.current_streak,
            "longest_streak": state.longest_streak,
            "momentum_score": round(float(state.momentum_score), 3),
            "total_sessions": state.total_sessions,
            "sessions_last_3_days": state.sessions_last_3_days,
            "version": state.version,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def _state_etag(self, state: UserCoreState) -> str:
        return f"W/\"{state.user_id}:{state.version}\""
