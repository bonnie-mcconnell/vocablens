from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import cast

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
        self.next_seq: int = 1
        self.execution_mode: str = "cold"


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
        seq = int(self._shared.next_seq)
        self._shared.next_seq += 1
        return seq

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

    async def is_overloaded(self, *, user_id: int, depth_threshold: int, sustained_seconds: int) -> bool:
        depth = await self.count(user_id)
        if depth <= int(depth_threshold):
            return False
        created_values = [
            cast(datetime, item["created_at"]) for item in self._shared.queue if item.get("created_at") is not None
        ]
        oldest = min(created_values) if created_values else None
        if oldest is None:
            return False
        return oldest <= datetime.now(timezone.utc) - timedelta(seconds=int(sustained_seconds))

    async def coalesce_latest_xp_delta(self, *, user_id: int, xp_delta: int) -> bool:
        if not self._shared.queue:
            return False
        latest = sorted(self._shared.queue, key=lambda row: int(row["seq"]))[-1]
        payload = dict(latest.get("payload") or {})
        if "xp_delta" not in payload:
            return False
        payload["xp_delta"] = int(payload.get("xp_delta", 0)) + int(xp_delta)
        latest["payload"] = payload
        return True


class _FakeExecutionModeRepo:
    def __init__(self, shared: _Shared):
        self._shared = shared

    async def get_or_create(self, user_id: int) -> str:
        return str(self._shared.execution_mode)

    async def set_mode(self, *, user_id: int, mode: str) -> str:
        self._shared.execution_mode = "hot" if str(mode).lower() == "hot" else "cold"
        return str(self._shared.execution_mode)


class _FakeUow:
    def __init__(self, shared: _Shared):
        self._shared = shared
        self.core_state = _FakeCoreRepo(shared)
        self.mutation_queue = _FakeQueueRepo(shared)
        self.execution_mode = _FakeExecutionModeRepo(shared)

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

    service_a = HotUserService(_uow_factory, max_queue=1000)  # type: ignore[arg-type]
    service_b = HotUserService(_uow_factory, max_queue=1000)  # type: ignore[arg-type]

    async def _run():
        tasks = [
            (service_a if idx % 2 == 0 else service_b).enqueue(
                user_id=1,
                payload={"xp_delta": idx},
                idempotency_key=f"cmd-{idx}",
            )
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

    second_write = client.post(
        "/state/mutate-xp",
        json={
            "xp_delta": 7,
            "idempotency_key": "cmd-hot-2",
            "mode": "hot",
        },
    )
    assert second_write.status_code == 200

    read_first = client.get("/state/core", params={"after_command_id": "cmd-hot-1"})
    assert read_first.status_code == 200
    assert read_first.json()["data"]["state"]["xp"] == 13

    read_second = client.get("/state/core", params={"after_command_id": "cmd-hot-2"})
    assert read_second.status_code == 200
    payload = read_second.json()
    assert payload["meta"]["mode"] == "hot"
    assert payload["meta"]["consistent"] is True
    assert payload["data"]["state"]["xp"] == 20


def test_hot_queue_overload_coalesces_similar_mutations():
    shared = _Shared()
    now = datetime.now(timezone.utc)
    for seq in range(1, 405):
        shared.queue.append(
            {
                "user_id": 1,
                "seq": seq,
                "idempotency_key": f"existing-{seq}",
                "payload": {"xp_delta": 1},
                "created_at": now - timedelta(seconds=31),
            }
        )
    shared.next_seq = 405

    def _uow_factory():
        return _FakeUow(shared)

    service = HotUserService(_uow_factory, max_queue=1000)  # type: ignore[arg-type]

    async def _run():
        before_len = len(shared.queue)
        result = await service.enqueue(user_id=1, payload={"xp_delta": 5}, idempotency_key="coalesce-1")
        assert result["mode"] == "hot"
        assert int(result["seq"]) == 0
        assert len(shared.queue) == before_len
        latest = sorted(shared.queue, key=lambda row: int(row["seq"]))[-1]
        assert int((latest.get("payload") or {}).get("xp_delta", 0)) == 6

    asyncio.run(_run())
