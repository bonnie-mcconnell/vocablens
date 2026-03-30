from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from time import monotonic

from vocablens.domain.models import UserCoreState
from vocablens.workers.hot_user_worker import HotUserWorker


class _Row:
    def __init__(self, row_id: int, seq: int, idempotency_key: str, payload: dict):
        self.id = int(row_id)
        self.seq = int(seq)
        self.idempotency_key = str(idempotency_key)
        self.payload = dict(payload)
        self.created_at = datetime.now(timezone.utc)


class _CoreRepo:
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

    async def get_for_update(self, user_id: int) -> UserCoreState:
        return self.state

    async def update(self, user_id: int, state: UserCoreState) -> UserCoreState:
        self.state = replace(state)
        return self.state


class _LedgerRepo:
    def __init__(self):
        self.entries: list[dict] = []

    async def insert(self, **kwargs):
        self.entries.append(dict(kwargs))


class _QueueRepo:
    def __init__(self):
        self.rows = [
            _Row(10, 1, "cmd-1", {"xp_delta": 99}),
            _Row(11, 2, "cmd-2", {"xp_delta": 5}),
        ]
        self.last_applied = 1

    async def claim_batch(self, *, user_id: int, limit: int):
        return list(self.rows)

    async def get_last_applied_seq(self, user_id: int) -> int:
        return int(self.last_applied)

    async def has_seq(self, *, user_id: int, seq: int) -> bool:
        return False

    async def delete_ids(self, ids: list[int]) -> None:
        self.rows = [row for row in self.rows if int(row.id) not in set(int(v) for v in ids)]

    async def set_last_applied_seq(self, *, user_id: int, seq: int) -> None:
        self.last_applied = int(seq)


class _Uow:
    def __init__(self):
        self.core_state = _CoreRepo()
        self.mutation_ledger = _LedgerRepo()
        self.mutation_queue = _QueueRepo()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


def test_hot_worker_recovers_from_gap_without_stall():
    def _uow_factory():
        return _Uow()

    worker = HotUserWorker(_uow_factory, batch_size=10)  # type: ignore[arg-type]

    async def _run():
        start = monotonic()
        handled = await worker.flush_user(1)
        elapsed = monotonic() - start
        assert handled == 1
        assert elapsed < 2.5

    asyncio.run(_run())
