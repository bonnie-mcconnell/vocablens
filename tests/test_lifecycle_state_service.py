from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.services.lifecycle_state_service import LifecycleStateService


class FakeLifecycleStates:
    def __init__(self):
        self.row = None

    async def get(self, user_id: int):
        if self.row is None or self.row.user_id != user_id:
            return None
        return self.row

    async def create(self, **kwargs):
        self.row = SimpleNamespace(id=1, **kwargs)
        return self.row

    async def update(self, user_id: int, **kwargs):
        for key, value in kwargs.items():
            if value is not None:
                setattr(self.row, key, value)
        return self.row


class FakeLifecycleTransitions:
    def __init__(self):
        self.rows = []

    async def create(self, **kwargs):
        row = SimpleNamespace(id=len(self.rows) + 1, **kwargs)
        self.rows.append(row)
        return row


class FakeUOW:
    def __init__(self, states, transitions):
        self.lifecycle_states = states
        self.lifecycle_transitions = transitions

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


def test_lifecycle_state_service_creates_initial_state_and_transition():
    states = FakeLifecycleStates()
    transitions = FakeLifecycleTransitions()
    service = LifecycleStateService(lambda: FakeUOW(states, transitions))

    result = run_async(
        service.record_stage(
            user_id=9,
            stage="new_user",
            reasons=["user has one or fewer sessions"],
            source="lifecycle_service.evaluate",
            reference_id="lifecycle:9",
            payload={"total_sessions": 1},
        )
    )

    assert result.changed is True
    assert result.state.current_stage == "new_user"
    assert result.state.transition_count == 1
    assert transitions.rows[0].from_stage is None
    assert transitions.rows[0].to_stage == "new_user"


def test_lifecycle_state_service_only_logs_transition_when_stage_changes():
    states = FakeLifecycleStates()
    transitions = FakeLifecycleTransitions()
    service = LifecycleStateService(lambda: FakeUOW(states, transitions))

    first = run_async(
        service.record_stage(
            user_id=4,
            stage="activating",
            reasons=["user is building toward activation"],
            source="lifecycle_service.evaluate",
            reference_id="lifecycle:4",
        )
    )
    second = run_async(
        service.record_stage(
            user_id=4,
            stage="activating",
            reasons=["engagement is improving, but not yet stable enough for the engaged stage"],
            source="lifecycle_service.evaluate",
            reference_id="lifecycle:4",
        )
    )
    third = run_async(
        service.record_stage(
            user_id=4,
            stage="engaged",
            reasons=["user shows strong engagement and progress"],
            source="lifecycle_service.evaluate",
            reference_id="lifecycle:4",
        )
    )

    assert first.changed is True
    assert second.changed is False
    assert third.changed is True
    assert len(transitions.rows) == 2
    assert states.row.previous_stage == "activating"
    assert states.row.current_stage == "engaged"
    assert states.row.transition_count == 2
