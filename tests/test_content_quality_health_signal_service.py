from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.services import content_quality_health_signal_service as content_quality_module
from vocablens.services.content_quality_health_signal_service import ContentQualityHealthSignalService


class FakeContentQualityHealthStatesRepo:
    def __init__(self):
        self.rows = {}

    async def get(self, scope_key: str):
        return self.rows.get(scope_key)

    async def list_all(self):
        return list(self.rows.values())

    async def upsert(self, *, scope_key: str, current_status: str, latest_alert_codes: list[str], metrics: dict):
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


class FakeContentQualityChecksRepo:
    def __init__(self, rows):
        self.rows = list(rows)

    async def list_since(self, since, limit: int = 5000):
        return list(self.rows)[:limit]


class FakeUOW:
    def __init__(self, checks):
        self.content_quality_checks = FakeContentQualityChecksRepo(checks)
        self.content_quality_health_states = FakeContentQualityHealthStatesRepo()
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


def test_content_quality_health_signal_service_persists_critical_state(monkeypatch):
    status_metric = FakeMetric()
    rate_metric = FakeMetric()
    transition_metric = FakeMetric()
    alert_metric = FakeMetric()
    scope_count_metric = FakeMetric()
    active_alert_metric = FakeMetric()
    logger = FakeLogger()
    alert_sink = FakeAlertSink()

    monkeypatch.setattr(content_quality_module, "CONTENT_QUALITY_HEALTH_STATUS", status_metric)
    monkeypatch.setattr(content_quality_module, "CONTENT_QUALITY_HEALTH_RATE", rate_metric)
    monkeypatch.setattr(content_quality_module, "CONTENT_QUALITY_HEALTH_TRANSITIONS", transition_metric)
    monkeypatch.setattr(content_quality_module, "CONTENT_QUALITY_HEALTH_ALERTS", alert_metric)
    monkeypatch.setattr(content_quality_module, "CONTENT_QUALITY_HEALTH_SCOPES", scope_count_metric)
    monkeypatch.setattr(content_quality_module, "CONTENT_QUALITY_ACTIVE_ALERTS", active_alert_metric)
    monkeypatch.setattr(content_quality_module, "logger", logger)

    checks = [
        SimpleNamespace(status="rejected", score=0.2, violations=[{"code": "target_contract_invalid"}]),
        SimpleNamespace(status="rejected", score=0.4, violations=[{"code": "answer_contract_invalid"}]),
    ] + [
        SimpleNamespace(status="passed", score=0.95, violations=[{"code": "ambiguous_prompt"}])
        for _ in range(10)
    ]
    uow = FakeUOW(checks)
    service = ContentQualityHealthSignalService(lambda: uow, alert_sink=alert_sink)

    report = run_async(service.evaluate_scope("global"))

    assert report["health"]["status"] == "critical"
    state = uow.content_quality_health_states.rows["global"]
    assert state.current_status == "critical"
    assert "target_contract_failures_detected" in state.latest_alert_codes
    assert state.metrics["rejected_checks_7d"] == 2
    assert uow.commit_count == 3
    assert alert_metric.records[0]["labels"]["code"] in {
        "content_rejection_rate_high",
        "target_contract_failures_detected",
    }
    assert logger.records[0]["message"] == "content_quality_health_alert"
    assert alert_sink.records[0]["alert_type"] == "content_quality_health_alert"


def test_content_quality_health_signal_service_dashboard_orders_attention():
    uow = FakeUOW([])
    uow.content_quality_health_states.rows = {
        "global": SimpleNamespace(
            scope_key="global",
            current_status="warning",
            latest_alert_codes=["ambiguous_prompts_detected"],
            metrics={"checks_7d": 32},
            last_evaluated_at=SimpleNamespace(isoformat=lambda: "2026-03-25T20:10:00"),
        ),
        "shadow": SimpleNamespace(
            scope_key="shadow",
            current_status="healthy",
            latest_alert_codes=[],
            metrics={"checks_7d": 4},
            last_evaluated_at=SimpleNamespace(isoformat=lambda: "2026-03-25T20:09:00"),
        ),
    }
    service = ContentQualityHealthSignalService(lambda: uow)

    report = run_async(service.get_health_dashboard(limit=10))

    assert report["summary"]["counts_by_health_status"]["warning"] == 1
    assert report["summary"]["alert_counts_by_code"]["ambiguous_prompts_detected"] == 1
    assert report["attention"][0]["scope_key"] == "global"
