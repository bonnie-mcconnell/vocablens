from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.services.experiment_results_service import ExperimentResultsService


class FakeExperimentOutcomeAttributionsRepo:
    def __init__(self, rows):
        self.rows = rows

    async def list_all(self, experiment_key: str | None = None):
        if experiment_key is None:
            return self.rows
        return [row for row in self.rows if row.experiment_key == experiment_key]


class FakeRegistriesRepo:
    def __init__(self, rows):
        self.rows = rows

    async def list_all(self):
        return self.rows


class FakeUOW:
    def __init__(self, rows, registries):
        self.experiment_outcome_attributions = FakeExperimentOutcomeAttributionsRepo(rows)
        self.experiment_registries = FakeRegistriesRepo(registries)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


def test_experiment_results_service_groups_by_variant_correctly():
    rows = [
        SimpleNamespace(user_id=1, experiment_key="paywall_offer", variant="control", retained_d1=False, converted=False, session_count=0, message_count=0, learning_action_count=0),
        SimpleNamespace(user_id=2, experiment_key="paywall_offer", variant="variant_a", retained_d1=False, converted=False, session_count=0, message_count=0, learning_action_count=0),
        SimpleNamespace(user_id=3, experiment_key="learning_strategy", variant="control", retained_d1=False, converted=False, session_count=0, message_count=0, learning_action_count=0),
    ]
    registries = [
        SimpleNamespace(experiment_key="paywall_offer", baseline_variant="control"),
        SimpleNamespace(experiment_key="learning_strategy", baseline_variant="control"),
    ]
    service = ExperimentResultsService(lambda: FakeUOW(rows, registries))

    report = run_async(service.results())

    assert len(report.experiments) == 2
    paywall = next(row for row in report.experiments if row.experiment_key == "paywall_offer")
    assert {variant.variant for variant in paywall.variants} == {"control", "variant_a"}


def test_experiment_results_service_aggregates_metrics_and_comparisons():
    rows = [
        SimpleNamespace(user_id=1, experiment_key="paywall_offer", variant="control", retained_d1=True, converted=False, session_count=1, message_count=1, learning_action_count=0),
        SimpleNamespace(user_id=2, experiment_key="paywall_offer", variant="control", retained_d1=False, converted=False, session_count=0, message_count=1, learning_action_count=0),
        SimpleNamespace(user_id=3, experiment_key="paywall_offer", variant="variant_a", retained_d1=True, converted=True, session_count=1, message_count=0, learning_action_count=1),
        SimpleNamespace(user_id=4, experiment_key="paywall_offer", variant="variant_a", retained_d1=True, converted=False, session_count=1, message_count=1, learning_action_count=1),
    ]
    registries = [SimpleNamespace(experiment_key="paywall_offer", baseline_variant="control")]
    service = ExperimentResultsService(lambda: FakeUOW(rows, registries))

    report = run_async(service.results("paywall_offer"))

    experiment = report.experiments[0]
    control = next(row for row in experiment.variants if row.variant == "control")
    variant_a = next(row for row in experiment.variants if row.variant == "variant_a")

    assert control.retention_rate == 50.0
    assert control.conversion_rate == 0.0
    assert control.engagement.messages_per_user == 1.0
    assert variant_a.retention_rate == 100.0
    assert variant_a.conversion_rate == 50.0
    assert variant_a.engagement.learning_actions_per_user == 1.0
    assert experiment.comparisons[0].baseline_variant == "control"
    assert experiment.comparisons[0].candidate_variant == "variant_a"
    assert experiment.comparisons[0].retention_lift == 50.0
