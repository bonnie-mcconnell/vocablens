from datetime import timedelta
from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.core.time import utc_now
from vocablens.services.notification_decision_engine import NotificationDecisionEngine


class FakeProfilesRepo:
    def __init__(self, profile):
        self.profile = profile

    async def get_or_create(self, user_id: int):
        return self.profile


class FakeNotificationDeliveryRepo:
    def __init__(self, deliveries=None):
        self.deliveries = deliveries or []

    async def list_recent(self, user_id: int, limit: int = 50):
        return self.deliveries[:limit]


class FakeLearningEventsRepo:
    def __init__(self, events=None):
        self.events = events or []

    async def list_since(self, user_id: int, since):
        return self.events


class FakeKnowledgeGraphRepo:
    def __init__(self, weak_clusters=None):
        self.weak_clusters = weak_clusters or []

    async def get_weak_clusters(self, user_id: int):
        return self.weak_clusters


class FakeMistakePatternsRepo:
    def __init__(self, mistakes=None):
        self.mistakes = mistakes or []

    async def top_patterns(self, user_id: int, limit: int = 3):
        return self.mistakes[:limit]


class FakeUOW:
    def __init__(self, profile, deliveries=None, events=None, weak_clusters=None, mistakes=None):
        self.profiles = FakeProfilesRepo(profile)
        self.notification_deliveries = FakeNotificationDeliveryRepo(deliveries)
        self.learning_events = FakeLearningEventsRepo(events)
        self.knowledge_graph = FakeKnowledgeGraphRepo(weak_clusters)
        self.mistake_patterns = FakeMistakePatternsRepo(mistakes)
        self.decision_traces = FakeDecisionTraces()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


class FakeDecisionTraces:
    def __init__(self):
        self.created = []

    async def create(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(**kwargs)


def test_notification_decision_engine_respects_daily_limit_and_prevents_spam():
    now = utc_now()
    profile = SimpleNamespace(preferred_channel="push", preferred_time_of_day=18, frequency_limit=1)
    deliveries = [SimpleNamespace(created_at=now - timedelta(hours=2))]
    assessment = SimpleNamespace(
        state="at-risk",
        drop_off_risk=0.7,
        current_streak=3,
        suggested_actions=[SimpleNamespace(kind="streak_nudge", reason="Keep it going", target=None)],
    )
    uow = FakeUOW(profile, deliveries=deliveries)
    engine = NotificationDecisionEngine(lambda: uow)

    decision = run_async(engine.decide(1, assessment))

    assert decision.should_send is False
    assert "limit" in decision.reason
    assert uow.decision_traces.created[0]["trace_type"] == "notification_selection"
    assert uow.decision_traces.created[0]["outputs"]["should_send"] is False


def test_notification_decision_engine_prioritizes_streak_over_review():
    profile = SimpleNamespace(preferred_channel="push", preferred_time_of_day=18, frequency_limit=3)
    assessment = SimpleNamespace(
        state="at-risk",
        drop_off_risk=0.55,
        current_streak=5,
        suggested_actions=[
            SimpleNamespace(kind="review_reminder", reason="3 reviews waiting", target="hola"),
            SimpleNamespace(kind="streak_nudge", reason="Your streak is alive", target=None),
        ],
    )
    uow = FakeUOW(
        profile,
        weak_clusters=[{"cluster": "travel"}],
        mistakes=[SimpleNamespace(pattern="verb tense")],
    )
    engine = NotificationDecisionEngine(lambda: uow)

    decision = run_async(engine.decide(2, assessment))

    assert decision.should_send is True
    assert decision.message is not None
    assert decision.message.category == "retention:streak_nudge"
    assert decision.message.metadata["priority"] > 0
    assert uow.decision_traces.created[0]["inputs"]["selected_action"]["kind"] == "streak_nudge"
    assert uow.decision_traces.created[0]["outputs"]["message_category"] == "retention:streak_nudge"


def test_notification_decision_engine_uses_session_history_for_send_time():
    profile = SimpleNamespace(preferred_channel="email", preferred_time_of_day=None, frequency_limit=3, last_active_at=None)
    session_events = [
        SimpleNamespace(created_at=utc_now().replace(hour=9, minute=10, second=0, microsecond=0)),
        SimpleNamespace(created_at=utc_now().replace(hour=10, minute=5, second=0, microsecond=0)),
        SimpleNamespace(created_at=utc_now().replace(hour=11, minute=20, second=0, microsecond=0)),
    ]
    assessment = SimpleNamespace(
        state="churned",
        drop_off_risk=0.8,
        current_streak=0,
        suggested_actions=[SimpleNamespace(kind="review_reminder", reason="Come back to review", target="bonjour")],
    )
    uow = FakeUOW(profile, events=session_events)
    engine = NotificationDecisionEngine(lambda: uow)

    decision = run_async(engine.decide(3, assessment))

    assert decision.should_send is True
    assert decision.channel == "email"
    assert decision.send_at.hour == 10
    assert uow.decision_traces.created[0]["inputs"]["session_history"]["predicted_hour"] == 10
