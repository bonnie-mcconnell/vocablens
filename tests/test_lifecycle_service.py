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


class FakeNotificationStates:
    def __init__(self):
        self.row = None

    async def get_or_create(self, user_id: int):
        if self.row is None or self.row.user_id != user_id:
            self.row = SimpleNamespace(
                user_id=user_id,
                preferred_channel="push",
                preferred_time_of_day=18,
                frequency_limit=2,
                lifecycle_stage=None,
                lifecycle_policy={},
                suppression_reason=None,
                suppressed_until=None,
                cooldown_until=None,
                sent_count_day=None,
                sent_count_today=0,
                last_sent_at=None,
                last_delivery_channel=None,
                last_delivery_status=None,
                last_delivery_category=None,
                last_reference_id=None,
                last_decision_at=None,
                last_decision_reason=None,
                updated_at=None,
            )
        return self.row

    async def update(self, user_id: int, **kwargs):
        row = await self.get_or_create(user_id)
        for key, value in kwargs.items():
            if value is not None:
                setattr(row, key, value)
        return row


class FakeNotificationSuppressionEvents:
    def __init__(self):
        self.created = []

    async def create(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(**kwargs)


class FakeNotificationPolicyRegistries:
    async def get(self, policy_key: str):
        return SimpleNamespace(
            policy_key=policy_key,
            status="active",
            is_killed=False,
            policy={
                "cooldown_hours": 4,
                "default_frequency_limit": 2,
                "default_preferred_time_of_day": 18,
                "stage_policies": {
                    "new_user": {"lifecycle_notifications_enabled": True, "suppression_reason": None, "recovery_window_hours": 0},
                    "activating": {"lifecycle_notifications_enabled": True, "suppression_reason": None, "recovery_window_hours": 0},
                    "engaged": {"lifecycle_notifications_enabled": False, "suppression_reason": "engaged stage suppresses proactive lifecycle messaging", "recovery_window_hours": 24},
                    "at_risk": {"lifecycle_notifications_enabled": True, "suppression_reason": None, "recovery_window_hours": 0},
                    "churned": {"lifecycle_notifications_enabled": True, "suppression_reason": None, "recovery_window_hours": 0},
                },
                "suppression_overrides": [
                    {
                        "source_context": "lifecycle_service.notification",
                        "stage": "engaged",
                        "lifecycle_notifications_enabled": False,
                        "suppression_reason": "engaged stage suppresses proactive lifecycle messaging",
                        "recovery_window_hours": 24,
                    }
                ],
            },
        )


class FakeUOW:
    def __init__(self, learning_state, engagement_state):
        self.learning_states = FakeLearningStates(learning_state)
        self.engagement_states = FakeEngagementStates(engagement_state)
        self.decision_traces = FakeDecisionTraces()
        self.lifecycle_states = FakeLifecycleStates()
        self.lifecycle_transitions = FakeLifecycleTransitions()
        self.notification_states = FakeNotificationStates()
        self.notification_suppression_events = FakeNotificationSuppressionEvents()
        self.notification_policy_registries = FakeNotificationPolicyRegistries()

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
        self.created = []

    async def create(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(**kwargs)


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

    async def decide(self, user_id: int, retention, *, reference_id: str | None = None, source_context: str = ""):
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


class FakeLifecycleHealthSignalService:
    def __init__(self):
        self.calls = []

    async def evaluate_scope(self, scope_key: str = "global"):
        self.calls.append(scope_key)
        return {"scope_key": scope_key}


class FakeLifecycleNotificationStateService:
    def __init__(self, uow):
        self._uow = uow

    async def apply_lifecycle_policy(
        self,
        *,
        user_id: int,
        lifecycle_stage: str,
        source: str,
        reference_id: str | None,
    ):
        row = await self._uow.notification_states.get_or_create(user_id)
        stage_policies = (
            await self._uow.notification_policy_registries.get("default")
        ).policy["stage_policies"]
        stage_policy = dict(stage_policies[lifecycle_stage])
        updated = await self._uow.notification_states.update(
            user_id,
            lifecycle_stage=lifecycle_stage,
            lifecycle_policy={
                "lifecycle_notifications_enabled": stage_policy["lifecycle_notifications_enabled"],
                "recovery_window_hours": stage_policy["recovery_window_hours"],
            },
            suppression_reason=stage_policy["suppression_reason"],
        )
        await self._uow.notification_suppression_events.create(
            user_id=user_id,
            event_type="lifecycle_policy_updated",
            source=source,
            reference_id=reference_id,
            policy_key="default",
            policy_version="v1",
            lifecycle_stage=lifecycle_stage,
            suppression_reason=stage_policy["suppression_reason"],
            suppressed_until=None,
            payload=dict(updated.lifecycle_policy or {}),
        )
        return updated


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
    uow = FakeUOW(learning_state, engagement_state)
    health_signals = FakeLifecycleHealthSignalService()
    service = LifecycleService(
        lambda: uow,
        FakeRetentionEngine(assessment),
        FakeProgressService(progress),
        notifier,
        FakePaywallService(paywall),
        notification_state_service=FakeLifecycleNotificationStateService(uow),
        lifecycle_health_signal_service=health_signals,
    )
    return service, notifier, uow, health_signals


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
    service, _, _, health_signals = _service(
        sessions=sessions,
        assessment=assessment,
        progress=progress,
    )

    plan = run_async(service.evaluate(42))

    assert plan.stage == expected_stage
    assert plan.reasons
    assert health_signals.calls == ["global", expected_stage]


def test_lifecycle_service_triggers_onboarding_and_wow_moment_actions():
    new_user_service, new_user_notifier, new_user_uow, new_user_health = _service(
        sessions=1,
        assessment=_assessment(),
        progress=_progress(accuracy=82.0, mastery=15.0, fluency=64.0),
    )
    activating_service, activating_notifier, activating_uow, activating_health = _service(
        sessions=3,
        assessment=_assessment(),
        progress=_progress(accuracy=63.0, mastery=25.0, fluency=57.0),
    )

    new_user_plan = run_async(new_user_service.evaluate(1))
    activating_plan = run_async(activating_service.evaluate(2))

    assert [action.type for action in new_user_plan.actions] == ["onboarding_nudge", "quick_start_path"]
    assert new_user_notifier.calls == [(1, "active")]
    assert new_user_uow.decision_traces.created[0]["trace_type"] == "lifecycle_action_plan"
    assert new_user_uow.decision_traces.created[1]["trace_type"] == "lifecycle_transition"
    assert new_user_uow.decision_traces.created[2]["trace_type"] == "lifecycle_decision"
    assert new_user_uow.decision_traces.created[2]["reference_id"] == "lifecycle:1"
    assert new_user_uow.lifecycle_states.row.current_stage == "new_user"
    assert new_user_uow.lifecycle_transitions.created[0]["to_stage"] == "new_user"
    assert new_user_uow.notification_states.row.lifecycle_policy["lifecycle_notifications_enabled"] is True
    assert new_user_health.calls == ["global", "new_user"]
    assert activating_plan.actions[0].type == "wow_moment_push"
    assert "mastery at 25.0%" in activating_plan.actions[1].message
    assert activating_notifier.calls == [(2, "active")]
    assert activating_uow.decision_traces.created[0]["outputs"]["action_types"] == ["wow_moment_push", "progress_visibility"]
    assert activating_uow.decision_traces.created[1]["outputs"]["current_stage"] == "activating"
    assert activating_uow.decision_traces.created[2]["outputs"]["stage"] == "activating"
    assert activating_uow.lifecycle_states.row.current_stage == "activating"
    assert activating_health.calls == ["global", "activating"]


def test_lifecycle_service_triggers_reengagement_and_limits_retention_actions():
    assessment = _assessment(
        state="at-risk",
        suggested_actions=[
            RetentionAction(kind="review_reminder", reason="3 reviews pending", target="hola"),
            RetentionAction(kind="quick_session", reason="Try a 2 minute session"),
            RetentionAction(kind="streak_nudge", reason="Keep the streak alive"),
        ],
    )
    service, notifier, uow, health_signals = _service(
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
    assert uow.decision_traces.created[2]["inputs"]["retention"]["suggested_action_types"] == [
        "review_reminder",
        "quick_session",
        "streak_nudge",
    ]
    assert uow.decision_traces.created[1]["trace_type"] == "lifecycle_transition"
    assert uow.decision_traces.created[2]["trace_type"] == "lifecycle_decision"
    assert health_signals.calls == ["global", "at_risk"]


def test_lifecycle_service_engaged_stage_surfaces_paywall_without_proactive_notification():
    paywall = SimpleNamespace(
        show_paywall=True,
        paywall_type="soft_paywall",
        reason="usage pressure high",
        usage_percent=82,
        allow_access=True,
    )
    service, notifier, uow, health_signals = _service(
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
    assert uow.decision_traces.created[0]["trace_type"] == "lifecycle_action_plan"
    assert uow.decision_traces.created[1]["trace_type"] == "lifecycle_transition"
    assert uow.decision_traces.created[2]["outputs"]["paywall"]["type"] == "soft_paywall"
    assert uow.decision_traces.created[2]["reason"] == "user shows strong engagement and progress"
    assert uow.notification_states.row.lifecycle_policy["lifecycle_notifications_enabled"] is False
    assert uow.notification_suppression_events.created[0]["event_type"] == "lifecycle_policy_updated"
    assert health_signals.calls == ["global", "engaged"]
