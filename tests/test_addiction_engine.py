from datetime import timedelta
from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.core.time import utc_now
from vocablens.services.addiction_engine import AddictionEngine
from vocablens.services.report_models import HabitAction, HabitRepeat, HabitReward, HabitTrigger


class FakeHabitEngine:
    def __init__(self, plan):
        self.plan = plan

    async def execute(self, user_id: int):
        return self.plan


class FakeRetentionEngine:
    def __init__(self, assessment):
        self.assessment = assessment

    async def assess_user(self, user_id: int):
        return self.assessment


class FakeNotificationEngine:
    def __init__(self, decision):
        self.decision = decision

    async def decide(self, user_id: int, assessment):
        return self.decision


class FakeProgressService:
    def __init__(self, progress):
        self.progress = progress

    async def build_dashboard(self, user_id: int):
        return self.progress


class FakeGlobalDecisionEngine:
    def __init__(self, user_state=None):
        self.user_state = user_state

    async def user_experience_state(self, user_id: int):
        return self.user_state


def _habit_plan():
    return SimpleNamespace(
        trigger=HabitTrigger(
            type="notification",
            channel="push",
            send_at=utc_now().isoformat(),
            category="retention:streak_nudge",
            reason="reminder",
            streak_reminder=True,
        ),
        action=HabitAction(
            type="quick_session",
            duration_minutes=3,
            target="review",
            reason="Keep going",
        ),
        reward=HabitReward(
            progress_increase=2,
            streak_boost=4,
            feedback="Keep going",
        ),
        repeat=HabitRepeat(
            should_repeat=True,
            next_best_trigger="streak_reminder",
            cadence="daily",
        ),
    )


def _assessment(*, streak: int = 3, risk: float = 0.52, last_active_hours_ago: int = 24):
    return SimpleNamespace(
        current_streak=streak,
        drop_off_risk=risk,
        last_active_at=utc_now() - timedelta(hours=last_active_hours_ago),
    )


def _progress(due_reviews: int = 4):
    return {
        "due_reviews": due_reviews,
        "metrics": {"fluency_score": 68.0, "accuracy_rate": 81.0},
        "daily": {"words_learned": 1, "reviews_completed": 2},
    }


def test_addiction_engine_generates_variable_but_deterministic_rewards():
    notification = SimpleNamespace(send_at=utc_now().replace(hour=19, minute=0, second=0, microsecond=0))
    engine = AddictionEngine(
        FakeHabitEngine(_habit_plan()),
        FakeRetentionEngine(_assessment()),
        FakeNotificationEngine(notification),
        FakeProgressService(_progress()),
    )

    first = run_async(engine.execute(11))
    second = run_async(engine.execute(11))
    third = run_async(engine.execute(27))

    assert first.reward == second.reward
    assert first.reward.type in {"bonus_xp", "surprise_streak_boost", "mystery_reward"}
    assert first.reward != third.reward


def test_addiction_engine_applies_streak_pressure_and_identity_reinforcement():
    notification = SimpleNamespace(send_at=utc_now().replace(hour=7, minute=0, second=0, microsecond=0))
    engine = AddictionEngine(
        FakeHabitEngine(_habit_plan()),
        FakeRetentionEngine(_assessment(streak=5, risk=0.7, last_active_hours_ago=30)),
        FakeNotificationEngine(notification),
        FakeProgressService(_progress(due_reviews=5)),
    )

    plan = run_async(engine.execute(4))

    assert plan.pressure.show_streak_decay_warning is True
    assert plan.pressure.will_lose_progress is True
    assert "lose progress" in plan.pressure.warning_message.lower()
    assert "becoming fluent" in plan.identity.message.lower()
    assert plan.ritual.daily_ritual_hour == 7
    assert plan.ritual.streak_anchor == 6


def test_addiction_engine_prefers_canonical_drop_off_risk_when_available():
    notification = SimpleNamespace(send_at=utc_now().replace(hour=12, minute=0, second=0, microsecond=0))
    engine = AddictionEngine(
        FakeHabitEngine(_habit_plan()),
        FakeRetentionEngine(_assessment(streak=4, risk=0.2, last_active_hours_ago=2)),
        FakeNotificationEngine(notification),
        FakeProgressService(_progress(due_reviews=2)),
        global_decision_engine=FakeGlobalDecisionEngine(
            user_state=SimpleNamespace(retention_state="at-risk", drop_off_risk=0.92)
        ),
    )

    plan = run_async(engine.execute(31))

    assert plan.pressure.show_streak_decay_warning is True
    assert plan.pressure.will_lose_progress is True
