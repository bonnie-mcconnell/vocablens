from __future__ import annotations

from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.services.monetization_state_service import MonetizationStateService


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


class FakeUOW:
    def __init__(self):
        self.monetization_states = FakeMonetizationStatesRepo()
        self.monetization_offer_events = FakeMonetizationOfferEventsRepo()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


def test_monetization_state_service_syncs_latest_decision():
    uow = FakeUOW()
    service = MonetizationStateService(lambda: uow)
    decision = SimpleNamespace(
        show_paywall=True,
        offer_type="trial",
        paywall_type="soft_paywall",
        strategy="high_intent:early:value_anchor:trial:us",
        lifecycle_stage="activating",
        trial_days=5,
        pricing=SimpleNamespace(monthly_price=20.0),
        trigger=SimpleNamespace(trigger_reason="wow moment reached"),
        value_display=SimpleNamespace(locked_progress_percent=41),
    )

    run_async(service.sync_decision(user_id=1, decision=decision, geography="us"))

    assert uow.monetization_states.updated[0]["current_offer_type"] == "trial"
    assert uow.monetization_states.updated[0]["conversion_propensity"] > 0
    assert uow.monetization_offer_events.recorded[0]["event_type"] == "decision_evaluated"


def test_monetization_state_service_records_dismissal_and_cooldown():
    uow = FakeUOW()
    service = MonetizationStateService(lambda: uow)

    run_async(
        service.record_response(
            user_id=1,
            event_type="paywall_dismissed",
            offer_type="discount",
            paywall_type="soft_paywall",
            strategy="low_engagement:late:discount",
            geography="nz",
            payload={"source": "test"},
        )
    )

    assert uow.monetization_states.updated[0]["paywall_dismissals"] == 1
    assert uow.monetization_states.updated[0]["fatigue_score"] == 2
    assert uow.monetization_offer_events.recorded[0]["event_type"] == "paywall_dismissed"
