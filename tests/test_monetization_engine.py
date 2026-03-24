from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.services.monetization_engine import MonetizationEngine


class FakeAdaptivePaywallService:
    def __init__(self, decision):
        self.decision = decision
        self.calls = []

    async def evaluate(self, user_id: int, *, wow_score: float | None = None):
        self.calls.append({"user_id": user_id, "wow_score": wow_score})
        return self.decision


class FakeBusinessMetricsService:
    def __init__(self, *, ltv: float = 240.0):
        self.ltv = ltv

    async def dashboard(self):
        return {
            "revenue": {
                "mrr": 1200.0,
                "arpu": 24.0,
                "arpu_all_users": 6.0,
                "ltv": self.ltv,
                "paying_users": 50,
            }
        }


class FakeOnboardingFlowService:
    def __init__(self, state=None):
        self.state = state
        self.calls = []

    async def current_state(self, user_id: int):
        self.calls.append(user_id)
        return self.state


class FakeLifecycleService:
    def __init__(self, plan):
        self.plan = plan
        self.calls = []

    async def evaluate(self, user_id: int):
        self.calls.append(user_id)
        return self.plan


class FakeStateRepo:
    def __init__(self, state):
        self.state = state

    async def get_or_create(self, user_id: int):
        return self.state


class FakeUOW:
    def __init__(self, learning_state, engagement_state, progress_state):
        self.learning_states = FakeStateRepo(learning_state)
        self.engagement_states = FakeStateRepo(engagement_state)
        self.progress_states = FakeStateRepo(progress_state)
        self.decision_traces = FakeDecisionTraces()
        self.monetization_states = FakeMonetizationStates()
        self.monetization_offer_events = FakeMonetizationOfferEvents()

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


class FakeMonetizationStates:
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


class FakeMonetizationOfferEvents:
    def __init__(self):
        self.recorded = []

    async def record(self, **kwargs):
        self.recorded.append(kwargs)
        return SimpleNamespace(**kwargs)


def _paywall_decision(
    *,
    show_paywall: bool = True,
    paywall_type: str | None = "soft_paywall",
    reason: str | None = "adaptive session trigger reached",
    usage_percent: int = 72,
    user_segment: str = "high_intent",
    strategy: str = "high_intent:early:value_anchor",
    trigger_variant: str = "early",
    pricing_variant: str = "value_anchor",
    trial_days: int = 5,
    trial_recommended: bool = False,
    trial_active: bool = False,
):
    return SimpleNamespace(
        show_paywall=show_paywall,
        paywall_type=paywall_type,
        reason=reason,
        usage_percent=usage_percent,
        allow_access=True,
        user_segment=user_segment,
        strategy=strategy,
        trigger_variant=trigger_variant,
        pricing_variant=pricing_variant,
        trial_days=trial_days,
        trial_recommended=trial_recommended,
        trial_active=trial_active,
    )


def _lifecycle(stage: str):
    return SimpleNamespace(stage=stage, actions=[], reasons=["test"])


def _engine(*, paywall, onboarding_state, lifecycle_stage, learning_state=None, engagement_state=None, progress_state=None, ltv=240.0):
    uow = FakeUOW(
        learning_state or SimpleNamespace(mastery_percent=48.0, weak_areas=["grammar"]),
        engagement_state or SimpleNamespace(momentum_score=0.5),
        progress_state or SimpleNamespace(xp=180, level=1, milestones=[]),
    )
    engine = MonetizationEngine(
        lambda: uow,
        FakeAdaptivePaywallService(paywall),
        FakeBusinessMetricsService(ltv=ltv),
        FakeOnboardingFlowService(onboarding_state),
        FakeLifecycleService(_lifecycle(lifecycle_stage)),
    )
    return engine, uow


def test_monetization_engine_adjusts_pricing_by_geography_and_engagement():
    engaged_engine, engaged_uow = _engine(
        paywall=_paywall_decision(user_segment="high_intent", pricing_variant="premium_anchor"),
        onboarding_state={"current_step": "completed", "paywall": {}},
        lifecycle_stage="engaged",
        engagement_state=SimpleNamespace(momentum_score=0.8),
        progress_state=SimpleNamespace(xp=650, level=3, milestones=[2, 3]),
        ltv=420.0,
    )
    low_engagement_engine, low_engagement_uow = _engine(
        paywall=_paywall_decision(user_segment="low_engagement", pricing_variant="discount_focus"),
        onboarding_state={"current_step": "completed", "paywall": {}},
        lifecycle_stage="at_risk",
        engagement_state=SimpleNamespace(momentum_score=0.2),
        progress_state=SimpleNamespace(xp=80, level=1, milestones=[]),
        ltv=180.0,
    )

    engaged = run_async(engaged_engine.evaluate(1, geography="us"))
    low_engagement = run_async(low_engagement_engine.evaluate(2, geography="india"))

    assert engaged.offer_type == "annual_anchor"
    assert engaged.pricing.monthly_price == 22.03
    assert engaged.pricing.annual_savings_percent == 20
    assert engaged_uow.decision_traces.created[0]["trace_type"] == "monetization_decision"
    assert engaged_uow.decision_traces.created[0]["reference_id"] == "monetization:1"
    assert engaged_uow.monetization_states.updated[0]["current_offer_type"] == "annual_anchor"
    assert engaged_uow.monetization_offer_events.recorded[0]["event_type"] == "decision_evaluated"
    assert low_engagement.offer_type == "discount"
    assert low_engagement.pricing.monthly_price == 6.88
    assert low_engagement.pricing.discounted_monthly_price == 5.5
    assert low_engagement.pricing.annual_savings_percent == 25
    assert low_engagement_uow.decision_traces.created[0]["inputs"]["geography"] == "india"


def test_monetization_engine_defers_paywall_during_early_onboarding_even_when_triggered():
    engine, uow = _engine(
        paywall=_paywall_decision(show_paywall=True, trial_recommended=True),
        onboarding_state={
            "current_step": "instant_wow_moment",
            "wow": {"understood_percent": 82.0},
            "paywall": {"trial_recommended": True},
        },
        lifecycle_stage="new_user",
        learning_state=SimpleNamespace(mastery_percent=82.0, weak_areas=["travel"]),
    )

    decision = run_async(engine.evaluate(3, geography="us", wow_score=0.84))

    assert decision.show_paywall is False
    assert decision.offer_type == "trial"
    assert decision.paywall_type is None
    assert decision.trigger.timing_policy == "deferred_for_activation"
    assert decision.value_display.locked_progress_percent == 82
    assert uow.decision_traces.created[0]["outputs"]["show_paywall"] is False
    assert uow.decision_traces.created[0]["reason"] == "adaptive session trigger reached"


def test_monetization_engine_surfaces_soft_paywall_once_onboarding_reaches_paywall_step():
    engine, uow = _engine(
        paywall=_paywall_decision(show_paywall=True, trial_recommended=True, usage_percent=64),
        onboarding_state={
            "current_step": "soft_paywall",
            "paywall": {"trial_recommended": True},
            "progress_illusion": {"xp_gain": 52},
        },
        lifecycle_stage="activating",
    )

    decision = run_async(engine.evaluate(4, geography="latam"))

    assert decision.show_paywall is True
    assert decision.paywall_type == "soft_paywall"
    assert decision.offer_type == "trial"
    assert decision.trigger.trigger_variant == "early"
    assert decision.strategy == "high_intent:early:value_anchor:trial:latam"
    assert "Keep your onboarding streak" in decision.value_display.locked_features[-1]
    assert uow.decision_traces.created[0]["outputs"]["trigger"]["onboarding_step"] == "soft_paywall"
    assert uow.decision_traces.created[0]["inputs"]["onboarding_state"]["current_step"] == "soft_paywall"
