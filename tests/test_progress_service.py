import json
from datetime import timedelta
from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.core.time import utc_now
from vocablens.services.progress_service import ProgressService


class FakeVocabRepo:
    def __init__(self, items):
        self.items = items

    async def list_all(self, user_id: int, limit: int, offset: int):
        return self.items

    async def list_due(self, user_id: int):
        return [item for item in self.items if getattr(item, "next_review_due", None) is not None]


class FakeStateRepo:
    def __init__(self, state):
        self.state = state

    async def get_or_create(self, user_id: int):
        return self.state


class FakeLearningEventsRepo:
    def __init__(self, events):
        self.events = events

    async def list_since(self, user_id: int, since):
        return [event for event in self.events if event.created_at >= since]


class FakeUOW:
    def __init__(self, items, learning_state, engagement_state, progress_state, events):
        self.vocab = FakeVocabRepo(items)
        self.learning_states = FakeStateRepo(learning_state)
        self.engagement_states = FakeStateRepo(engagement_state)
        self.progress_states = FakeStateRepo(progress_state)
        self.learning_events = FakeLearningEventsRepo(events)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


def test_progress_service_computes_metric_accuracy():
    now = utc_now()
    items = [
        SimpleNamespace(review_count=4, ease_factor=2.5, next_review_due=None),
        SimpleNamespace(review_count=3, ease_factor=2.4, next_review_due=now + timedelta(days=1)),
        SimpleNamespace(review_count=1, ease_factor=2.0, next_review_due=None),
        SimpleNamespace(review_count=0, ease_factor=2.5, next_review_due=None),
    ]
    events = [
        SimpleNamespace(
            event_type="word_reviewed",
            payload_json=json.dumps({"response_accuracy": 0.8}),
            created_at=now - timedelta(hours=2),
        ),
        SimpleNamespace(
            event_type="word_reviewed",
            payload_json=json.dumps({"response_accuracy": 0.6}),
            created_at=now - timedelta(hours=1),
        ),
        SimpleNamespace(
            event_type="conversation_turn",
            payload_json="{}",
            created_at=now - timedelta(minutes=30),
        ),
        SimpleNamespace(
            event_type="conversation_turn",
            payload_json="{}",
            created_at=now - timedelta(minutes=29, seconds=30),
        ),
    ]
    service = ProgressService(
        lambda: FakeUOW(
            items,
            SimpleNamespace(
                skills={"grammar": 0.7, "vocabulary": 0.8, "fluency": 0.65},
                mastery_percent=50.0,
                accuracy_rate=70.0,
                response_speed_seconds=30.0,
            ),
            SimpleNamespace(current_streak=4, momentum_score=0.6, total_sessions=8),
            SimpleNamespace(xp=240, level=1, milestones=[]),
            events,
        )
    )

    progress = run_async(service.build_dashboard(1))

    assert progress["metrics"]["vocabulary_mastery_percent"] == 50.0
    assert progress["metrics"]["accuracy_rate"] == 70.0
    assert progress["metrics"]["response_speed_seconds"] == 30.0
    assert progress["metrics"]["fluency_score"] == 65.0


def test_progress_service_aggregates_daily_weekly_and_trends_correctly():
    now = utc_now()
    items = [SimpleNamespace(review_count=4, ease_factor=2.5, next_review_due=None)]
    events = [
        SimpleNamespace(event_type="word_learned", payload_json="{}", created_at=now - timedelta(hours=3)),
        SimpleNamespace(event_type="word_reviewed", payload_json=json.dumps({"response_accuracy": 0.9}), created_at=now - timedelta(hours=2)),
        SimpleNamespace(event_type="conversation_turn", payload_json="{}", created_at=now - timedelta(hours=1)),
        SimpleNamespace(event_type="word_learned", payload_json="{}", created_at=now - timedelta(days=8)),
        SimpleNamespace(event_type="word_reviewed", payload_json=json.dumps({"response_accuracy": 0.5}), created_at=now - timedelta(days=9)),
        SimpleNamespace(event_type="conversation_turn", payload_json="{}", created_at=now - timedelta(days=10)),
    ]
    service = ProgressService(
        lambda: FakeUOW(
            items,
            SimpleNamespace(
                skills={"grammar": 0.55, "vocabulary": 0.6, "fluency": 0.72},
                mastery_percent=100.0,
                accuracy_rate=78.0,
                response_speed_seconds=12.0,
            ),
            SimpleNamespace(current_streak=2, momentum_score=0.4, total_sessions=3),
            SimpleNamespace(xp=380, level=2, milestones=[2]),
            events,
        )
    )

    progress = run_async(service.build_dashboard(9))

    assert progress["daily"]["words_learned"] == 1
    assert progress["daily"]["reviews_completed"] == 1
    assert progress["weekly"]["messages_sent"] == 1
    assert progress["trends"]["weekly_words_learned_delta"] == 0
    assert progress["trends"]["weekly_reviews_completed_delta"] == 0
    assert progress["trends"]["weekly_messages_sent_delta"] == 0
    assert progress["trends"]["weekly_accuracy_rate_delta"] == 40.0
    assert progress["skill_breakdown"]["fluency"] == 72.0
