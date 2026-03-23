from datetime import timedelta
from types import SimpleNamespace

import pytest

from tests.conftest import run_async
from vocablens.core.time import utc_now
from vocablens.services.conversion_funnel_service import ConversionFunnelService


class FakeEventsRepo:
    def __init__(self, events):
        self.events = events

    async def list_by_user(self, user_id: int, limit: int = 500):
        return [event for event in self.events if event.user_id == user_id][:limit]

    async def list_since(self, since, event_types=None, limit: int = 50000):
        rows = [event for event in self.events if event.created_at >= since]
        if event_types:
            rows = [event for event in rows if event.event_type in event_types]
        return rows[:limit]


class FakeUsersRepo:
    def __init__(self, users):
        self.users = users

    async def list_all(self):
        return self.users


class FakeSubscriptionsRepo:
    def __init__(self, subscriptions):
        self.subscriptions = subscriptions

    async def get_by_user(self, user_id: int):
        return self.subscriptions.get(user_id)


class FakeUOW:
    def __init__(self, *, users=None, events=None, subscriptions=None):
        self.users = FakeUsersRepo(users or [])
        self.events = FakeEventsRepo(events or [])
        self.subscriptions = FakeSubscriptionsRepo(subscriptions or {})

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


class FakePaywallService:
    def __init__(self, decisions):
        self.decisions = decisions

    async def evaluate(self, user_id: int):
        return self.decisions[user_id]


class FakeAnalyticsService:
    async def retention_report(self):
        return {"cohorts": [{"cohort_date": "2026-03-01", "d1_retention": 60.0}]}


class FixedExperimentService:
    def __init__(self, variants):
        self.variants = variants

    def has_experiment(self, experiment_key: str) -> bool:
        return experiment_key in self.variants

    async def assign(self, user_id: int, experiment_key: str) -> str:
        return self.variants[experiment_key]


def _event(user_id: int, event_type: str, days_ago: int = 0, payload=None):
    return SimpleNamespace(
        user_id=user_id,
        event_type=event_type,
        created_at=utc_now() - timedelta(days=days_ago),
        payload=payload or {},
    )


@pytest.mark.parametrize(
    ("events", "subscription", "paywall", "expected_stage"),
    [
        ([_event(1, "session_started")], None, SimpleNamespace(show_paywall=False, paywall_type=None, reason=None, usage_percent=10, trial_recommended=False), "awareness"),
        ([_event(1, "session_started"), _event(1, "message_sent", payload={"wow_moment": True, "wow_score": 0.82})], None, SimpleNamespace(show_paywall=False, paywall_type=None, reason=None, usage_percent=20, trial_recommended=False), "value_realization"),
        ([_event(1, "session_started")], None, SimpleNamespace(show_paywall=False, paywall_type=None, reason="usage pressure high", usage_percent=70, trial_recommended=False), "usage_pressure"),
        ([_event(1, "session_started"), _event(1, "paywall_viewed")], None, SimpleNamespace(show_paywall=True, paywall_type="soft_paywall", reason="usage pressure high", usage_percent=82, trial_recommended=False), "paywall_exposure"),
        ([_event(1, "session_started"), _event(1, "paywall_viewed")], SimpleNamespace(tier="free", trial_tier="pro", trial_ends_at=utc_now() + timedelta(days=3)), SimpleNamespace(show_paywall=True, paywall_type="soft_paywall", reason="wow moment reached", usage_percent=82, trial_recommended=True), "trial"),
        ([_event(1, "session_started"), _event(1, "upgrade_completed")], SimpleNamespace(tier="pro", trial_tier=None, trial_ends_at=None), SimpleNamespace(show_paywall=False, paywall_type=None, reason=None, usage_percent=20, trial_recommended=False), "conversion"),
        ([_event(1, "session_started", days_ago=2), _event(1, "upgrade_completed", days_ago=1), _event(1, "session_started")], SimpleNamespace(tier="pro", trial_tier=None, trial_ends_at=None), SimpleNamespace(show_paywall=False, paywall_type=None, reason=None, usage_percent=20, trial_recommended=False), "retention"),
    ],
)
def test_conversion_funnel_service_transitions_users_through_stages(events, subscription, paywall, expected_stage):
    service = ConversionFunnelService(
        lambda: FakeUOW(users=[SimpleNamespace(id=1)], events=events, subscriptions={1: subscription} if subscription else {}),
        FakePaywallService({1: paywall}),
        FakeAnalyticsService(),
        FixedExperimentService({"paywall_pricing_messaging": "premium_anchor"}),
    )

    state = run_async(service.state(1))

    assert state.stage == expected_stage
    assert state.completed_stages
    if expected_stage in {"usage_pressure", "paywall_exposure", "trial"}:
        assert state.experiment_variant == "premium_anchor"


def test_conversion_funnel_service_reports_stage_metrics():
    users = [SimpleNamespace(id=1), SimpleNamespace(id=2)]
    events = [
        _event(1, "session_started", days_ago=2),
        _event(1, "paywall_viewed", days_ago=1),
        _event(1, "upgrade_completed"),
        _event(2, "session_started", days_ago=2),
    ]
    paywalls = {
        1: SimpleNamespace(show_paywall=True, paywall_type="soft_paywall", reason="usage pressure high", usage_percent=82, trial_recommended=False),
        2: SimpleNamespace(show_paywall=False, paywall_type=None, reason=None, usage_percent=15, trial_recommended=False),
    }
    subscriptions = {
        1: SimpleNamespace(tier="pro", trial_tier=None, trial_ends_at=None),
    }
    service = ConversionFunnelService(
        lambda: FakeUOW(users=users, events=events, subscriptions=subscriptions),
        FakePaywallService(paywalls),
        FakeAnalyticsService(),
    )

    metrics = run_async(service.metrics())

    awareness = next(row for row in metrics.stages if row.stage == "awareness")
    conversion = next(row for row in metrics.stages if row.stage == "conversion")

    assert awareness.users == 2
    assert awareness.conversion_rate == 50.0
    assert conversion.users == 1
    assert metrics.retention_summary["cohorts"][0]["d1_retention"] == 60.0
