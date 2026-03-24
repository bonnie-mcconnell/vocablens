from __future__ import annotations

from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.services.experiment_service import ExperimentContext, ExperimentDefinition, ExperimentService, ExperimentVariant


class FakeAssignments:
    def __init__(self):
        self.rows = {}

    async def get(self, user_id: int, experiment_key: str):
        return self.rows.get((user_id, experiment_key))

    async def create(self, *, user_id: int, experiment_key: str, variant: str, assigned_at=None):
        row = SimpleNamespace(
            user_id=user_id,
            experiment_key=experiment_key,
            variant=variant,
            assigned_at=assigned_at,
        )
        self.rows[(user_id, experiment_key)] = row
        return row


class FakeExposures:
    def __init__(self):
        self.rows = {}

    async def get(self, user_id: int, experiment_key: str):
        return self.rows.get((user_id, experiment_key))

    async def create(self, *, user_id: int, experiment_key: str, variant: str, exposed_at=None):
        row = SimpleNamespace(
            user_id=user_id,
            experiment_key=experiment_key,
            variant=variant,
            exposed_at=exposed_at,
        )
        self.rows[(user_id, experiment_key)] = row
        return row


class FakeSubscriptions:
    def __init__(self, tier: str = "free"):
        self.tier = tier

    async def get_by_user(self, user_id: int):
        return SimpleNamespace(tier=self.tier)


class FakeLifecycleStates:
    def __init__(self, stage: str = "activating"):
        self.stage = stage

    async def get(self, user_id: int):
        return SimpleNamespace(current_stage=self.stage)


class FakeRegistries:
    async def get(self, experiment_key: str):
        return None


class FakeUOW:
    def __init__(self, *, tier: str = "free", stage: str = "activating"):
        self.experiment_assignments = FakeAssignments()
        self.experiment_exposures = FakeExposures()
        self.subscriptions = FakeSubscriptions(tier)
        self.lifecycle_states = FakeLifecycleStates(stage)
        self.experiment_registries = FakeRegistries()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


def _definition(
    *,
    key: str = "paywall_offer",
    rollout_percentage: int = 100,
    holdout_percentage: int = 0,
    baseline_variant: str = "control",
    eligibility: dict[str, tuple[str, ...]] | None = None,
    mutually_exclusive_with: tuple[str, ...] = (),
    prerequisite_experiments: tuple[str, ...] = (),
) -> ExperimentDefinition:
    return ExperimentDefinition(
        key=key,
        status="active",
        rollout_percentage=rollout_percentage,
        holdout_percentage=holdout_percentage,
        is_killed=False,
        baseline_variant=baseline_variant,
        eligibility=eligibility or {},
        mutually_exclusive_with=mutually_exclusive_with,
        prerequisite_experiments=prerequisite_experiments,
        variants=(
            ExperimentVariant(name="control", weight=50),
            ExperimentVariant(name="annual_anchor", weight=50),
        ),
    )


def test_experiment_service_persists_holdout_assignment_to_baseline():
    uow = FakeUOW()
    definition = _definition(holdout_percentage=99)
    service = ExperimentService(
        lambda: uow,
        experiments={
            "paywall_offer": definition,
        },
    )

    user_id = next(
        candidate
        for candidate in range(1, 500)
        if service._is_in_holdout(candidate, definition)
    )
    variant = run_async(service.assign(user_id, "paywall_offer"))

    assert variant == "control"
    assert uow.experiment_assignments.rows[(user_id, "paywall_offer")].variant == "control"


def test_experiment_service_returns_baseline_without_persisting_when_context_is_ineligible():
    uow = FakeUOW(tier="free", stage="activating")
    service = ExperimentService(
        lambda: uow,
        experiments={
            "paywall_offer": _definition(
                eligibility={"subscription_tiers": ("pro",), "lifecycle_stages": ("engaged",)},
            ),
        },
    )

    variant = run_async(service.assign(9, "paywall_offer"))

    assert variant == "control"
    assert uow.experiment_assignments.rows == {}
    assert uow.experiment_exposures.rows == {}


def test_experiment_service_honors_mutual_exclusion_and_prerequisites():
    uow = FakeUOW()
    run_async(
        uow.experiment_assignments.create(
            user_id=5,
            experiment_key="pricing_test",
            variant="control",
        )
    )
    service = ExperimentService(
        lambda: uow,
        experiments={
            "paywall_offer": _definition(
                mutually_exclusive_with=("pricing_test",),
                prerequisite_experiments=("onboarding_trial_gate",),
            ),
        },
    )

    variant = run_async(
        service.assign(
            5,
            "paywall_offer",
            context=ExperimentContext(geography="us", platform="ios", surface="paywall"),
        )
    )

    assert variant == "control"
    assert (5, "paywall_offer") not in uow.experiment_assignments.rows
