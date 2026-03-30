from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta

from vocablens.core.time import utc_now
from vocablens.workers.outbox_worker import OutboxWorker


@dataclass
class _Event:
    id: int
    dedupe_key: str
    event_type: str
    payload: dict
    retry_count: int = 0
    published_at: datetime | None = None
    next_attempt_at: datetime | None = None
    dead_lettered_at: datetime | None = None


class _OutboxRepo:
    def __init__(self, shared):
        self._shared = shared

    async def claim_unpublished(self, *, limit: int):
        now = utc_now()
        eligible = [
            event
            for event in self._shared["events"]
            if event.published_at is None
            and event.dead_lettered_at is None
            and (event.next_attempt_at is None or event.next_attempt_at <= now)
        ]
        selected = eligible[:limit]
        return [
            {
                "id": int(event.id),
                "dedupe_key": str(event.dedupe_key),
                "event_type": str(event.event_type),
                "payload": dict(event.payload),
            }
            for event in selected
        ]

    async def mark_published_many(self, *, ids: list[int]):
        for event in self._shared["events"]:
            if int(event.id) in set(int(v) for v in ids):
                event.published_at = utc_now()

    async def increment_retry_many(self, *, ids: list[int]):
        for event in self._shared["events"]:
            if int(event.id) not in set(int(v) for v in ids):
                continue
            next_retry = int(event.retry_count) + 1
            event.retry_count = next_retry
            if next_retry > 10:
                event.dead_lettered_at = utc_now()
                continue
            event.next_attempt_at = utc_now() + timedelta(seconds=min(60, 2 ** next_retry))


class _Uow:
    def __init__(self, shared):
        self.outbox_events = _OutboxRepo(shared)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


def test_outbox_backoff_under_failure():
    shared = {
        "events": [
            _Event(
                id=1,
                dedupe_key="dedupe-1",
                event_type="event.test",
                payload={"value": 1},
                next_attempt_at=utc_now(),
            )
        ]
    }

    def _uow_factory():
        return _Uow(shared)

    async def _publisher(event_type: str, payload: dict, dedupe_key: str):
        _ = (event_type, payload, dedupe_key)
        raise RuntimeError("publish failed")

    worker = OutboxWorker(_uow_factory, _publisher)  # type: ignore[arg-type]

    async def _run():
        first = await worker.run_once()
        assert first == 1
        assert shared["events"][0].retry_count == 1
        assert shared["events"][0].next_attempt_at is not None
        assert shared["events"][0].next_attempt_at > utc_now()

        second = await worker.run_once()
        assert second == 0

        for _ in range(11):
            shared["events"][0].next_attempt_at = utc_now() - timedelta(seconds=1)
            await worker.run_once()
        assert shared["events"][0].dead_lettered_at is not None

    asyncio.run(_run())
