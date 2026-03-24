from datetime import timedelta
from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.core.time import utc_now
from vocablens.services.paywall_service import PaywallService
from vocablens.services.subscription_service import SubscriptionService


class FakeSubscriptionsRepo:
    def __init__(self, subscription=None):
        self.subscription = subscription
        self.started_trial = None
        self.cleared_trial = False

    async def get_by_user(self, user_id: int):
        return self.subscription

    async def start_trial(self, *, user_id: int, tier: str, request_limit: int, token_limit: int, duration_days: int):
        now = utc_now()
        self.started_trial = {
            "user_id": user_id,
            "tier": tier,
            "request_limit": request_limit,
            "token_limit": token_limit,
            "duration_days": duration_days,
        }
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
        if self.subscription:
            self.subscription.trial_started_at = None
            self.subscription.trial_ends_at = None
            self.subscription.trial_tier = None
        return self.subscription

    async def upsert(self, user_id: int, tier: str, request_limit: int, token_limit: int):
        self.subscription = SimpleNamespace(
            user_id=user_id,
            tier=tier,
            request_limit=request_limit,
            token_limit=token_limit,
            trial_started_at=None,
            trial_ends_at=None,
            trial_tier=None,
        )


class FakeUsageLogsRepo:
    def __init__(self, used_requests: int = 0, used_tokens: int = 0):
        self.used_requests = used_requests
        self.used_tokens = used_tokens

    async def totals_for_user_day(self, user_id: int):
        return self.used_requests, self.used_tokens


class FakeEventsRepo:
    def __init__(self, events=None):
        self._events = events or []

    async def list_by_user(self, user_id: int, limit: int = 200):
        return self._events[:limit]


class FakeSubscriptionEventsRepo:
    def __init__(self):
        self.events = []

    async def record(self, **kwargs):
        self.events.append(kwargs)

    async def counts_by_event(self):
        counts = {}
        for event in self.events:
            counts[event["event_type"]] = counts.get(event["event_type"], 0) + 1
        return counts


class FakeUOW:
    def __init__(self, subscription=None, used_requests: int = 0, used_tokens: int = 0, events=None):
        self.subscriptions = FakeSubscriptionsRepo(subscription)
        self.usage_logs = FakeUsageLogsRepo(used_requests, used_tokens)
        self.events = FakeEventsRepo(events)
        self.subscription_events = FakeSubscriptionEventsRepo()
        self.monetization_states = FakeMonetizationStatesRepo()
        self.monetization_offer_events = FakeMonetizationOfferEventsRepo()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


class FakeEventService:
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


class FakeMonetizationOfferEventsRepo:
    def __init__(self):
        self.recorded = []

    async def record(self, **kwargs):
        self.recorded.append(kwargs)
        return SimpleNamespace(**kwargs)


def test_paywall_trigger_correctness_for_sessions_usage_and_wow_moment():
    events = [SimpleNamespace(event_type="session_started") for _ in range(3)]
    tracker = FakeEventService()
    uow = FakeUOW(
        subscription=SimpleNamespace(tier="free", request_limit=100, token_limit=50000, trial_tier=None, trial_ends_at=None),
        used_requests=80,
        used_tokens=1000,
        events=events,
    )
    service = PaywallService(lambda: uow, tracker)

    decision = run_async(service.evaluate(1, wow_moment=True))

    assert decision.show_paywall is True
    assert decision.paywall_type == "soft_paywall"
    assert decision.reason in {"wow moment reached", "session trigger reached", "usage pressure high"}
    assert decision.usage_percent == 80
    assert tracker.calls[0][1] == "paywall_viewed"


def test_paywall_trial_lifecycle_activates_and_expires():
    uow = FakeUOW(subscription=None)
    paywall = PaywallService(lambda: uow)
    subscription_service = SubscriptionService(lambda: uow, paywall_service=paywall)

    features = run_async(subscription_service.start_trial(7, duration_days=5))

    assert uow.subscriptions.started_trial["duration_days"] == 5
    assert features.trial_active is True
    assert features.tier == "pro"
    assert uow.monetization_offer_events.recorded[0]["event_type"] == "trial_started"
    assert uow.monetization_states.updated[0]["paywall_acceptances"] == 1

    expired = SimpleNamespace(
        tier="free",
        request_limit=1000,
        token_limit=300000,
        trial_tier="pro",
        trial_ends_at=utc_now() - timedelta(minutes=1),
    )
    expiring_uow = FakeUOW(subscription=expired)
    expired_paywall = PaywallService(lambda: expiring_uow)

    decision = run_async(expired_paywall.evaluate(8))

    assert decision.trial_active is False
    assert expiring_uow.subscriptions.cleared_trial is True


def test_subscription_service_enforces_hard_paywall_gating():
    overloaded = SimpleNamespace(tier="free", request_limit=100, token_limit=50000, trial_tier=None, trial_ends_at=None)
    uow = FakeUOW(subscription=overloaded, used_requests=100, used_tokens=50000, events=[])
    paywall = PaywallService(lambda: uow)
    service = SubscriptionService(lambda: uow, paywall_service=paywall)

    features = run_async(service.get_features(3))

    assert features.paywall_type == "hard_paywall"
    assert features.allow_access is False
