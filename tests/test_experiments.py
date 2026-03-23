from collections import Counter
from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.services.experiment_service import ExperimentService
from vocablens.services.learning_engine import LearningEngine
from vocablens.services.retention_engine import RetentionEngine
from vocablens.services.subscription_service import SubscriptionService


class FakeExperimentAssignmentsRepo:
    def __init__(self):
        self.assignments = {}

    async def get(self, user_id: int, experiment_key: str):
        record = self.assignments.get((user_id, experiment_key))
        if record is None:
            return None
        return SimpleNamespace(**record)

    async def create(self, *, user_id: int, experiment_key: str, variant: str, assigned_at=None):
        self.assignments[(user_id, experiment_key)] = {
            "user_id": user_id,
            "experiment_key": experiment_key,
            "variant": variant,
            "assigned_at": assigned_at,
        }
        return SimpleNamespace(**self.assignments[(user_id, experiment_key)])


class FakeExperimentExposuresRepo:
    def __init__(self):
        self.exposures = {}

    async def get(self, user_id: int, experiment_key: str):
        record = self.exposures.get((user_id, experiment_key))
        if record is None:
            return None
        return SimpleNamespace(**record)

    async def create(self, *, user_id: int, experiment_key: str, variant: str, exposed_at=None):
        self.exposures[(user_id, experiment_key)] = {
            "user_id": user_id,
            "experiment_key": experiment_key,
            "variant": variant,
            "exposed_at": exposed_at,
        }
        return SimpleNamespace(**self.exposures[(user_id, experiment_key)])


class FakeExperimentRegistriesRepo:
    def __init__(self, experiments: dict[str, dict[str, int]]):
        self.registries = {
            key: SimpleNamespace(
                experiment_key=key,
                status="active",
                rollout_percentage=100,
                is_killed=False,
                description=None,
                variants=[{"name": name, "weight": weight} for name, weight in definition.items()],
            )
            for key, definition in experiments.items()
        }

    async def get(self, experiment_key: str):
        return self.registries.get(experiment_key)


class FakeExperimentUOW:
    def __init__(
        self,
        repo: FakeExperimentAssignmentsRepo,
        exposures: FakeExperimentExposuresRepo,
        registries: FakeExperimentRegistriesRepo,
    ):
        self.experiment_assignments = repo
        self.experiment_exposures = exposures
        self.experiment_registries = registries

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


class FakeEventService:
    def __init__(self):
        self.events = []

    async def record(self, *, event_type: str, user_id: int, payload: dict):
        self.events.append(
            {
                "event_type": event_type,
                "user_id": user_id,
                "payload": payload,
            }
        )


def _experiment_service(experiments: dict[str, dict[str, int]]):
    repo = FakeExperimentAssignmentsRepo()
    exposures = FakeExperimentExposuresRepo()
    registries = FakeExperimentRegistriesRepo(experiments)
    events = FakeEventService()
    factory = lambda: FakeExperimentUOW(repo, exposures, registries)
    service = ExperimentService(factory, events)
    return service, repo, exposures, events


def test_experiment_assignment_is_deterministic():
    service, _, exposures, events = _experiment_service({"pricing_test": {"control": 50, "variant_a": 50}})

    first = run_async(service.assign(42, "pricing_test"))
    second = run_async(service.assign(42, "pricing_test"))
    stored = run_async(service.get_variant(42, "pricing_test"))

    assert first == second
    assert stored == first
    assert exposures.exposures[(42, "pricing_test")]["variant"] == first
    assert len(events.events) == 1
    assert events.events[0]["event_type"] == "experiment_exposure"


def test_experiment_assignment_respects_weighted_distribution():
    service, _, _, _ = _experiment_service({"pricing_test": {"control": 80, "variant_a": 20}})

    counts = Counter(run_async(service.assign(user_id, "pricing_test")) for user_id in range(1, 10001))

    control_ratio = counts["control"] / 10000
    variant_ratio = counts["variant_a"] / 10000

    assert 0.77 <= control_ratio <= 0.83
    assert 0.17 <= variant_ratio <= 0.23


def test_experiment_assignment_does_not_reassign_existing_users():
    service, repo, exposures, events = _experiment_service({"pricing_test": {"control": 100}})
    run_async(repo.create(user_id=7, experiment_key="pricing_test", variant="variant_a"))

    variant = run_async(service.assign(7, "pricing_test"))

    assert variant == "variant_a"
    assert exposures.exposures[(7, "pricing_test")]["variant"] == "variant_a"
    assert len(events.events) == 1


def test_experiment_assignment_backfills_missing_exposure_for_existing_assignment():
    service, repo, exposures, events = _experiment_service({"pricing_test": {"control": 100}})
    run_async(repo.create(user_id=9, experiment_key="pricing_test", variant="control"))

    variant = run_async(service.assign(9, "pricing_test"))

    assert variant == "control"
    assert exposures.exposures[(9, "pricing_test")]["variant"] == "control"
    assert len(events.events) == 1


class FakeLearningUOW:
    def __init__(self):
        self.learning_states = SimpleNamespace(get_or_create=self._get_or_create_learning_state)
        self.vocab = SimpleNamespace(
            list_due=self._list_due,
            list_all=self._list_all,
        )
        self.skill_tracking = SimpleNamespace(latest_scores=self._latest_scores)
        self.knowledge_graph = SimpleNamespace(
            list_clusters=self._list_clusters,
            get_weak_clusters=self._get_weak_clusters,
        )
        self.mistake_patterns = SimpleNamespace(
            top_patterns=self._top_patterns,
            repeated_patterns=self._repeated_patterns,
        )
        self.learning_events = SimpleNamespace(list_since=self._list_since)
        self.profiles = SimpleNamespace(get_or_create=self._get_or_create_profile)
        self.decision_traces = SimpleNamespace(create=self._create_trace)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None

    async def _list_due(self, user_id: int):
        return []

    async def _list_all(self, user_id: int, limit: int, offset: int):
        return [object()] * 30

    async def _latest_scores(self, user_id: int):
        return {"grammar": 0.9, "vocabulary": 0.9, "fluency": 0.7}

    async def _list_clusters(self, user_id: int):
        return {}

    async def _get_weak_clusters(self, user_id: int, limit: int = 3):
        return []

    async def _top_patterns(self, user_id: int, limit: int = 3):
        return []

    async def _repeated_patterns(self, user_id: int, threshold: int = 2, limit: int = 3):
        return []

    async def _list_since(self, user_id: int, since):
        return []

    async def _get_or_create_profile(self, user_id: int):
        return SimpleNamespace(
            difficulty_preference="medium",
            retention_rate=0.8,
            content_preference="mixed",
        )

    async def _get_or_create_learning_state(self, user_id: int):
        return SimpleNamespace(skills={}, weak_areas=[])

    async def _create_trace(self, **kwargs):
        return SimpleNamespace(**kwargs)


class FixedExperimentService:
    def __init__(self, assignments: dict[str, str]):
        self.assignments = assignments

    async def has_experiment(self, experiment_key: str) -> bool:
        return experiment_key in self.assignments

    async def assign(self, user_id: int, experiment_key: str) -> str:
        return self.assignments[experiment_key]


def test_learning_engine_applies_learning_experiment_variant():
    engine = LearningEngine(
        lambda: FakeLearningUOW(),
        RetentionEngine(),
        experiment_service=FixedExperimentService({"learning_strategy": "conversation_focus"}),
    )

    recommendation = run_async(engine.recommend(11))

    assert recommendation.action == "conversation_drill"
    assert "experiment variant" in recommendation.reason


class FakeRetentionUOW:
    def __init__(self):
        self.profiles = SimpleNamespace(get_or_create=self._get_or_create)
        self.vocab = SimpleNamespace(list_due=self._list_due, list_all=self._list_all)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None

    async def _get_or_create(self, user_id: int):
        return SimpleNamespace(
            last_active_at=None,
            session_frequency=0.0,
            current_streak=2,
            longest_streak=2,
            retention_rate=0.8,
            drop_off_risk=0.0,
        )

    async def _list_due(self, user_id: int):
        return [SimpleNamespace(source_text="hola", review_count=1, ease_factor=1.9)]

    async def _list_all(self, user_id: int, limit: int, offset: int):
        return [SimpleNamespace(source_text="hola", review_count=1, ease_factor=1.9)]


def test_retention_engine_applies_retention_experiment_variant():
    engine = RetentionEngine(
        lambda: FakeRetentionUOW(),
        experiment_service=FixedExperimentService({"retention_nudges": "quick_session_first"}),
    )

    assessment = run_async(engine.assess_user(5))

    assert assessment.suggested_actions[0].kind == "quick_session"


class FakeSubscriptionRepo:
    async def get_by_user(self, user_id: int):
        return None


class FakeSubscriptionEventsRepo:
    async def record(self, **kwargs):
        return None

    async def counts_by_event(self):
        return {}


class FakeSubscriptionUOW:
    def __init__(self):
        self.subscriptions = FakeSubscriptionRepo()
        self.subscription_events = FakeSubscriptionEventsRepo()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


def test_subscription_service_applies_paywall_experiment_variant():
    service = SubscriptionService(
        lambda: FakeSubscriptionUOW(),
        experiment_service=FixedExperimentService({"paywall_offer": "soft_paywall"}),
    )

    features = run_async(service.get_features(3))

    assert features.paywall_variant == "soft_paywall"
    assert features.request_limit == 120
    assert features.token_limit == 60000
