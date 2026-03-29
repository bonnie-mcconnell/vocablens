from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from vocablens.core.errors import MutationTooSlowError
from vocablens.domain.models import UserCoreState
from vocablens.services.mutator import CoreMutationGuard, Mutator


class _FakeCoreRepo:
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


class _FakeLedgerRepo:
    def __init__(self):
        self.entries: dict[tuple[int, str], dict] = {}

    async def get(self, *, user_id: int, idempotency_key: str):
        return self.entries.get((user_id, idempotency_key))

    async def insert(self, **kwargs):
        self.entries[(kwargs["user_id"], kwargs["idempotency_key"])] = dict(kwargs)
        return kwargs


class _FakeOutboxRepo:
    def __init__(self):
        self.events = []

    async def insert(self, **kwargs):
        self.events.append(dict(kwargs))
        return kwargs


class _FakeUow:
    def __init__(self):
        self.core_state = _FakeCoreRepo()
        self.mutation_ledger = _FakeLedgerRepo()
        self.outbox_events = _FakeOutboxRepo()
        self.commit_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        self.commit_count += 1


def _uow_factory():
    return _FakeUow()


def test_mutator_applies_once_for_same_idempotency_key():
    async def _run() -> None:
        mutator = Mutator(_uow_factory)

        def mutate(state: UserCoreState) -> UserCoreState:
            return replace(state, xp=state.xp + 10)

        first = await mutator.mutate(
            user_id=1,
            mutation_fn=mutate,
            idempotency_key="req-1",
            source="test",
            reference_id="abc",
        )
        second = await mutator.mutate(
            user_id=1,
            mutation_fn=mutate,
            idempotency_key="req-1",
            source="test",
            reference_id="abc",
        )

        assert first.xp == 10
        assert second.xp == 10

    asyncio.run(_run())


def test_core_mutation_guard_enforces_budget():
    guard = CoreMutationGuard()

    def too_slow(state: UserCoreState) -> UserCoreState:
        import time

        time.sleep(0.01)
        return state

    with pytest.raises(MutationTooSlowError):
        guard.execute(
            too_slow,
            UserCoreState(
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
            ),
        )
