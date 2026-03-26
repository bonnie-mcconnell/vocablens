from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.services import session_health_signal_service as session_health_module
from vocablens.services.session_health_signal_service import SessionHealthSignalService


class FakeSessionHealthStatesRepo:
    def __init__(self):
        self.rows = {}

    async def get(self, scope_key: str):
        return self.rows.get(scope_key)

    async def list_all(self):
        return list(self.rows.values())

    async def upsert(
        self,
        *,
        scope_key: str,
        current_status: str,
        latest_alert_codes: list[str],
        metrics: dict,
    ):
        row = self.rows.get(scope_key)
        if row is None:
            row = SimpleNamespace(
                scope_key=scope_key,
                current_status=current_status,
                latest_alert_codes=list(latest_alert_codes),
                metrics=dict(metrics),
            )
            self.rows[scope_key] = row
            return row
        row.current_status = current_status
        row.latest_alert_codes = list(latest_alert_codes)
        row.metrics = dict(metrics)
        return row


class FakeScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class FakeExecuteResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return FakeScalarResult(self._rows)


class FakeSession:
    def __init__(self, sessions, attempts, traces, events):
        self._responses = [list(sessions), list(attempts), list(traces), list(events)]
        self._index = 0

    async def execute(self, query):
        if self._index >= len(self._responses):
            self._index = 0
        rows = self._responses[self._index]
        self._index += 1
        return FakeExecuteResult(rows)


class FakeUOW:
    def __init__(self, *, sessions, attempts, traces, events):
        self.session_health_states = FakeSessionHealthStatesRepo()
        self.session = FakeSession(sessions, attempts, traces, events)
        self.commit_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        self.commit_count += 1


class FakeMetricHandle:
    def __init__(self, records, labels):
        self._records = records
        self._labels = labels

    def set(self, value: float):
        self._records.append({"op": "set", "labels": dict(self._labels), "value": value})

    def inc(self, value: float = 1.0):
        self._records.append({"op": "inc", "labels": dict(self._labels), "value": value})


class FakeMetric:
    def __init__(self):
        self.records = []

    def labels(self, **labels):
        return FakeMetricHandle(self.records, labels)


class FakeLogger:
    def __init__(self):
        self.records = []

    def warning(self, message: str, *, extra: dict):
        self.records.append({"message": message, "extra": dict(extra)})


class FakeAlertSink:
    def __init__(self):
        self.records = []

    async def emit(self, alert_type: str, payload: dict):
        self.records.append({"alert_type": alert_type, "payload": dict(payload)})


def test_session_health_signal_service_persists_critical_state(monkeypatch):
    status_metric = FakeMetric()
    rate_metric = FakeMetric()
    transition_metric = FakeMetric()
    alert_metric = FakeMetric()
    scope_count_metric = FakeMetric()
    active_alert_metric = FakeMetric()
    logger = FakeLogger()
    alert_sink = FakeAlertSink()

    monkeypatch.setattr(session_health_module, "SESSION_HEALTH_STATUS", status_metric)
    monkeypatch.setattr(session_health_module, "SESSION_HEALTH_RATE", rate_metric)
    monkeypatch.setattr(session_health_module, "SESSION_HEALTH_TRANSITIONS", transition_metric)
    monkeypatch.setattr(session_health_module, "SESSION_HEALTH_ALERTS", alert_metric)
    monkeypatch.setattr(session_health_module, "SESSION_HEALTH_SCOPES", scope_count_metric)
    monkeypatch.setattr(session_health_module, "SESSION_ACTIVE_ALERTS", active_alert_metric)
    monkeypatch.setattr(session_health_module, "logger", logger)

    sessions = [
        SimpleNamespace(session_id="sess_completed", user_id=1, status="completed", created_at=SimpleNamespace()),
        SimpleNamespace(session_id="sess_expired", user_id=2, status="expired", created_at=SimpleNamespace()),
    ] + [
        SimpleNamespace(session_id=f"sess_active_{idx}", user_id=idx + 3, status="active", created_at=SimpleNamespace())
        for idx in range(22)
    ]
    events = [
        SimpleNamespace(event_type="session_generation_rejected", payload={}),
        *[
            SimpleNamespace(event_type="session_submission_rejected", payload={"reason": "stale_contract"})
            for _ in range(5)
        ],
    ]
    uow = FakeUOW(sessions=sessions, attempts=[], traces=[], events=events)
    service = SessionHealthSignalService(lambda: uow, alert_sink=alert_sink)

    report = run_async(service.evaluate_scope("global"))

    assert report["health"]["status"] == "critical"
    state = uow.session_health_states.rows["global"]
    assert state.current_status == "critical"
    assert "session_generation_rejections_detected" in state.latest_alert_codes
    assert state.metrics["stale_contract_rejections_7d"] == 5
    assert uow.commit_count == 3
    assert status_metric.records[:3] == [
        {"op": "set", "labels": {"scope_key": "global", "status": "healthy"}, "value": 0},
        {"op": "set", "labels": {"scope_key": "global", "status": "warning"}, "value": 0},
        {"op": "set", "labels": {"scope_key": "global", "status": "critical"}, "value": 1},
    ]
    assert alert_metric.records[0]["labels"]["code"] == "session_generation_rejections_detected"
    assert active_alert_metric.records[-1]["labels"]["severity"] == "critical"
    assert logger.records[0]["message"] == "session_health_alert"
    assert alert_sink.records[0]["alert_type"] == "session_health_alert"


def test_session_health_signal_service_dashboard_orders_attention():
    uow = FakeUOW(sessions=[], attempts=[], traces=[], events=[])
    uow.session_health_states.rows = {
        "global": SimpleNamespace(
            scope_key="global",
            current_status="critical",
            latest_alert_codes=["session_completion_rate_low"],
            metrics={"sessions_started_7d": 44},
            last_evaluated_at=SimpleNamespace(isoformat=lambda: "2026-03-25T19:10:00"),
        ),
        "canary": SimpleNamespace(
            scope_key="canary",
            current_status="healthy",
            latest_alert_codes=[],
            metrics={"sessions_started_7d": 8},
            last_evaluated_at=SimpleNamespace(isoformat=lambda: "2026-03-25T19:05:00"),
        ),
    }
    service = SessionHealthSignalService(lambda: uow)

    report = run_async(service.get_health_dashboard(limit=10))

    assert report["summary"]["counts_by_health_status"]["critical"] == 1
    assert report["summary"]["alert_counts_by_code"]["session_completion_rate_low"] == 1
    assert report["attention"][0]["scope_key"] == "global"
    assert report["attention"][0]["alert_drilldowns"] == {}


def test_session_health_signal_service_detects_reference_drift(monkeypatch):
    status_metric = FakeMetric()
    rate_metric = FakeMetric()
    transition_metric = FakeMetric()
    alert_metric = FakeMetric()
    scope_count_metric = FakeMetric()
    active_alert_metric = FakeMetric()
    logger = FakeLogger()
    alert_sink = FakeAlertSink()

    monkeypatch.setattr(session_health_module, "SESSION_HEALTH_STATUS", status_metric)
    monkeypatch.setattr(session_health_module, "SESSION_HEALTH_RATE", rate_metric)
    monkeypatch.setattr(session_health_module, "SESSION_HEALTH_TRANSITIONS", transition_metric)
    monkeypatch.setattr(session_health_module, "SESSION_HEALTH_ALERTS", alert_metric)
    monkeypatch.setattr(session_health_module, "SESSION_HEALTH_SCOPES", scope_count_metric)
    monkeypatch.setattr(session_health_module, "SESSION_ACTIVE_ALERTS", active_alert_metric)
    monkeypatch.setattr(session_health_module, "logger", logger)

    sessions = [SimpleNamespace(session_id="sess_1", user_id=1, status="completed", created_at=SimpleNamespace())]
    attempts = [SimpleNamespace(session_id="sess_missing", user_id=1, created_at=SimpleNamespace())]
    traces = [SimpleNamespace(reference_id="sess_missing", user_id=1, created_at=SimpleNamespace())]
    uow = FakeUOW(sessions=sessions, attempts=attempts, traces=traces, events=[])
    service = SessionHealthSignalService(lambda: uow, alert_sink=alert_sink)

    report = run_async(service.evaluate_scope("global"))
    dashboard = run_async(service.get_health_dashboard(limit=10))

    assert report["health"]["status"] == "critical"
    assert report["health"]["metrics"]["attempt_reference_mismatches_7d"] == 1
    assert report["health"]["metrics"]["evaluation_reference_mismatches_7d"] == 1
    assert "session_reference_drift_detected" in uow.session_health_states.rows["global"].latest_alert_codes
    drilldown = dashboard["attention"][0]["alert_drilldowns"]["session_reference_drift_detected"]
    assert drilldown[0]["artifact_type"] == "session_attempt"
