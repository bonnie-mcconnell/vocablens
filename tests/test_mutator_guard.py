from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from vocablens.core.errors import MutationTooSlowError
from vocablens.domain.models import UserCoreState
from vocablens.services.mutator import CoreMutationGuard, Mutator


class _FakeCoreRepo:
    def __init__(self, shared):
        self._shared = shared
        if self._shared.state is None:
            self._shared.state = UserCoreState(
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
        return self._shared.state

    async def update(self, user_id: int, state: UserCoreState) -> UserCoreState:
        self._shared.state = replace(state)
        return self._shared.state


class _SharedStore:
    def __init__(self):
        self.state: UserCoreState | None = None
        self.ledger: dict[tuple[int, str], dict] = {}
        self.outbox: list[dict] = []


class _FakeLedgerRepo:
    def __init__(self, shared):
        self._shared = shared

    async def get(self, *, user_id: int, idempotency_key: str):
        return self._shared.ledger.get((user_id, idempotency_key))

    async def insert(self, **kwargs):
        self._shared.ledger[(kwargs["user_id"], kwargs["idempotency_key"])] = dict(kwargs)
        return kwargs


class _FakeOutboxRepo:
    def __init__(self, shared):
        self._shared = shared

    async def insert(self, **kwargs):
        self._shared.outbox.append(dict(kwargs))
        return kwargs


class _FakeUow:
    def __init__(self, shared):
        self.core_state = _FakeCoreRepo(shared)
        self.mutation_ledger = _FakeLedgerRepo(shared)
        self.outbox_events = _FakeOutboxRepo(shared)
        self.commit_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        self.commit_count += 1


def _uow_factory(shared):
    def _factory():
        return _FakeUow(shared)

    return _factory


def test_mutator_applies_once_for_same_idempotency_key():
    async def _run() -> None:
        shared = _SharedStore()
        mutator = Mutator(_uow_factory(shared))

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
        assert len(shared.outbox) == 1
        assert shared.outbox[0]["dedupe_key"] == "1:req-1"

    asyncio.run(_run())


def test_core_mutation_guard_enforces_structural_rules():
    guard = CoreMutationGuard()

    def forbidden_loop(state: UserCoreState) -> UserCoreState:
        total = 0
        for value in [1, 2, 3]:
            total += value
        if total > 0:
            return state
        return state

    with pytest.raises(MutationTooSlowError):
        guard.execute(
            forbidden_loop,
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
