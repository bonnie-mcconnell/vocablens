from types import SimpleNamespace

import pytest

from tests.conftest import run_async
from vocablens.services.event_service import EventService


class FakeEventsRepo:
    def __init__(self):
        self.rows = []
        self._next_id = 1

    async def record(self, *, user_id: int, event_type: str, payload: dict, created_at=None) -> None:
        row = SimpleNamespace(
            id=self._next_id,
            user_id=user_id,
            event_type=event_type,
            payload=payload,
            created_at=created_at,
        )
        self._next_id += 1
        self.rows.append(row)

    async def list_by_user(self, user_id: int, limit: int = 1000):
        return [row for row in reversed(self.rows) if row.user_id == user_id][:limit]

    async def list_by_type(self, event_type: str, limit: int = 1000):
        return [row for row in reversed(self.rows) if row.event_type == event_type][:limit]


class FakeUOW:
    def __init__(self, repo: FakeEventsRepo):
        self.events = repo
        self.engagement_states = SimpleNamespace(get_or_create=self._get_or_create, update=self._update)
        self._engagement_state = SimpleNamespace(interaction_stats={})

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None

    async def _get_or_create(self, user_id: int):
        return self._engagement_state

    async def _update(self, user_id: int, **kwargs):
        for key, value in kwargs.items():
            setattr(self._engagement_state, key, value)
        return self._engagement_state


class FailingEventsRepo(FakeEventsRepo):
    async def record(self, *, user_id: int, event_type: str, payload: dict, created_at=None) -> None:
        raise RuntimeError("event persistence failed")


def test_event_service_persists_events_and_supports_queries():
    repo = FakeEventsRepo()
    service = EventService(lambda: FakeUOW(repo))

    async def scenario():
        await service.track_event(1, "message_sent", {"text": "hola"})
        await service.track_event(1, "mistake_made", {"count": 2})
        await service.track_event(2, "message_sent", {"text": "bonjour"})
        await service.flush()
        result = await service.get_user_events(1), await service.get_events_by_type("message_sent")
        await service.close()
        return result

    user_events, message_events = run_async(scenario())

    assert [event.event_type for event in user_events] == ["mistake_made", "message_sent"]
    assert user_events[0].payload == {"count": 2}
    assert [event.user_id for event in message_events] == [2, 1]


def test_event_service_handles_high_volume_buffered_ingestion():
    repo = FakeEventsRepo()
    service = EventService(lambda: FakeUOW(repo), use_buffer=True, buffer_size=32)

    async def scenario():
        for user_id in range(1, 501):
            await service.track_event(
                user_id,
                "message_sent",
                {"sequence": user_id},
            )
        await service.flush()
        result = await service.get_events_by_type("message_sent")
        await service.close()
        return result

    events = run_async(scenario())

    assert len(repo.rows) == 500
    assert len(events) == 500
    assert {event.payload["sequence"] for event in events} == set(range(1, 501))


def test_event_service_durable_mode_surfaces_persistence_errors():
    service = EventService(lambda: FakeUOW(FailingEventsRepo()), use_buffer=True, ingest_mode="durable")

    async def scenario():
        with pytest.raises(RuntimeError, match="event persistence failed"):
            await service.track_event(1, "message_sent", {"text": "hola"})
        await service.close()

    run_async(scenario())


def test_event_service_best_effort_mode_drops_failed_events_without_raising():
    service = EventService(lambda: FakeUOW(FailingEventsRepo()), use_buffer=False, ingest_mode="best_effort")

    async def scenario():
        await service.track_event(1, "message_sent", {"text": "hola"})
        await service.flush()
        await service.close()

    run_async(scenario())
