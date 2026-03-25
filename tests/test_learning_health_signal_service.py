from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.services import learning_health_signal_service as learning_health_module
from vocablens.services.learning_health_signal_service import LearningHealthSignalService


class FakeLearningHealthStatesRepo:
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
    def __init__(self, traces, learning_states):
        self._responses = [list(traces), list(learning_states)]
        self._index = 0

    async def execute(self, query):
        rows = self._responses[self._index]
        self._index += 1
        return FakeExecuteResult(rows)


class FakeUOW:
    def __init__(self, *, traces, learning_states):
        self.learning_health_states = FakeLearningHealthStatesRepo()
        self.session = FakeSession(traces, learning_states)
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


def test_learning_health_signal_service_persists_warning_state(monkeypatch):
    status_metric = FakeMetric()
    rate_metric = FakeMetric()
    transition_metric = FakeMetric()
    alert_metric = FakeMetric()
    scope_count_metric = FakeMetric()
    active_alert_metric = FakeMetric()
    logger = FakeLogger()
    alert_sink = FakeAlertSink()

    monkeypatch.setattr(learning_health_module, "LEARNING_HEALTH_STATUS", status_metric)
    monkeypatch.setattr(learning_health_module, "LEARNING_HEALTH_RATE", rate_metric)
    monkeypatch.setattr(learning_health_module, "LEARNING_HEALTH_TRANSITIONS", transition_metric)
    monkeypatch.setattr(learning_health_module, "LEARNING_HEALTH_ALERTS", alert_metric)
    monkeypatch.setattr(learning_health_module, "LEARNING_HEALTH_SCOPES", scope_count_metric)
    monkeypatch.setattr(learning_health_module, "LEARNING_ACTIVE_ALERTS", active_alert_metric)
    monkeypatch.setattr(learning_health_module, "logger", logger)

    recommendation_traces = [
        SimpleNamespace(trace_type="lesson_recommendation", outputs={"action": "learn_new_word", "target": "general"})
        for _ in range(12)
    ] + [
        SimpleNamespace(trace_type="lesson_recommendation", outputs={"action": "learn_new_word", "target": "vocabulary"})
        for _ in range(8)
    ]
    knowledge_update_traces = [
        SimpleNamespace(trace_type="knowledge_update", outputs={"reviewed_count": 1})
        for _ in range(8)
    ]
    learning_states = [
        SimpleNamespace(mastery_percent=20.0, weak_areas=[]),
        SimpleNamespace(mastery_percent=72.0, weak_areas=["grammar"]),
    ]
    uow = FakeUOW(
        traces=[*recommendation_traces, *knowledge_update_traces],
        learning_states=learning_states,
    )
    service = LearningHealthSignalService(lambda: uow, alert_sink=alert_sink)

    report = run_async(service.evaluate_scope("global"))

    assert report["health"]["status"] == "warning"
    state = uow.learning_health_states.rows["global"]
    assert state.current_status == "warning"
    assert "recommendation_target_generic" in state.latest_alert_codes
    assert "weak_area_detection_missing" in state.latest_alert_codes
    assert state.metrics["recommendation_update_coverage_percent"] == 40.0
    assert uow.commit_count == 3
    assert status_metric.records[:3] == [
        {"op": "set", "labels": {"scope_key": "global", "status": "healthy"}, "value": 0},
        {"op": "set", "labels": {"scope_key": "global", "status": "warning"}, "value": 1},
        {"op": "set", "labels": {"scope_key": "global", "status": "critical"}, "value": 0},
    ]
    assert alert_metric.records[0]["labels"]["code"] == "knowledge_update_coverage_low"
    assert {
        (record["labels"]["severity"], record["value"])
        for record in active_alert_metric.records
    } == {("warning", 3.0), ("critical", 0.0)}
    assert logger.records[0]["message"] == "learning_health_alert"
    assert alert_sink.records[0]["alert_type"] == "learning_health_alert"


def test_learning_health_signal_service_dashboard_orders_attention():
    uow = FakeUOW(traces=[], learning_states=[])
    uow.learning_health_states.rows = {
        "global": SimpleNamespace(
            scope_key="global",
            current_status="warning",
            latest_alert_codes=["weak_area_detection_missing"],
            metrics={"recommendations_7d": 22},
            last_evaluated_at=SimpleNamespace(isoformat=lambda: "2026-03-25T19:12:00"),
        ),
        "shadow": SimpleNamespace(
            scope_key="shadow",
            current_status="healthy",
            latest_alert_codes=[],
            metrics={"recommendations_7d": 4},
            last_evaluated_at=SimpleNamespace(isoformat=lambda: "2026-03-25T19:11:00"),
        ),
    }
    service = LearningHealthSignalService(lambda: uow)

    report = run_async(service.get_health_dashboard(limit=10))

    assert report["summary"]["counts_by_health_status"]["warning"] == 1
    assert report["summary"]["alert_counts_by_code"]["weak_area_detection_missing"] == 1
    assert report["attention"][0]["scope_key"] == "global"
