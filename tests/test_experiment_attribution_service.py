from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.core.time import utc_now
from vocablens.services.experiment_attribution_service import ExperimentAttributionService


class FakeExperimentOutcomeAttributions:
    def __init__(self):
        self.rows = {}

    async def get(self, user_id: int, experiment_key: str):
        return self.rows.get((user_id, experiment_key))

    async def create(
        self,
        *,
        user_id: int,
        experiment_key: str,
        variant: str,
        assignment_reason: str,
        attribution_version: str,
        exposed_at,
        window_end_at,
    ):
        row = SimpleNamespace(
            user_id=user_id,
            experiment_key=experiment_key,
            variant=variant,
            assignment_reason=assignment_reason,
            attribution_version=attribution_version,
            exposed_at=exposed_at,
            window_end_at=window_end_at,
            retained_d1=False,
            retained_d7=False,
            converted=False,
            first_conversion_at=None,
            session_count=0,
            message_count=0,
            learning_action_count=0,
            upgrade_click_count=0,
            last_event_at=None,
        )
        self.rows[(user_id, experiment_key)] = row
        return row

    async def update(self, user_id: int, experiment_key: str, **kwargs):
        row = self.rows[(user_id, experiment_key)]
        for key, value in kwargs.items():
            setattr(row, key, value)
        return row

    async def list_active_by_user(self, user_id: int, occurred_at):
        return [
            row
            for row in self.rows.values()
            if row.user_id == user_id and row.exposed_at <= occurred_at <= row.window_end_at
        ]


class FakeUOW:
    def __init__(self):
        self.experiment_outcome_attributions = FakeExperimentOutcomeAttributions()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


def test_experiment_attribution_service_tracks_session_and_conversion_outcomes():
    uow = FakeUOW()
    service = ExperimentAttributionService(lambda: uow)
    exposed_at = utc_now() - timedelta(days=8)

    run_async(
        service.ensure_exposure(
            user_id=7,
            experiment_key="paywall_offer",
            variant="control",
            exposed_at=exposed_at,
            assignment_reason="rollout",
        )
    )
    run_async(service.record_event(user_id=7, event_type="session_started", occurred_at=exposed_at + timedelta(days=2)))
    run_async(service.record_event(user_id=7, event_type="message_sent", occurred_at=exposed_at + timedelta(days=2)))
    run_async(service.record_event(user_id=7, event_type="lesson_completed", occurred_at=exposed_at + timedelta(days=2)))
    run_async(service.record_event(user_id=7, event_type="upgrade_completed", occurred_at=exposed_at + timedelta(days=3)))

    row = uow.experiment_outcome_attributions.rows[(7, "paywall_offer")]
    assert row.retained_d1 is True
    assert row.retained_d7 is False
    assert row.converted is True
    assert row.session_count == 1
    assert row.message_count == 1
    assert row.learning_action_count == 1
    assert row.first_conversion_at == exposed_at + timedelta(days=3)
