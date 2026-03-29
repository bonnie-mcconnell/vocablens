from datetime import timedelta
from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.core.time import utc_now
from vocablens.services.lifecycle_service import LifecycleService
from vocablens.services.onboarding_service import OnboardingService


class FakeEventsRepo:
    def __init__(self, events):
        self.events = events

    async def list_by_user(self, user_id: int, limit: int = 100):
        return self.events[:limit]


class FakeUOW:
    def __init__(self, events):
        self.events = FakeEventsRepo(events)
        self.learning_states = SimpleNamespace(get_or_create=self._learning_state)
        self.engagement_states = SimpleNamespace(get_or_create=self._engagement_state)
        self.lifecycle_states = FakeLifecycleStates()
        self.lifecycle_transitions = FakeLifecycleTransitions()
        self.decision_traces = SimpleNamespace(create=self._create_decision_trace)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None

    async def _create_decision_trace(self, **kwargs):
        return None

    async def _learning_state(self, user_id: int):
        return SimpleNamespace(
            skills={"grammar": 0.45, "vocabulary": 0.12, "fluency": 0.35},
            weak_areas=[],
            mastery_percent=12.0,
        )

    async def _engagement_state(self, user_id: int):
        return SimpleNamespace(total_sessions=1)


class FakeProgressService:
    def __init__(self, progress):
        self.progress = progress

    async def build_dashboard(self, user_id: int):
        return self.progress


class FakeWowEngine:
    def __init__(self, wow):
        self.wow = wow
        self.calls = []

    async def score_session(self, user_id: int, **kwargs):
        self.calls.append((user_id, kwargs))
        return self.wow


class FakeGlobalDecisionEngine:
    def __init__(self, decision, user_state=None):
        self.decision = decision
        self.user_state = user_state

    async def decide(self, user_id: int):
        return self.decision

    async def user_experience_state(self, user_id: int):
        return self.user_state


class FakeRetentionEngine:
    def __init__(self, assessment):
        self.assessment = assessment

    async def assess_user(self, user_id: int):
        return self.assessment


class FakeNotificationEngine:
    def __init__(self):
        self.decision = SimpleNamespace(
            should_send=True,
            reason="retention action selected",
            channel="push",
            send_at=utc_now(),
            message=SimpleNamespace(category="retention:streak_nudge"),
        )

    async def decide(self, user_id: int, retention, *, reference_id: str | None = None, source_context: str = ""):
        return self.decision


class FakeLifecycleStates:
    def __init__(self):
        self.row = None

    async def get(self, user_id: int):
        if self.row is None or self.row.user_id != user_id:
            return None
        return self.row

    async def create(self, **kwargs):
        self.row = SimpleNamespace(**kwargs)
        return self.row

    async def update(self, user_id: int, **kwargs):
        for key, value in kwargs.items():
            if value is not None:
                setattr(self.row, key, value)
        return self.row


class FakeLifecycleTransitions:
    def __init__(self):
        self.rows = []

    async def create(self, **kwargs):
        row = SimpleNamespace(**kwargs)
        self.rows.append(row)
        return row


class FakePaywallService:
    def __init__(self):
        self.decision = SimpleNamespace(
            show_paywall=False,
            paywall_type=None,
            reason=None,
            usage_percent=0,
            allow_access=True,
        )

    async def evaluate(self, user_id: int):
        return self.decision


class FakeLifecycleHealthSignalService:
    async def evaluate_scope(self, scope_key: str = "global"):
        return {"scope_key": scope_key}


class FakeLifecycleNotificationStateService:
    async def apply_lifecycle_policy(
        self,
        *,
        user_id: int,
        lifecycle_stage: str,
        source: str,
        reference_id: str | None,
    ):
        return SimpleNamespace(
            user_id=user_id,
            lifecycle_stage=lifecycle_stage,
            lifecycle_policy={"lifecycle_notifications_enabled": True},
            suppression_reason=None,
        )


def _progress(accuracy: float, *, words: int = 0, reviews: int = 0) -> dict:
    return {
        "metrics": {
            "accuracy_rate": accuracy,
            "vocabulary_mastery_percent": 12.0,
            "fluency_score": 35.0,
        },
        "daily": {
            "words_learned": words,
            "reviews_completed": reviews,
            "messages_sent": 1,
        },
    }


def _wow(score: float, qualifies: bool):
    return SimpleNamespace(
        score=score,
        qualifies=qualifies,
        triggers={"paywall": qualifies, "trial": score >= 0.8, "upsell": score >= 0.72},
    )


def test_onboarding_service_progresses_from_start_to_guided_and_first_success():
    decision = SimpleNamespace(
        primary_action="conversation",
        difficulty_level="medium",
        session_type="quick",
        engagement_action="habit_nudge",
    )
    start_service = OnboardingService(
        lambda: FakeUOW([SimpleNamespace(event_type="session_started")]),
        FakeProgressService(_progress(40.0)),
        FakeWowEngine(_wow(0.0, False)),
        FakeGlobalDecisionEngine(decision),
    )
    guided_service = OnboardingService(
        lambda: FakeUOW([SimpleNamespace(event_type="session_started")]),
        FakeProgressService(_progress(52.0)),
        FakeWowEngine(_wow(0.0, False)),
        FakeGlobalDecisionEngine(decision),
    )
    success_service = OnboardingService(
        lambda: FakeUOW([SimpleNamespace(event_type="session_started")]),
        FakeProgressService(_progress(78.0)),
        FakeWowEngine(_wow(0.0, False)),
        FakeGlobalDecisionEngine(decision),
    )

    start_plan = run_async(start_service.plan(1))
    guided_plan = run_async(guided_service.plan(2, goals=["travel"]))
    success_plan = run_async(success_service.plan(3, goals=["conversation"]))

    assert start_plan.stage == "onboarding_start"
    assert start_plan.goals_prompt is not None
    assert start_plan.recommended_difficulty == "easy"
    assert guided_plan.stage == "guided_learning"
    assert guided_plan.guided_flow[0].type == "goal_capture"
    assert success_plan.stage == "first_success"
    assert success_plan.first_win.ensure_success is True


def test_onboarding_service_triggers_wow_moment_and_habit_hook():
    decision = SimpleNamespace(
        primary_action="conversation",
        difficulty_level="medium",
        session_type="quick",
        engagement_action="streak_push",
    )
    wow_engine = FakeWowEngine(_wow(0.84, True))
    wow_service = OnboardingService(
        lambda: FakeUOW([SimpleNamespace(event_type="session_started")]),
        FakeProgressService(_progress(65.0)),
        wow_engine,
        FakeGlobalDecisionEngine(decision),
    )
    habit_service = OnboardingService(
        lambda: FakeUOW([SimpleNamespace(event_type="session_started")]),
        FakeProgressService(_progress(65.0, words=1)),
        wow_engine,
        FakeGlobalDecisionEngine(decision),
    )

    wow_plan = run_async(
        wow_service.plan(
            5,
            goals=["conversation"],
            session_snapshot={
                "tutor_mode": True,
                "correction_feedback_count": 3,
                "new_words_count": 2,
                "grammar_mistake_count": 0,
                "session_turn_count": 4,
                "reply_length": 180,
            },
        )
    )
    habit_plan = run_async(
        habit_service.plan(
            6,
            goals=["conversation"],
            session_snapshot={
                "tutor_mode": True,
                "correction_feedback_count": 3,
                "new_words_count": 2,
                "grammar_mistake_count": 0,
                "session_turn_count": 4,
                "reply_length": 180,
            },
        )
    )

    assert wow_plan.stage == "wow_moment"
    assert wow_plan.wow.triggered is True
    assert habit_plan.stage == "habit_hook"
    assert habit_plan.habit_hook.show_streak_starting is True
    assert wow_engine.calls


def test_onboarding_service_prefers_canonical_new_user_stage_when_available():
    decision = SimpleNamespace(
        primary_action="conversation",
        difficulty_level="hard",
        session_type="deep",
        engagement_action="habit_nudge",
    )
    service = OnboardingService(
        lambda: FakeUOW([
            SimpleNamespace(event_type="session_started"),
            SimpleNamespace(event_type="session_started"),
            SimpleNamespace(event_type="session_started"),
        ]),
        FakeProgressService(_progress(85.0)),
        FakeWowEngine(_wow(0.0, False)),
        FakeGlobalDecisionEngine(decision, user_state=SimpleNamespace(lifecycle_stage="new_user")),
    )

    plan = run_async(service.plan(12))

    assert plan.stage == "onboarding_start"
    assert plan.recommended_difficulty == "easy"


def test_lifecycle_service_includes_onboarding_actions_for_new_users():
    onboarding = OnboardingService(
        lambda: FakeUOW([SimpleNamespace(event_type="session_started")]),
        FakeProgressService(_progress(45.0)),
        FakeWowEngine(_wow(0.0, False)),
        FakeGlobalDecisionEngine(
            SimpleNamespace(
                primary_action="conversation",
                difficulty_level="easy",
                session_type="quick",
                monetization_action="none",
                engagement_action="habit_nudge",
                lifecycle_stage="new_user",
                reason="New users need activation and a fast wow moment.",
            )
        ),
    )
    lifecycle = LifecycleService(
        lambda: FakeUOW([SimpleNamespace(event_type="session_started")]),
        FakeRetentionEngine(
            SimpleNamespace(
                state="active",
                drop_off_risk=0.2,
                session_frequency=1.0,
                current_streak=0,
                longest_streak=0,
                last_active_at=utc_now() - timedelta(hours=1),
                is_high_engagement=False,
                suggested_actions=[],
            )
        ),
        FakeProgressService(_progress(45.0)),
        FakeNotificationEngine(),
        FakePaywallService(),
        FakeGlobalDecisionEngine(
            SimpleNamespace(
                primary_action="conversation",
                difficulty_level="easy",
                session_type="quick",
                monetization_action="none",
                engagement_action="habit_nudge",
                lifecycle_stage="new_user",
                reason="New users need activation and a fast wow moment.",
            )
        ),
        onboarding,
        notification_state_service=FakeLifecycleNotificationStateService(),
        lifecycle_health_signal_service=FakeLifecycleHealthSignalService(),
    )

    plan = run_async(lifecycle.evaluate(9))

    assert plan.stage == "new_user"
    assert any(action.type == "goal_capture" for action in plan.actions)
