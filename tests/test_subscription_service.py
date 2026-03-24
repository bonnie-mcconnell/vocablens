from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.services.subscription_service import SubscriptionService


class FakeSubscriptionsRepo:
    def __init__(self, subscription=None):
        self.subscription = subscription

    async def get_by_user(self, user_id: int):
        return self.subscription

    async def upsert(self, user_id: int, tier: str, request_limit: int, token_limit: int):
        self.subscription = SimpleNamespace(
            user_id=user_id,
            tier=tier,
            request_limit=request_limit,
            token_limit=token_limit,
        )


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
    def __init__(self, subscription=None):
        self.subscriptions = FakeSubscriptionsRepo(subscription)
        self.subscription_events = FakeSubscriptionEventsRepo()
        self.monetization_states = FakeMonetizationStatesRepo()
        self.monetization_offer_events = FakeMonetizationOfferEventsRepo()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


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


def test_subscription_service_returns_tier_features_and_tracks_upgrade():
    uow = FakeUOW(SimpleNamespace(tier="pro", request_limit=1000, token_limit=300000))
    service = SubscriptionService(lambda: uow)

    features = run_async(service.get_features(1))
    upgraded = run_async(service.upgrade_tier(1, "premium"))
    metrics = run_async(service.conversion_metrics())

    assert features.tier == "pro"
    assert features.tutor_depth == "standard"
    assert upgraded.tier == "premium"
    assert metrics.counts_by_event["tier_upgraded"] == 1
    assert uow.monetization_offer_events.recorded[0]["event_type"] == "upgrade_completed"
    assert uow.monetization_states.updated[0]["paywall_acceptances"] == 1


def test_subscription_service_records_feature_gate_metrics():
    uow = FakeUOW(SimpleNamespace(tier="free", request_limit=100, token_limit=50000))
    service = SubscriptionService(lambda: uow)

    run_async(
        service.record_feature_gate(
            user_id=7,
            feature_name="tutor_depth",
            allowed=False,
            current_tier="free",
            required_tier="premium",
        )
    )
    metrics = run_async(service.conversion_metrics())

    assert metrics.counts_by_event["feature_gate_blocked"] == 1
