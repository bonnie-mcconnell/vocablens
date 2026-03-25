from datetime import timedelta
from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.core.time import utc_now
from vocablens.services.adaptive_paywall_service import AdaptivePaywallService


class FakeSubscriptionsRepo:
    def __init__(self, subscription=None):
        self.subscription = subscription
        self.started_trial = None
        self.cleared_trial = False

    async def get_by_user(self, user_id: int):
        return self.subscription

    async def start_trial(self, *, user_id: int, tier: str, request_limit: int, token_limit: int, duration_days: int):
        self.started_trial = {
            "user_id": user_id,
            "tier": tier,
            "request_limit": request_limit,
            "token_limit": token_limit,
            "duration_days": duration_days,
        }
        now = utc_now()
        self.subscription = SimpleNamespace(
            user_id=user_id,
            tier="free",
            request_limit=request_limit,
            token_limit=token_limit,
            trial_started_at=now,
            trial_ends_at=now + timedelta(days=duration_days),
            trial_tier=tier,
        )
        return self.subscription

    async def clear_trial(self, user_id: int):
        self.cleared_trial = True
        return None


class FakeEventsRepo:
    def __init__(self, events=None, since_events=None):
        self.events = events or []
        self.since_events = since_events or self.events

    async def list_by_user(self, user_id: int, limit: int = 250):
        return [event for event in self.events if getattr(event, "user_id", user_id) == user_id][:limit]

    async def list_since(self, since, event_types=None, limit: int = 50000):
        rows = [event for event in self.since_events if event.created_at >= since]
        if event_types:
            rows = [event for event in rows if event.event_type in event_types]
        return rows[:limit]


class FakeUsageLogsRepo:
    def __init__(self, used_requests: int, used_tokens: int):
        self.used_requests = used_requests
        self.used_tokens = used_tokens

    async def totals_for_user_day(self, user_id: int):
        return self.used_requests, self.used_tokens


class FakeProfilesRepo:
    def __init__(self, profile):
        self.profile = profile

    async def get_or_create(self, user_id: int):
        return self.profile


class FakeUOW:
    def __init__(self, *, subscription=None, events=None, since_events=None, used_requests=0, used_tokens=0, profile=None):
        self.subscriptions = FakeSubscriptionsRepo(subscription)
        self.events = FakeEventsRepo(events, since_events)
        self.usage_logs = FakeUsageLogsRepo(used_requests, used_tokens)
        self.profiles = FakeProfilesRepo(
            profile or SimpleNamespace(drop_off_risk=0.2, session_frequency=3.0)
        )
        self.monetization_states = FakeMonetizationStatesRepo()
        self.monetization_offer_events = FakeMonetizationOfferEventsRepo()
        self.monetization_health_states = FakeMonetizationHealthStatesRepo()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


class FixedExperimentService:
    def __init__(self, assignments):
        self.assignments = assignments

    async def has_experiment(self, experiment_key: str) -> bool:
        return experiment_key in self.assignments

    async def assign(self, user_id: int, experiment_key: str) -> str:
        return self.assignments[experiment_key]


class FakeEventTracker:
    def __init__(self):
        self.calls = []

    async def track_event(self, user_id: int, event_type: str, payload: dict | None = None):
        self.calls.append((user_id, event_type, payload or {}))


class FakeMonetizationStatesRepo:
    def __init__(self):
        self.row = SimpleNamespace(
            trial_eligible=True,
            fatigue_score=0,
            trial_started_at=None,
            trial_ends_at=None,
        )
        self.updated = []

    async def get_or_create(self, user_id: int):
        return self.row

    async def update(self, user_id: int, **kwargs):
        for key, value in kwargs.items():
            setattr(self.row, key, value)
        self.updated.append(kwargs)
        return self.row

    async def list_all(self):
        return [self.row]


class FakeMonetizationOfferEventsRepo:
    def __init__(self):
        self.recorded = []

    async def record(self, **kwargs):
        self.recorded.append(kwargs)
        return SimpleNamespace(**kwargs)

    async def list_all(self, geography: str | None = None, limit: int | None = None):
        return []


class FakeMonetizationHealthStatesRepo:
    def __init__(self):
        self.row = None

    async def get(self, scope_key: str):
        return self.row if self.row and self.row.scope_key == scope_key else None

    async def list_all(self):
        return [self.row] if self.row is not None else []

    async def upsert(self, *, scope_key: str, current_status: str, latest_alert_codes: list[str], metrics: dict):
        self.row = SimpleNamespace(
            scope_key=scope_key,
            current_status=current_status,
            latest_alert_codes=list(latest_alert_codes),
            metrics=dict(metrics),
            last_evaluated_at=None,
        )
        return self.row


def test_adaptive_paywall_service_is_more_aggressive_for_high_intent_users():
    tracker = FakeEventTracker()
    events = [
        SimpleNamespace(user_id=1, event_type="session_started", created_at=utc_now() - timedelta(hours=3)),
        SimpleNamespace(user_id=1, event_type="session_started", created_at=utc_now() - timedelta(hours=2)),
        SimpleNamespace(user_id=1, event_type="upgrade_clicked", created_at=utc_now() - timedelta(hours=1)),
    ]
    uow = FakeUOW(
        subscription=SimpleNamespace(tier="free", request_limit=100, token_limit=50000, trial_tier=None, trial_ends_at=None),
        events=events,
        used_requests=45,
        profile=SimpleNamespace(drop_off_risk=0.15, session_frequency=4.2),
    )
    service = AdaptivePaywallService(
        lambda: uow,
        tracker,
        FixedExperimentService(
            {
                "paywall_trigger_timing": "early",
                "paywall_trial_length": "trial_5d",
                "paywall_pricing_messaging": "value_anchor",
            }
        ),
    )

    decision = run_async(service.evaluate(1))

    assert decision.show_paywall is True
    assert decision.user_segment == "high_intent"
    assert decision.reason == "adaptive session trigger reached"
    assert decision.trigger_variant == "early"
    assert decision.pricing_variant == "value_anchor"
    assert decision.trial_days == 5
    assert decision.trial_recommended is False
    assert tracker.calls[0][1] == "paywall_viewed"
    assert tracker.calls[0][2]["strategy"] == "high_intent:early:value_anchor"
    assert uow.monetization_states.updated[0]["paywall_impressions"] == 1
    assert uow.monetization_offer_events.recorded[0]["event_type"] == "paywall_impression"


def test_adaptive_paywall_service_delays_paywall_for_low_engagement_users():
    tracker = FakeEventTracker()
    events = [
        SimpleNamespace(user_id=2, event_type="session_started", created_at=utc_now() - timedelta(hours=2)),
        SimpleNamespace(user_id=2, event_type="message_sent", created_at=utc_now() - timedelta(hours=1)),
    ]
    uow = FakeUOW(
        subscription=SimpleNamespace(tier="free", request_limit=100, token_limit=50000, trial_tier=None, trial_ends_at=None),
        events=events,
        used_requests=45,
        profile=SimpleNamespace(drop_off_risk=0.6, session_frequency=0.8),
    )
    service = AdaptivePaywallService(
        lambda: uow,
        tracker,
        FixedExperimentService(
            {
                "paywall_trigger_timing": "late",
                "paywall_trial_length": "trial_7d",
                "paywall_pricing_messaging": "standard",
            }
        ),
    )

    decision = run_async(service.evaluate(2))

    assert decision.show_paywall is False
    assert decision.user_segment == "low_engagement"
    assert decision.trial_days == 7
    assert tracker.calls == []


def test_adaptive_paywall_service_uses_experiment_trial_length():
    tracker = FakeEventTracker()
    uow = FakeUOW(
        subscription=None,
        events=[],
        profile=SimpleNamespace(drop_off_risk=0.2, session_frequency=2.0),
    )
    service = AdaptivePaywallService(
        lambda: uow,
        tracker,
        FixedExperimentService(
            {
                "paywall_trial_length": "trial_7d",
            }
        ),
    )

    run_async(service.start_trial(9))

    assert uow.subscriptions.started_trial["duration_days"] == 7


def test_adaptive_paywall_service_reports_conversion_rate_per_strategy():
    now = utc_now()
    tracker = FakeEventTracker()
    since_events = [
        SimpleNamespace(
            user_id=1,
            event_type="paywall_viewed",
            payload={"strategy": "high_intent:early:value_anchor"},
            created_at=now - timedelta(days=2),
        ),
        SimpleNamespace(
            user_id=1,
            event_type="upgrade_completed",
            payload={},
            created_at=now - timedelta(days=1),
        ),
        SimpleNamespace(
            user_id=2,
            event_type="paywall_viewed",
            payload={"strategy": "low_engagement:late:standard"},
            created_at=now - timedelta(days=2),
        ),
    ]
    uow = FakeUOW(
        subscription=None,
        events=[],
        since_events=since_events,
        profile=SimpleNamespace(drop_off_risk=0.2, session_frequency=2.0),
    )
    service = AdaptivePaywallService(lambda: uow, tracker)

    report = run_async(service.conversion_metrics())

    high_intent = next(row for row in report.strategies if row.strategy == "high_intent:early:value_anchor")
    low_engagement = next(row for row in report.strategies if row.strategy == "low_engagement:late:standard")

    assert high_intent.views == 1
    assert high_intent.upgrades == 1
    assert high_intent.conversion_rate == 100.0
    assert low_engagement.views == 1
    assert low_engagement.upgrades == 0
    assert low_engagement.conversion_rate == 0.0


def test_adaptive_paywall_service_uses_wow_score_for_trial_and_upsell_recommendations():
    tracker = FakeEventTracker()
    uow = FakeUOW(
        subscription=SimpleNamespace(tier="free", request_limit=100, token_limit=50000, trial_tier=None, trial_ends_at=None),
        events=[],
        used_requests=10,
        profile=SimpleNamespace(drop_off_risk=0.2, session_frequency=2.2),
    )
    service = AdaptivePaywallService(lambda: uow, tracker)

    decision = run_async(service.evaluate(15, wow_score=0.86))

    assert decision.show_paywall is True
    assert decision.reason == "wow moment reached"
    assert decision.wow_score == 0.86
    assert decision.trial_recommended is True
    assert decision.upsell_recommended is True
