from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from vocablens.core.errors import MutationTooSlowError
from vocablens.domain.models import UserCoreState
from vocablens.services.mutator import Mutator
from vocablens.workers.hot_user_worker import HotUserWorker


class _SlowCoreRepo:
    def __init__(self):
        self.state = UserCoreState(
            user_id=1,
            xp=0,
            level=1,
            current_streak=0,
            longest_streak=0,
            momentum_score=0.0,
            total_sessions=0,
            sessions_last_3_days=0,
            version=1,
            updated_at=datetime.now(timezone.utc),
        )

    async def get_for_update(self, user_id: int):
        await asyncio.sleep(0.2)
        return self.state

    async def update(self, user_id: int, state: UserCoreState):
        self.state = replace(state)
        return self.state


class _NoopLedger:
    async def get(self, *, user_id: int, idempotency_key: str):
        return None

    async def insert(self, **kwargs):
        return kwargs


class _NoopOutbox:
    async def insert(self, **kwargs):
        return kwargs


class _MutatorUow:
    def __init__(self):
        self.core_state = _SlowCoreRepo()
        self.mutation_ledger = _NoopLedger()
        self.outbox_events = _NoopOutbox()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


def test_db_timeout_injection_fails_fast_mutator_lock_wait():
    def _uow_factory():
        return _MutatorUow()

    mutator = Mutator(_uow_factory)

    async def _run():
        with pytest.raises(MutationTooSlowError):
            await mutator.mutate(
                user_id=1,
                mutation_fn=lambda s: replace(s, xp=s.xp + 1),
                idempotency_key="slow-lock",
                source="chaos",
            )

    asyncio.run(_run())


class _SchedulerQueueRepo:
    async def list_users_by_lag(self, *, limit: int):
        return [5, 2, 9][: int(limit)]


class _SchedulerUow:
    def __init__(self):
        self.mutation_queue = _SchedulerQueueRepo()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


class _OrderWorker(HotUserWorker):
    def __init__(self, uow_factory):
        super().__init__(uow_factory, batch_size=10)
        self.order: list[int] = []

    async def flush_user(self, user_id: int) -> int:  # type: ignore[override]
        self.order.append(int(user_id))
        return 1


def test_global_scheduler_prefers_lag_order():
    def _uow_factory():
        return _SchedulerUow()

    worker = _OrderWorker(_uow_factory)  # type: ignore[arg-type]

    async def _run():
        handled = await worker.run_once(max_users=3)
        assert handled == 3
        assert worker.order == [5, 2, 9]

    asyncio.run(_run())


class _TxnRow:
    def __init__(self, row_id: int, seq: int, xp_delta: int):
        self.id = row_id
        self.seq = seq
        self.idempotency_key = f"cmd-{seq}"
        self.payload = {"xp_delta": xp_delta}
        self.created_at = datetime.now(timezone.utc)


class _TxnShared:
    def __init__(self):
        self.state = UserCoreState(
            user_id=1,
            xp=0,
            level=1,
            current_streak=0,
            longest_streak=0,
            momentum_score=0.0,
            total_sessions=0,
            sessions_last_3_days=0,
            version=1,
            updated_at=datetime.now(timezone.utc),
        )
        self.rows = [_TxnRow(1, 1, 5)]
        self.last_applied = 0
        self.crash_once = True


class _TxnQueueRepo:
    def __init__(self, shared: _TxnShared):
        self._shared = shared
        self._pending_last_applied = None
        self._pending_delete_ids: list[int] = []

    async def claim_batch(self, *, user_id: int, limit: int):
        return list(self._shared.rows)

    async def get_last_applied_seq(self, user_id: int):
        return int(self._shared.last_applied)

    async def has_seq(self, *, user_id: int, seq: int):
        return any(int(row.seq) == int(seq) for row in self._shared.rows)

    async def delete_ids(self, ids: list[int]):
        self._pending_delete_ids = [int(v) for v in ids]

    async def set_last_applied_seq(self, *, user_id: int, seq: int):
        self._pending_last_applied = int(seq)

    def apply_commit(self):
        if self._pending_last_applied is not None:
            self._shared.last_applied = int(self._pending_last_applied)
        if self._pending_delete_ids:
            ids = set(self._pending_delete_ids)
            self._shared.rows = [row for row in self._shared.rows if int(row.id) not in ids]


class _TxnCoreRepo:
    def __init__(self, shared: _TxnShared):
        self._shared = shared
        self._pending_state = None

    async def get_for_update(self, user_id: int):
        return self._shared.state

    async def update(self, user_id: int, state: UserCoreState):
        self._pending_state = replace(state)
        return state

    def apply_commit(self):
        if self._pending_state is not None:
            self._shared.state = replace(self._pending_state)


class _TxnLedger:
    async def insert(self, **kwargs):
        return kwargs


class _TxnUow:
    def __init__(self, shared: _TxnShared):
        self._shared = shared
        self.mutation_queue = _TxnQueueRepo(shared)
        self.core_state = _TxnCoreRepo(shared)
        self.mutation_ledger = _TxnLedger()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        if self._shared.crash_once:
            self._shared.crash_once = False
            raise RuntimeError("simulated crash before commit")
        self.core_state.apply_commit()
        self.mutation_queue.apply_commit()


def test_worker_crash_mid_transaction_replay_no_double_apply():
    shared = _TxnShared()

    def _uow_factory():
        return _TxnUow(shared)

    worker = HotUserWorker(_uow_factory, batch_size=10)  # type: ignore[arg-type]

    async def _run():
        with pytest.raises(RuntimeError):
            await worker.flush_user(1)
        assert shared.state.xp == 0
        assert shared.last_applied == 0

        handled = await worker.flush_user(1)
        assert handled == 1
        assert shared.state.xp == 5
        assert shared.last_applied == 1

    asyncio.run(_run())
