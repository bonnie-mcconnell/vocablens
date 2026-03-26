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

    async def list_by_policy(self, policy_key: str, limit: int = 100):
        return []


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


class FakeNotificationStatesRepo:
    def __init__(self, state=None):
        self.state = state or SimpleNamespace(
            user_id=0,
            preferred_channel="push",
            preferred_time_of_day=18,
            frequency_limit=2,
            lifecycle_policy={},
            suppression_reason=None,
            suppressed_until=None,
            cooldown_until=None,
            sent_count_day=None,
            sent_count_today=0,
            last_decision_at=None,
            last_decision_reason=None,
            last_reference_id=None,
        )

    async def get_or_create(self, user_id: int):
        self.state.user_id = user_id
        return self.state

    async def update(self, user_id: int, **kwargs):
        self.state.user_id = user_id
        for key, value in kwargs.items():
            if value is not None:
                setattr(self.state, key, value)
        return self.state


class FakeNotificationSuppressionEventsRepo:
    def __init__(self):
        self.created = []

    async def create(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(**kwargs)

    async def list_by_policy(self, policy_key: str, limit: int = 100):
        return []


class FakeNotificationPolicyAuditsRepo:
    async def list_by_policy(self, policy_key: str, limit: int = 50):
        return []

    async def latest_for_policy(self, policy_key: str):
        return None


class FakeNotificationPolicyHealthStatesRepo:
    def __init__(self):
        self.rows = {}

    async def get(self, policy_key: str):
        return self.rows.get(policy_key)

    async def list_all(self):
        return list(self.rows.values())

    async def upsert(self, *, policy_key: str, current_status: str, latest_alert_codes: list[str], metrics: dict):
        row = SimpleNamespace(
            policy_key=policy_key,
            current_status=current_status,
            latest_alert_codes=list(latest_alert_codes),
            metrics=dict(metrics),
        )
        self.rows[policy_key] = row
        return row


class FakeNotificationPolicyRegistryRepo:
    async def get(self, policy_key: str):
        return SimpleNamespace(
            policy_key=policy_key,
            status="active",
            is_killed=False,
            description="Default notification policy.",
            created_at=None,
            updated_at=None,
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

    async def list_all(self):
        return [await self.get("default")]


class FakeUOW:
    def __init__(self, profile, deliveries=None, events=None, weak_clusters=None, mistakes=None, notification_state=None):
        self.profiles = FakeProfilesRepo(profile)
        self.notification_deliveries = FakeNotificationDeliveryRepo(deliveries)
        self.notification_states = FakeNotificationStatesRepo(notification_state)
        self.notification_suppression_events = FakeNotificationSuppressionEventsRepo()
        self.notification_policy_registries = FakeNotificationPolicyRegistryRepo()
        self.notification_policy_audits = FakeNotificationPolicyAuditsRepo()
        self.notification_policy_health_states = FakeNotificationPolicyHealthStatesRepo()
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

    async def list_recent(self, *, user_id=None, trace_type: str | None = None, reference_id: str | None = None, limit: int = 100):
        rows = list(self.created)
        if trace_type is not None:
            rows = [row for row in rows if row.get("trace_type") == trace_type]
        if reference_id is not None:
            rows = [row for row in rows if row.get("reference_id") == reference_id]
        if user_id is not None:
            rows = [row for row in rows if row.get("user_id") == user_id]
        return [SimpleNamespace(**row) for row in rows[:limit]]


def test_notification_decision_engine_respects_daily_limit_and_prevents_spam():
    now = utc_now()
    profile = SimpleNamespace(preferred_channel="push", preferred_time_of_day=18, frequency_limit=1)
    notification_state = SimpleNamespace(
        user_id=1,
        preferred_channel="push",
        preferred_time_of_day=18,
        frequency_limit=1,
        lifecycle_policy={},
        suppression_reason=None,
        suppressed_until=None,
        cooldown_until=None,
        sent_count_day=now.date().isoformat(),
        sent_count_today=1,
        last_decision_at=None,
        last_decision_reason=None,
        last_reference_id=None,
    )
    assessment = SimpleNamespace(
        state="at-risk",
        drop_off_risk=0.7,
        current_streak=3,
        suggested_actions=[SimpleNamespace(kind="streak_nudge", reason="Keep it going", target=None)],
    )
    uow = FakeUOW(profile, deliveries=[], notification_state=notification_state)
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


def test_notification_decision_engine_respects_canonical_lifecycle_suppression():
    profile = SimpleNamespace(preferred_channel="push", preferred_time_of_day=18, frequency_limit=3)
    notification_state = SimpleNamespace(
        user_id=4,
        preferred_channel="push",
        preferred_time_of_day=18,
        frequency_limit=3,
        lifecycle_stage="engaged",
        lifecycle_policy={"lifecycle_notifications_enabled": False},
        suppression_reason="engaged stage suppresses proactive lifecycle messaging",
        suppressed_until=None,
        cooldown_until=None,
        sent_count_day=None,
        sent_count_today=0,
        last_decision_at=None,
        last_decision_reason=None,
        last_reference_id=None,
    )
    assessment = SimpleNamespace(
        state="active",
        drop_off_risk=0.2,
        current_streak=4,
        suggested_actions=[SimpleNamespace(kind="review_reminder", reason="Review is ready", target="hola")],
    )
    uow = FakeUOW(profile, notification_state=notification_state)
    engine = NotificationDecisionEngine(lambda: uow)

    decision = run_async(
        engine.decide(
            4,
            assessment,
            reference_id="lifecycle:4",
            source_context="lifecycle_service.notification",
        )
    )

    assert decision.should_send is False
    assert decision.reason == "engaged stage suppresses proactive lifecycle messaging"
    assert uow.decision_traces.created[0]["inputs"]["notification_state"]["lifecycle_policy"]["lifecycle_notifications_enabled"] is False
    assert uow.decision_traces.created[0]["inputs"]["evaluated_constraints"]["source_context"] == "lifecycle_service.notification"
    assert uow.decision_traces.created[0]["outputs"]["suppressed_until"] is None
