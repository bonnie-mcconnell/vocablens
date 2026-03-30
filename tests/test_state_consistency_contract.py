from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from tests.conftest import make_user
from vocablens.api.dependencies_core import get_uow_factory
from vocablens.api.dependencies_interaction_api import get_current_user, get_hot_user_service, get_mutator
from vocablens.main import create_app
from vocablens.domain.models import UserCoreState
from vocablens.services.hot_user_service import HotUserService


class _QueueItem:
    def __init__(self, seq: int):
        self.seq = int(seq)


class _Shared:
    def __init__(self):
        self.lock = asyncio.Lock()
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
        self.queue: list[dict] = []


class _FakeCoreRepo:
    def __init__(self, shared: _Shared):
        self._shared = shared

    async def get_for_update(self, user_id: int):
        return self._shared.state

    async def get_or_create(self, user_id: int):
        return self._shared.state


class _FakeQueueRepo:
    def __init__(self, shared: _Shared):
        self._shared = shared

    async def count(self, user_id: int) -> int:
        return len(self._shared.queue)

    async def next_seq(self, user_id: int) -> int:
        if not self._shared.queue:
            return 1
        return max(int(row["seq"]) for row in self._shared.queue) + 1

    async def insert_with_seq(self, *, user_id: int, seq: int, idempotency_key: str, payload: dict):
        self._shared.queue.append(
            {
                "user_id": int(user_id),
                "seq": int(seq),
                "idempotency_key": str(idempotency_key),
                "payload": dict(payload),
            }
        )
        return _QueueItem(seq=int(seq))


class _FakeUow:
    def __init__(self, shared: _Shared):
        self._shared = shared
        self.core_state = _FakeCoreRepo(shared)
        self.mutation_queue = _FakeQueueRepo(shared)

    async def __aenter__(self):
        await self._shared.lock.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self._shared.lock.release()
        return None

    async def commit(self):
        return None


class _FakeMutator:
    async def mutate(self, **kwargs):
        state = kwargs["mutation_fn"](
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
            )
        )
        return replace(state, version=2)


def test_hot_enqueue_assigns_monotonic_seq_under_concurrency():
    shared = _Shared()

    def _uow_factory():
        return _FakeUow(shared)

    service = HotUserService(_uow_factory, max_queue=1000)  # type: ignore[arg-type]

    async def _run():
        tasks = [
            service.enqueue(user_id=1, payload={"xp_delta": idx}, idempotency_key=f"cmd-{idx}")
            for idx in range(1, 21)
        ]
        results = await asyncio.gather(*tasks)
        seqs = sorted(int(item["seq"]) for item in results)
        assert seqs == list(range(1, 21))

        queued = sorted(shared.queue, key=lambda row: int(row["seq"]))
        assert [int(row["seq"]) for row in queued] == list(range(1, 21))

    asyncio.run(_run())


def test_state_api_supports_after_command_id_read_your_writes_hot_mode():
    shared = _Shared()

    def _uow_factory():
        return _FakeUow(shared)

    hot_service = HotUserService(_uow_factory, max_queue=1000)  # type: ignore[arg-type]

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: make_user(user_id=1)
    app.dependency_overrides[get_hot_user_service] = lambda: hot_service
    app.dependency_overrides[get_mutator] = lambda: _FakeMutator()
    app.dependency_overrides[get_uow_factory] = lambda: _uow_factory

    client = TestClient(app)

    write_resp = client.post(
        "/state/mutate-xp",
        json={
            "xp_delta": 13,
            "idempotency_key": "cmd-hot-1",
            "mode": "hot",
        },
    )
    assert write_resp.status_code == 200
    write_payload = write_resp.json()
    assert write_payload["data"] == {"command_id": "cmd-hot-1", "mode": "hot"}

    stale_read = client.get("/state/core")
    assert stale_read.status_code == 200
    assert stale_read.json()["data"]["state"]["xp"] == 0

    consistent_read = client.get("/state/core", params={"after_command_id": "cmd-hot-1"})
    assert consistent_read.status_code == 200
    payload = consistent_read.json()
    assert payload["meta"]["mode"] == "hot"
    assert payload["meta"]["consistent"] is True
    assert payload["data"]["state"]["xp"] == 13
