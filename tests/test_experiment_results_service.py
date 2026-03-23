from datetime import timedelta
from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.core.time import utc_now
from vocablens.services.experiment_results_service import ExperimentResultsService


class FakeAssignmentsRepo:
    def __init__(self, assignments):
        self.assignments = assignments

    async def list_all(self, experiment_key: str | None = None):
        if experiment_key is None:
            return self.assignments
        return [row for row in self.assignments if row.experiment_key == experiment_key]


class FakeEventsRepo:
    def __init__(self, events):
        self.events = events

    async def list_since(self, since, event_types=None, limit: int = 50000):
        rows = [event for event in self.events if event.created_at >= since]
        if event_types:
            rows = [event for event in rows if event.event_type in event_types]
        return rows[:limit]


class FakeUOW:
    def __init__(self, assignments, events):
        self.experiment_assignments = FakeAssignmentsRepo(assignments)
        self.events = FakeEventsRepo(events)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


def test_experiment_results_service_groups_by_variant_correctly():
    now = utc_now()
    assignments = [
        SimpleNamespace(user_id=1, experiment_key="paywall_offer", variant="control", assigned_at=now - timedelta(days=5)),
        SimpleNamespace(user_id=2, experiment_key="paywall_offer", variant="variant_a", assigned_at=now - timedelta(days=5)),
        SimpleNamespace(user_id=3, experiment_key="learning_strategy", variant="control", assigned_at=now - timedelta(days=5)),
    ]
    service = ExperimentResultsService(lambda: FakeUOW(assignments, []))

    report = run_async(service.results())

    assert len(report.experiments) == 2
    paywall = next(row for row in report.experiments if row.experiment_key == "paywall_offer")
    assert {variant.variant for variant in paywall.variants} == {"control", "variant_a"}


def test_experiment_results_service_aggregates_metrics_and_comparisons():
    now = utc_now()
    assignments = [
        SimpleNamespace(user_id=1, experiment_key="paywall_offer", variant="control", assigned_at=now - timedelta(days=10)),
        SimpleNamespace(user_id=2, experiment_key="paywall_offer", variant="control", assigned_at=now - timedelta(days=10)),
        SimpleNamespace(user_id=3, experiment_key="paywall_offer", variant="variant_a", assigned_at=now - timedelta(days=10)),
        SimpleNamespace(user_id=4, experiment_key="paywall_offer", variant="variant_a", assigned_at=now - timedelta(days=10)),
    ]
    events = [
        SimpleNamespace(user_id=1, event_type="session_started", created_at=now - timedelta(days=8)),
        SimpleNamespace(user_id=1, event_type="message_sent", created_at=now - timedelta(days=8)),
        SimpleNamespace(user_id=2, event_type="message_sent", created_at=now - timedelta(days=8)),
        SimpleNamespace(user_id=3, event_type="session_started", created_at=now - timedelta(days=8)),
        SimpleNamespace(user_id=3, event_type="upgrade_completed", created_at=now - timedelta(days=7)),
        SimpleNamespace(user_id=3, event_type="lesson_completed", created_at=now - timedelta(days=7)),
        SimpleNamespace(user_id=4, event_type="session_started", created_at=now - timedelta(days=8)),
        SimpleNamespace(user_id=4, event_type="message_sent", created_at=now - timedelta(days=8)),
        SimpleNamespace(user_id=4, event_type="review_completed", created_at=now - timedelta(days=7)),
    ]
    service = ExperimentResultsService(lambda: FakeUOW(assignments, events))

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
