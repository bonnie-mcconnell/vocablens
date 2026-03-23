from datetime import timedelta
from types import SimpleNamespace

import pytest

from tests.conftest import run_async
from vocablens.core.time import utc_now
from vocablens.services.global_decision_engine import GlobalDecisionEngine
from vocablens.services.habit_engine import HabitEngine
from vocablens.services.learning_engine import LearningEngine
from vocablens.services.lifecycle_service import LifecycleService
from vocablens.services.notification_decision_engine import NotificationDecision
from vocablens.services.retention_engine import RetentionAssessment


class FakeLearningStates:
    def __init__(self, state):
        self.state = state

    async def get_or_create(self, user_id: int):
        return self.state


class FakeEngagementStates:
    def __init__(self, state):
        self.state = state

    async def get_or_create(self, user_id: int):
        return self.state


class FakeDecisionUOW:
    def __init__(self, *, learning_state, engagement_state):
        self.learning_states = FakeLearningStates(learning_state)
        self.engagement_states = FakeEngagementStates(engagement_state)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


class FakeRetentionEngine:
    def __init__(self, assessment):
        self.assessment = assessment

    async def assess_user(self, user_id: int):
        return self.assessment


class FakeProgressService:
    def __init__(self, progress):
        self.progress = progress

    async def build_dashboard(self, user_id: int):
        return self.progress


class FakeSubscriptionService:
    def __init__(self, features=None):
        self.features = features or SimpleNamespace(tier="free", personalization_level="standard")

    async def get_features(self, user_id: int):
        return self.features

    async def record_feature_gate(self, **kwargs):
        return None


class FakePaywallService:
    def __init__(self, decision=None):
        self.decision = decision or SimpleNamespace(
            show_paywall=False,
            paywall_type=None,
            reason=None,
            usage_percent=0,
            allow_access=True,
            trial_recommended=False,
            upsell_recommended=False,
        )

    async def evaluate(self, user_id: int):
        return self.decision


class FakeNotificationEngine:
    def __init__(self, decision=None):
        self.decision = decision or NotificationDecision(
            should_send=True,
            send_at=utc_now(),
            channel="push",
            cooldown_until=None,
            message=SimpleNamespace(category="retention:streak_nudge"),
            reason="retention action selected",
        )

    async def decide(self, user_id: int, assessment):
        return self.decision


class FakeGlobalDecisionEngine:
    def __init__(self, decision):
        self.decision = decision
        self.calls = []

    async def decide(self, user_id: int):
        self.calls.append(user_id)
        return self.decision


class FakeLearningAdapterUOW:
    def __init__(self):
        self.decision_traces = SimpleNamespace(
            create=self._create_decision_trace,
        )
        self.events = SimpleNamespace(
            create=self._create_event,
        )
        self.vocab = SimpleNamespace(
            list_due=self._list_due,
        )
        self.learning_states = SimpleNamespace(
            get_or_create=self._learning_state,
        )
        self.engagement_states = SimpleNamespace(
            get_or_create=self._engagement_state,
        )
        self.knowledge_graph = SimpleNamespace(
            get_weak_clusters=self._get_weak_clusters,
        )
        self.mistake_patterns = SimpleNamespace(
            repeated_patterns=self._repeated_patterns,
        )
        self.profiles = SimpleNamespace(
            get_or_create=self._get_or_create,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None

    async def _list_due(self, user_id: int):
        return []

    async def _get_weak_clusters(self, user_id: int):
        return []

    async def _repeated_patterns(self, user_id: int, threshold: int = 2, limit: int = 3):
        return []

    async def _get_or_create(self, user_id: int):
        return SimpleNamespace(
            difficulty_preference="medium",
            retention_rate=0.8,
            content_preference="mixed",
        )

    async def _learning_state(self, user_id: int):
        return SimpleNamespace(
            skills={"grammar": 0.8, "vocabulary": 0.8, "fluency": 0.8},
            weak_areas=[],
            mastery_percent=60.0,
        )

    async def _engagement_state(self, user_id: int):
        return SimpleNamespace(total_sessions=7)

    async def _create_decision_trace(self, **kwargs):
        return None

    async def _create_event(self, **kwargs):
        return None


def _assessment(stage: str) -> RetentionAssessment:
    mapping = {
        "new_user": ("active", 0.2, False),
        "activating": ("active", 0.25, False),
        "engaged": ("active", 0.1, True),
        "at_risk": ("at-risk", 0.6, False),
        "churned": ("churned", 0.9, False),
    }
    state, risk, engaged = mapping[stage]
    return RetentionAssessment(
        state=state,
        drop_off_risk=risk,
        session_frequency=4.5 if engaged else 1.2,
        current_streak=3,
        longest_streak=5,
        last_active_at=utc_now() - timedelta(days=1 if state == "active" else 7),
        is_high_engagement=engaged,
        suggested_actions=[],
    )


def _progress(accuracy: float, mastery: float, fluency: float, due_reviews: int = 0) -> dict:
    return {
        "due_reviews": due_reviews,
        "metrics": {
            "accuracy_rate": accuracy,
            "vocabulary_mastery_percent": mastery,
            "fluency_score": fluency,
        },
        "daily": {"words_learned": 1, "reviews_completed": due_reviews, "messages_sent": 1},
        "weekly": {"reviews_completed": 5},
        "trends": {"weekly_accuracy_rate_delta": 4.0},
    }


def _learning_state_from_progress(progress: dict) -> SimpleNamespace:
    metrics = progress["metrics"]
    return SimpleNamespace(
        skills={
            "grammar": float(metrics["accuracy_rate"]) / 100,
            "vocabulary": min(1.0, float(metrics["vocabulary_mastery_percent"]) / 100),
            "fluency": float(metrics["fluency_score"]) / 100,
        },
        weak_areas=[],
        mastery_percent=float(metrics["vocabulary_mastery_percent"]),
    )


@pytest.mark.parametrize(
    ("stage", "sessions", "progress", "paywall", "expected"),
    [
        ("new_user", 1, _progress(55.0, 10.0, 35.0), None, ("conversation", "quick", "none", "habit_nudge")),
        ("activating", 3, _progress(62.0, 20.0, 58.0, due_reviews=2), None, ("review", "quick", "none", "streak_push")),
        ("engaged", 7, _progress(88.0, 65.0, 82.0), SimpleNamespace(show_paywall=True, paywall_type="soft_paywall", reason="usage", usage_percent=82, allow_access=True, trial_recommended=False, upsell_recommended=True), ("upsell", "deep", "soft_paywall", "streak_push")),
        ("at_risk", 4, _progress(76.0, 44.0, 70.0, due_reviews=3), None, ("review", "quick", "none", "streak_push")),
        ("churned", 6, _progress(72.0, 40.0, 61.0), None, ("nudge", "passive", "none", "streak_push")),
    ],
)
def test_global_decision_engine_outputs_correct_priorities_for_each_stage(stage, sessions, progress, paywall, expected):
    engine = GlobalDecisionEngine(
        lambda: FakeDecisionUOW(
            learning_state=_learning_state_from_progress(progress),
            engagement_state=SimpleNamespace(total_sessions=sessions),
        ),
        FakeRetentionEngine(_assessment(stage)),
        FakeProgressService(progress),
        FakeSubscriptionService(),
        FakePaywallService(paywall),
    )

    decision = run_async(engine.decide(1))

    assert (
        decision.primary_action,
        decision.session_type,
        decision.monetization_action,
        decision.engagement_action,
    ) == expected
    assert decision.lifecycle_stage == stage


def test_global_decision_engine_is_deterministic_for_same_inputs():
    progress = _progress(74.0, 38.0, 63.0, due_reviews=2)
    engine = GlobalDecisionEngine(
        lambda: FakeDecisionUOW(
            learning_state=_learning_state_from_progress(progress),
            engagement_state=SimpleNamespace(total_sessions=4),
        ),
        FakeRetentionEngine(_assessment("at_risk")),
        FakeProgressService(progress),
        FakeSubscriptionService(),
        FakePaywallService(),
    )

    first = run_async(engine.decide(2))
    second = run_async(engine.decide(2))

    assert first == second


def test_learning_lifecycle_and_habit_services_use_global_decision_engine():
    global_decision = SimpleNamespace(
        primary_action="upsell",
        difficulty_level="hard",
        session_type="deep",
        monetization_action="soft_paywall",
        engagement_action="reward_boost",
        lifecycle_stage="engaged",
        reason="Engaged users should see monetization next.",
    )
    global_engine = FakeGlobalDecisionEngine(global_decision)
    retention = FakeRetentionEngine(_assessment("engaged"))
    progress_service = FakeProgressService(_progress(90.0, 70.0, 84.0))
    notification = FakeNotificationEngine(
        NotificationDecision(
            should_send=False,
            send_at=utc_now(),
            channel="push",
            cooldown_until=None,
            message=None,
            reason="stage does not require proactive lifecycle messaging",
        )
    )
    paywall = FakePaywallService(
        SimpleNamespace(
            show_paywall=True,
            paywall_type="soft_paywall",
            reason="usage",
            usage_percent=80,
            allow_access=True,
            trial_recommended=False,
            upsell_recommended=True,
        )
    )
    learning = LearningEngine(
        lambda: FakeLearningAdapterUOW(),
        retention,
        subscription_service=FakeSubscriptionService(),
        global_decision_engine=global_engine,
    )
    lifecycle = LifecycleService(
        lambda: FakeDecisionUOW(
            learning_state=SimpleNamespace(
                skills={"grammar": 0.9, "vocabulary": 0.9, "fluency": 0.84},
                weak_areas=[],
                mastery_percent=70.0,
            ),
            engagement_state=SimpleNamespace(total_sessions=7),
        ),
        retention,
        progress_service,
        notification,
        paywall,
        global_engine,
    )
    habit = HabitEngine(
        retention,
        notification,
        progress_service,
        global_engine,
    )

    learning_decision = run_async(learning.recommend(5))
    lifecycle_plan = run_async(lifecycle.evaluate(5))
    habit_plan = run_async(habit.execute(5))

    assert learning_decision.lesson_difficulty == "hard"
    assert learning_decision.reason == "Engaged users should see monetization next."
    assert lifecycle_plan.stage == "engaged"
    assert habit_plan.action.duration_minutes == 5
    assert global_engine.calls == [5, 5, 5]
