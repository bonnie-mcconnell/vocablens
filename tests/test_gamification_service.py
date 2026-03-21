from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.services.gamification_service import GamificationService


class FakeEventsRepo:
    def __init__(self, events):
        self.events = list(events)

    async def list_by_user(self, user_id: int, limit: int = 5000):
        return [event for event in self.events if event.user_id == user_id][:limit]


class FakeUOW:
    def __init__(self, events, engagement_state=None, progress_state=None):
        self.events = FakeEventsRepo(events)
        self.engagement_states = SimpleNamespace(get_or_create=self._get_engagement_state)
        self.progress_states = SimpleNamespace(get_or_create=self._get_progress_state)
        self._engagement_state = engagement_state or SimpleNamespace(
            current_streak=7,
            longest_streak=12,
            total_sessions=1,
            interaction_stats={
                "messages_sent": 10,
                "lessons_completed": 5,
                "reviews_completed": 1,
                "progress_shares": 1,
            },
        )
        self._progress_state = progress_state or SimpleNamespace(xp=645, level=3, milestones=[2, 3])

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None

    async def _get_engagement_state(self, user_id: int):
        return self._engagement_state

    async def _get_progress_state(self, user_id: int):
        return self._progress_state


class FakeProgressService:
    def __init__(self, *, mastery=52.0, accuracy=88.0, fluency=71.0):
        self.mastery = mastery
        self.accuracy = accuracy
        self.fluency = fluency

    async def build_dashboard(self, user_id: int):
        return {
            "metrics": {
                "vocabulary_mastery_percent": self.mastery,
                "accuracy_rate": self.accuracy,
                "fluency_score": self.fluency,
            }
        }


class FakeRetentionEngine:
    def __init__(self, *, current_streak=7, longest_streak=12):
        self.current_streak = current_streak
        self.longest_streak = longest_streak

    async def assess_user(self, user_id: int):
        return SimpleNamespace(
            current_streak=self.current_streak,
            longest_streak=self.longest_streak,
        )


class FakeEventService:
    def __init__(self):
        self.events = []

    async def track_event(self, user_id: int, event_type: str, payload: dict | None = None):
        self.events.append(
            SimpleNamespace(user_id=user_id, event_type=event_type, payload=payload or {})
        )


def _event(user_id: int, event_type: str, payload=None):
    return SimpleNamespace(user_id=user_id, event_type=event_type, payload=payload or {})


def test_gamification_service_builds_xp_level_badges_and_milestones():
    events = [
        _event(1, "session_started"),
        _event(1, "message_sent"),
        _event(1, "message_sent"),
        _event(1, "message_sent"),
        _event(1, "message_sent"),
        _event(1, "message_sent"),
        _event(1, "message_sent"),
        _event(1, "message_sent"),
        _event(1, "message_sent"),
        _event(1, "message_sent"),
        _event(1, "message_sent"),
        _event(1, "lesson_completed"),
        _event(1, "lesson_completed"),
        _event(1, "lesson_completed"),
        _event(1, "lesson_completed"),
        _event(1, "lesson_completed"),
        _event(1, "review_completed"),
        _event(1, "referral_reward_granted", {"xp_reward": 300}),
        _event(1, "progress_shared"),
    ]
    service = GamificationService(
        lambda: FakeUOW(events),
        FakeProgressService(),
        FakeRetentionEngine(current_streak=7, longest_streak=12),
    )

    profile = run_async(service.summary(1))

    assert profile.xp == 645
    assert profile.level == 3
    assert profile.streak_milestones_reached == [3, 7]
    assert profile.next_streak_milestone == 14
    badge_keys = {badge.key for badge in profile.badges}
    assert {
        "first_session",
        "conversation_starter",
        "lesson_climber",
        "accuracy_ace",
        "mastery_builder",
        "streak_keeper",
        "streak_master",
        "share_your_win",
    }.issubset(badge_keys)


def test_gamification_service_refresh_emits_only_new_achievements():
    events = [
        _event(1, "session_started"),
        _event(1, "message_sent"),
        _event(1, "message_sent"),
        _event(1, "message_sent"),
        _event(1, "message_sent"),
        _event(1, "message_sent"),
        _event(1, "message_sent"),
        _event(1, "message_sent"),
        _event(1, "message_sent"),
        _event(1, "message_sent"),
        _event(1, "message_sent"),
        _event(1, "lesson_completed"),
        _event(1, "lesson_completed"),
        _event(1, "lesson_completed"),
        _event(1, "lesson_completed"),
        _event(1, "lesson_completed"),
        _event(1, "badge_unlocked", {"badge": "first_session"}),
        _event(1, "streak_milestone_reached", {"milestone": 3}),
    ]
    event_service = FakeEventService()
    service = GamificationService(
        lambda: FakeUOW(
            events,
            engagement_state=SimpleNamespace(
                current_streak=7,
                longest_streak=9,
                total_sessions=1,
                interaction_stats={
                    "messages_sent": 10,
                    "lessons_completed": 5,
                    "reviews_completed": 0,
                    "progress_shares": 0,
                },
            ),
            progress_state=SimpleNamespace(xp=160, level=1, milestones=[]),
        ),
        FakeProgressService(),
        FakeRetentionEngine(current_streak=7, longest_streak=9),
        event_service,
    )

    result = run_async(service.refresh(1))

    assert [milestone for milestone in result["new_streak_milestones"]] == [7]
    emitted_types = [event.event_type for event in event_service.events]
    assert emitted_types.count("badge_unlocked") >= 1
    assert "streak_milestone_reached" in emitted_types
    assert "xp_awarded" in emitted_types
