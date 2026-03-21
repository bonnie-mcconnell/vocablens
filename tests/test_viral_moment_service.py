import json
from datetime import timedelta
from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.core.time import utc_now
from vocablens.services.viral_moment_service import ViralMomentService


class FakeUsersRepo:
    def __init__(self, users):
        self.users = list(users)

    async def list_all(self):
        return list(self.users)


class FakeLearningEventsRepo:
    def __init__(self, events_by_user):
        self.events_by_user = events_by_user

    async def list_since(self, user_id: int, since):
        return list(self.events_by_user.get(user_id, []))


class FakeUOW:
    def __init__(self, users, events_by_user):
        self.users = FakeUsersRepo(users)
        self.learning_events = FakeLearningEventsRepo(events_by_user)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


class FakeProgressService:
    def __init__(self, dashboards):
        self.dashboards = dashboards

    async def build_dashboard(self, user_id: int):
        return self.dashboards[user_id]


class FakeGamificationService:
    async def summary(self, user_id: int):
        return SimpleNamespace(current_streak=7, level=3, xp=645, badges=[SimpleNamespace(label="Streak Master")])


def _event(event_type: str, payload: dict, days_ago: int = 0):
    return SimpleNamespace(
        event_type=event_type,
        payload_json=json.dumps(payload),
        created_at=utc_now() - timedelta(days=days_ago),
    )


def test_viral_moment_service_outputs_are_deterministic():
    users = [SimpleNamespace(id=1), SimpleNamespace(id=2), SimpleNamespace(id=3)]
    dashboards = {
        1: {"metrics": {"vocabulary_mastery_percent": 61.4, "accuracy_rate": 84.8}},
        2: {"metrics": {"vocabulary_mastery_percent": 40.0, "accuracy_rate": 62.0}},
        3: {"metrics": {"vocabulary_mastery_percent": 20.0, "accuracy_rate": 51.0}},
    }
    events = {
        1: [
            _event("word_reviewed", {"response_accuracy": 0.45}, days_ago=25),
            _event("word_reviewed", {"response_accuracy": 0.5}, days_ago=24),
            _event("conversation_turn", {"message": "I used to struggle, but now I can explain my weekend plans clearly.", "mistakes": {"grammar_mistakes": []}}, days_ago=1),
        ]
    }
    service = ViralMomentService(
        lambda: FakeUOW(users, events),
        FakeProgressService(dashboards),
        FakeGamificationService(),
    )

    first = run_async(service.generate_share_moments(1))
    second = run_async(service.generate_share_moments(1))

    assert first == second
    assert len(first) >= 3


def test_viral_moment_service_prioritizes_high_engagement_formats():
    users = [SimpleNamespace(id=1), SimpleNamespace(id=2)]
    dashboards = {
        1: {"metrics": {"vocabulary_mastery_percent": 88.0, "accuracy_rate": 92.0}},
        2: {"metrics": {"vocabulary_mastery_percent": 25.0, "accuracy_rate": 58.0}},
    }
    events = {
        1: [
            _event("word_reviewed", {"response_accuracy": 0.4}, days_ago=20),
            _event("word_reviewed", {"response_accuracy": 0.45}, days_ago=19),
            _event("conversation_turn", {"message": "I can confidently describe complex travel delays and rebook plans in Spanish now.", "mistakes": {"grammar_mistakes": []}}, days_ago=1),
        ]
    }
    service = ViralMomentService(
        lambda: FakeUOW(users, events),
        FakeProgressService(dashboards),
        FakeGamificationService(),
    )

    moments = run_async(service.generate_share_moments(1))

    assert moments[0].type in {"before_after", "hard_sentence_mastered", "percentile"}
    assert any(moment.type == "streak_flex" for moment in moments)
    assert any(moment.type == "hard_sentence_mastered" for moment in moments)
