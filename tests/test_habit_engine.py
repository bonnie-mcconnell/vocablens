from datetime import timedelta
from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.core.time import utc_now
from vocablens.services.habit_engine import HabitEngine
from vocablens.services.retention_engine import RetentionAction, RetentionAssessment


class FakeRetentionEngine:
    def __init__(self, assessment):
        self.assessment = assessment

    async def assess_user(self, user_id: int):
        return self.assessment


class FakeNotificationEngine:
    def __init__(self, decision):
        self.decision = decision
        self.calls = []

    async def decide(self, user_id: int, assessment):
        self.calls.append((user_id, assessment.state))
        return self.decision


class FakeProgressService:
    def __init__(self, progress):
        self.progress = progress

    async def build_dashboard(self, user_id: int):
        return self.progress


def _assessment(state: str = "at-risk", suggested_actions=None) -> RetentionAssessment:
    return RetentionAssessment(
        state=state,
        drop_off_risk=0.52 if state == "at-risk" else 0.18,
        session_frequency=1.2 if state == "at-risk" else 3.4,
        current_streak=3,
        longest_streak=5,
        last_active_at=utc_now() - timedelta(days=1),
        is_high_engagement=state == "active",
        suggested_actions=suggested_actions or [],
    )


def _progress() -> dict:
    return {
        "due_reviews": 4,
        "metrics": {
            "accuracy_rate": 78.0,
            "vocabulary_mastery_percent": 41.0,
            "fluency_score": 69.0,
        },
        "daily": {
            "words_learned": 1,
            "reviews_completed": 2,
            "messages_sent": 1,
        },
        "weekly": {
            "reviews_completed": 7,
        },
        "trends": {
            "weekly_accuracy_rate_delta": 6.5,
        },
    }


def test_habit_engine_executes_notification_to_quick_session_loop():
    assessment = _assessment(
        suggested_actions=[
            RetentionAction(kind="streak_nudge", reason="Keep the streak alive"),
            RetentionAction(kind="quick_session", reason="Take a short review burst", target="review"),
        ]
    )
    notification = SimpleNamespace(
        should_send=True,
        send_at=utc_now(),
        channel="push",
        cooldown_until=None,
        message=SimpleNamespace(category="retention:streak_nudge"),
        reason="retention action selected",
    )
    engine = HabitEngine(
        FakeRetentionEngine(assessment),
        FakeNotificationEngine(notification),
        FakeProgressService(_progress()),
    )

    plan = run_async(engine.execute(12))

    assert plan.trigger.type == "notification"
    assert plan.trigger.streak_reminder is True
    assert plan.action.type == "quick_session"
    assert plan.action.duration_minutes == 3
    assert plan.reward.progress_increase == 2
    assert plan.reward.streak_boost == 4
    assert "78.0% accuracy" in plan.reward.feedback
    assert plan.repeat.should_repeat is True
    assert plan.repeat.cadence == "daily"


def test_habit_engine_falls_back_to_passive_trigger_and_low_friction_action():
    assessment = _assessment(
        state="active",
        suggested_actions=[],
    )
    notification = SimpleNamespace(
        should_send=False,
        send_at=utc_now(),
        channel="push",
        cooldown_until=None,
        message=None,
        reason="cooldown active",
    )
    progress = _progress()
    progress["due_reviews"] = 0
    progress["daily"]["reviews_completed"] = 0
    progress["daily"]["words_learned"] = 0
    progress["trends"]["weekly_accuracy_rate_delta"] = 0.0
    engine = HabitEngine(
        FakeRetentionEngine(assessment),
        FakeNotificationEngine(notification),
        FakeProgressService(progress),
    )

    plan = run_async(engine.execute(7))

    assert plan.trigger.type == "passive_reentry"
    assert plan.action.duration_minutes == 2
    assert plan.action.target == "conversation"
    assert plan.reward.progress_increase == 0
    assert plan.reward.streak_boost == 4
    assert plan.repeat.next_best_trigger == "streak_reminder"
