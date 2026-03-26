from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.services.operator_remediation_service import OperatorRemediationService


class FakeScalarResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def first(self):
        return self._rows[0] if self._rows else None


class FakeExecuteResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return FakeScalarResult(self._rows)


class FakeSession:
    def __init__(self, responses):
        self._responses = [list(item) for item in responses]
        self._index = 0

    async def execute(self, query):
        rows = self._responses[self._index]
        self._index += 1
        return FakeExecuteResult(rows)


class FakeLifecycleStatesRepo:
    def __init__(self, state):
        self._state = state

    async def get(self, user_id: int):
        return self._state


class FakeMonetizationStatesRepo:
    def __init__(self, state):
        self._state = state

    async def get_or_create(self, user_id: int):
        return self._state


class FakeUOW:
    def __init__(self, *, session_responses=None, lifecycle_state=None, monetization_state=None):
        self.session = FakeSession(session_responses or [])
        self.lifecycle_states = FakeLifecycleStatesRepo(lifecycle_state)
        self.monetization_states = FakeMonetizationStatesRepo(monetization_state or SimpleNamespace(current_geography=None))
        self.commit_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        self.commit_count += 1


class FakeSessionHealthService:
    def __init__(self):
        self.calls = []

    async def evaluate_scope(self, scope_key: str):
        self.calls.append(scope_key)


class FakeLifecycleService:
    def __init__(self):
        self.calls = []

    async def evaluate(self, user_id: int):
        self.calls.append(user_id)


class FakeLifecycleStateService:
    def __init__(self):
        self.calls = []

    async def repair_current_stage_transition(self, *, user_id: int, source: str, reference_id: str | None):
        self.calls.append({"user_id": user_id, "source": source, "reference_id": reference_id})


class FakeLifecycleHealthService:
    def __init__(self):
        self.calls = []

    async def evaluate_scope(self, scope_key: str):
        self.calls.append(scope_key)


class FakeNotificationStateService:
    def __init__(self):
        self.calls = []

    async def apply_lifecycle_policy(self, *, user_id: int, lifecycle_stage: str, source: str, reference_id: str | None):
        self.calls.append(
            {
                "user_id": user_id,
                "lifecycle_stage": lifecycle_stage,
                "source": source,
                "reference_id": reference_id,
            }
        )


class FakeMonetizationStateService:
    def __init__(self):
        self.calls = []

    async def sync_lifecycle_stage(self, *, user_id: int, lifecycle_stage: str):
        self.calls.append({"user_id": user_id, "lifecycle_stage": lifecycle_stage})


class FakeMonetizationHealthService:
    def __init__(self):
        self.calls = []

    async def evaluate_scope(self, scope_key: str):
        self.calls.append(scope_key)


class FakeDailyLoopHealthService:
    def __init__(self):
        self.calls = []

    async def evaluate_scope(self, scope_key: str):
        self.calls.append(scope_key)


def _build_service(*, uow):
    return OperatorRemediationService(
        lambda: uow,
        session_health_signal_service=FakeSessionHealthService(),
        lifecycle_service=FakeLifecycleService(),
        lifecycle_state_service=FakeLifecycleStateService(),
        lifecycle_health_signal_service=FakeLifecycleHealthService(),
        notification_state_service=FakeNotificationStateService(),
        monetization_state_service=FakeMonetizationStateService(),
        monetization_health_signal_service=FakeMonetizationHealthService(),
        daily_loop_health_signal_service=FakeDailyLoopHealthService(),
    )


def test_operator_remediation_service_repairs_session_attempt_reference():
    session = SimpleNamespace(session_id="sess_1", user_id=9)
    attempt = SimpleNamespace(id=41, session_id="sess_1", submission_id="sub_1", user_id=3)
    uow = FakeUOW(session_responses=[[session], [attempt]])
    service = _build_service(uow=uow)

    result = run_async(
        service.remediate_session_alert(
            alert_code="session_reference_drift_detected",
            artifact_type="session_attempt",
            session_id="sess_1",
            submission_id="sub_1",
            trace_id=None,
        )
    )

    assert result["status"] == "repaired"
    assert result["repaired"] is True
    assert attempt.user_id == 9
    assert result["target"]["submission_id"] == "sub_1"


def test_operator_remediation_service_syncs_notification_state_from_lifecycle():
    lifecycle_state = SimpleNamespace(current_stage="at_risk")
    uow = FakeUOW(lifecycle_state=lifecycle_state)
    service = _build_service(uow=uow)

    result = run_async(
        service.remediate_lifecycle_alert(
            alert_code="lifecycle_state_drift_detected",
            artifact_type="notification_state",
            user_id=17,
        )
    )

    assert result["status"] == "repaired"
    assert result["details"]["current_stage"] == "at_risk"
    assert service._notification_states.calls[0]["user_id"] == 17
    assert service._lifecycle.calls == [17]
    assert service._lifecycle_health.calls == ["global", "at_risk"]


def test_operator_remediation_service_repairs_reward_chest_owner():
    chest = SimpleNamespace(id=71, mission_id=11, user_id=22)
    mission = SimpleNamespace(id=11, user_id=5)
    uow = FakeUOW(session_responses=[[chest], [mission]])
    service = _build_service(uow=uow)

    result = run_async(
        service.remediate_daily_loop_alert(
            alert_code="reward_mission_reference_mismatch_detected",
            reward_chest_id=71,
            mission_id=None,
        )
    )

    assert result["status"] == "repaired"
    assert result["repaired"] is True
    assert chest.user_id == 5
    assert service._daily_loop_health.calls == ["global"]
