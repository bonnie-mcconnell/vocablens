from datetime import timedelta
from types import SimpleNamespace

import pytest

from tests.conftest import run_async
from vocablens.core.time import utc_now
from vocablens.services.lifecycle_service import LifecycleService
from vocablens.services.retention_engine import RetentionAction, RetentionAssessment


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


class FakeUOW:
    def __init__(self, learning_state, engagement_state):
        self.learning_states = FakeLearningStates(learning_state)
        self.engagement_states = FakeEngagementStates(engagement_state)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


class FakeProgressService:
    def __init__(self, progress):
        self.progress = progress

    async def build_dashboard(self, user_id: int):
        return self.progress


class FakeRetentionEngine:
    def __init__(self, assessment):
        self.assessment = assessment

    async def assess_user(self, user_id: int):
        return self.assessment


class FakeNotificationEngine:
    def __init__(self, decision=None):
        self.decision = decision or SimpleNamespace(
            should_send=True,
            reason="send lifecycle message",
            channel="push",
            send_at=utc_now(),
            message=SimpleNamespace(category="retention:review_reminder"),
        )
        self.calls = []

    async def decide(self, user_id: int, retention):
        self.calls.append((user_id, retention.state))
        return self.decision


class FakePaywallService:
    def __init__(self, decision=None):
        self.decision = decision or SimpleNamespace(
            show_paywall=False,
            paywall_type=None,
            reason=None,
            usage_percent=0,
            allow_access=True,
        )

    async def evaluate(self, user_id: int):
        return self.decision


def _progress(*, accuracy: float, mastery: float, fluency: float) -> dict:
    return {
        "metrics": {
            "accuracy_rate": accuracy,
            "vocabulary_mastery_percent": mastery,
            "fluency_score": fluency,
        }
    }


def _assessment(
    *,
    state: str = "active",
    is_high_engagement: bool = False,
    suggested_actions: list[RetentionAction] | None = None,
) -> RetentionAssessment:
    return RetentionAssessment(
        state=state,
        drop_off_risk=0.2,
        session_frequency=3.0,
        current_streak=2,
        longest_streak=4,
        last_active_at=utc_now() - timedelta(hours=2),
        is_high_engagement=is_high_engagement,
        suggested_actions=suggested_actions or [],
    )


def _service(
    *,
    sessions: int,
    assessment: RetentionAssessment,
    progress: dict,
    paywall=None,
    notification=None,
) -> tuple[LifecycleService, FakeNotificationEngine]:
    notifier = notification or FakeNotificationEngine()
    learning_state = SimpleNamespace(
        skills={
            "grammar": float(progress["metrics"]["accuracy_rate"]) / 100,
            "fluency": float(progress["metrics"]["fluency_score"]) / 100,
        },
        weak_areas=[],
        mastery_percent=float(progress["metrics"]["vocabulary_mastery_percent"]),
    )
    engagement_state = SimpleNamespace(total_sessions=sessions)
    service = LifecycleService(
        lambda: FakeUOW(learning_state, engagement_state),
        FakeRetentionEngine(assessment),
        FakeProgressService(progress),
        notifier,
        FakePaywallService(paywall),
    )
    return service, notifier


@pytest.mark.parametrize(
    ("sessions", "assessment", "progress", "expected_stage"),
    [
        (1, _assessment(), _progress(accuracy=90.0, mastery=50.0, fluency=80.0), "new_user"),
        (3, _assessment(), _progress(accuracy=68.0, mastery=20.0, fluency=58.0), "activating"),
        (6, _assessment(is_high_engagement=True), _progress(accuracy=88.0, mastery=65.0, fluency=82.0), "engaged"),
        (4, _assessment(state="at-risk"), _progress(accuracy=84.0, mastery=45.0, fluency=70.0), "at_risk"),
        (6, _assessment(state="churned"), _progress(accuracy=84.0, mastery=45.0, fluency=70.0), "churned"),
    ],
)
def test_lifecycle_service_classifies_users_correctly(sessions, assessment, progress, expected_stage):
    service, _ = _service(
        sessions=sessions,
        assessment=assessment,
        progress=progress,
    )

    plan = run_async(service.evaluate(42))

    assert plan.stage == expected_stage
    assert plan.reasons


def test_lifecycle_service_triggers_onboarding_and_wow_moment_actions():
    new_user_service, new_user_notifier = _service(
        sessions=1,
        assessment=_assessment(),
        progress=_progress(accuracy=82.0, mastery=15.0, fluency=64.0),
    )
    activating_service, activating_notifier = _service(
        sessions=3,
        assessment=_assessment(),
        progress=_progress(accuracy=63.0, mastery=25.0, fluency=57.0),
    )

    new_user_plan = run_async(new_user_service.evaluate(1))
    activating_plan = run_async(activating_service.evaluate(2))

    assert [action.type for action in new_user_plan.actions] == ["onboarding_nudge", "quick_start_path"]
    assert new_user_notifier.calls == [(1, "active")]
    assert activating_plan.actions[0].type == "wow_moment_push"
    assert "mastery at 25.0%" in activating_plan.actions[1].message
    assert activating_notifier.calls == [(2, "active")]


def test_lifecycle_service_triggers_reengagement_and_limits_retention_actions():
    assessment = _assessment(
        state="at-risk",
        suggested_actions=[
            RetentionAction(kind="review_reminder", reason="3 reviews pending", target="hola"),
            RetentionAction(kind="quick_session", reason="Try a 2 minute session"),
            RetentionAction(kind="streak_nudge", reason="Keep the streak alive"),
        ],
    )
    service, notifier = _service(
        sessions=5,
        assessment=assessment,
        progress=_progress(accuracy=78.0, mastery=42.0, fluency=71.0),
    )

    plan = run_async(service.evaluate(7))

    assert plan.stage == "at_risk"
    assert [action.type for action in plan.actions] == [
        "reengagement_flow",
        "review_reminder",
        "quick_session",
    ]
    assert plan.notification.should_send is True
    assert plan.notification.category == "retention:review_reminder"
    assert notifier.calls == [(7, "at-risk")]


def test_lifecycle_service_engaged_stage_surfaces_paywall_without_proactive_notification():
    paywall = SimpleNamespace(
        show_paywall=True,
        paywall_type="soft_paywall",
        reason="usage pressure high",
        usage_percent=82,
        allow_access=True,
    )
    service, notifier = _service(
        sessions=7,
        assessment=_assessment(is_high_engagement=True),
        progress=_progress(accuracy=91.0, mastery=68.0, fluency=84.0),
        paywall=paywall,
    )

    plan = run_async(service.evaluate(11))

    assert plan.stage == "engaged"
    assert [action.type for action in plan.actions] == ["monetization_prompt", "paywall_follow_up"]
    assert plan.paywall.usage_percent == 82
    assert plan.notification.should_send is False
    assert notifier.calls == []
