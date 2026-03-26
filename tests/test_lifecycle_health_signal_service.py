from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.services import lifecycle_health_signal_service as lifecycle_health_module
from vocablens.services.lifecycle_health_signal_service import LifecycleHealthSignalService


class FakeLifecycleHealthStatesRepo:
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


class FakeLifecycleStatesRepo:
    def __init__(self, rows):
        self.rows = list(rows)

    async def list_all(self):
        return list(self.rows)


class FakeLifecycleTransitionsRepo:
    def __init__(self, rows):
        self.rows = list(rows)

    async def list_all(self, limit: int | None = None):
        if limit is None:
            return list(self.rows)
        return list(self.rows)[:limit]


class FakeScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class FakeSessionResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return FakeScalarResult(self._rows)


class FakeSession:
    def __init__(self, notification_states):
        self.notification_states = list(notification_states)

    async def execute(self, query):
        return FakeSessionResult(self.notification_states)


class FakeUOW:
    def __init__(self, *, lifecycle_states, lifecycle_transitions, notification_states):
        self.lifecycle_states = FakeLifecycleStatesRepo(lifecycle_states)
        self.lifecycle_transitions = FakeLifecycleTransitionsRepo(lifecycle_transitions)
        self.lifecycle_health_states = FakeLifecycleHealthStatesRepo()
        self.session = FakeSession(notification_states)
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


def test_lifecycle_health_signal_service_persists_global_critical_state(monkeypatch):
    status_metric = FakeMetric()
    rate_metric = FakeMetric()
    transition_metric = FakeMetric()
    alert_metric = FakeMetric()
    scope_count_metric = FakeMetric()
    active_alert_metric = FakeMetric()
    logger = FakeLogger()
    alert_sink = FakeAlertSink()

    monkeypatch.setattr(lifecycle_health_module, "LIFECYCLE_HEALTH_STATUS", status_metric)
    monkeypatch.setattr(lifecycle_health_module, "LIFECYCLE_HEALTH_RATE", rate_metric)
    monkeypatch.setattr(lifecycle_health_module, "LIFECYCLE_HEALTH_TRANSITIONS", transition_metric)
    monkeypatch.setattr(lifecycle_health_module, "LIFECYCLE_HEALTH_ALERTS", alert_metric)
    monkeypatch.setattr(lifecycle_health_module, "LIFECYCLE_HEALTH_SCOPES", scope_count_metric)
    monkeypatch.setattr(lifecycle_health_module, "LIFECYCLE_ACTIVE_ALERTS", active_alert_metric)
    monkeypatch.setattr(lifecycle_health_module, "logger", logger)

    uow = FakeUOW(
        lifecycle_states=[
            SimpleNamespace(user_id=1, current_stage="at_risk"),
            SimpleNamespace(user_id=2, current_stage="at_risk"),
            SimpleNamespace(user_id=3, current_stage="churned"),
            SimpleNamespace(user_id=4, current_stage="engaged"),
        ],
        lifecycle_transitions=[],
        notification_states=[
            SimpleNamespace(
                lifecycle_stage="at_risk",
                lifecycle_policy={"lifecycle_notifications_enabled": False},
                suppressed_until=None,
            )
        ],
    )
    service = LifecycleHealthSignalService(lambda: uow, alert_sink=alert_sink)

    report = run_async(service.evaluate_scope("global"))

    assert report["health"]["status"] == "critical"
    state = uow.lifecycle_health_states.rows["global"]
    assert state.current_status == "critical"
    assert "recovery_messaging_blocked" in state.latest_alert_codes
    assert state.metrics["at_risk_share_percent"] == 50.0
    assert uow.commit_count == 3
    assert status_metric.records[:3] == [
        {"op": "set", "labels": {"scope_key": "global", "status": "healthy"}, "value": 0},
        {"op": "set", "labels": {"scope_key": "global", "status": "warning"}, "value": 0},
        {"op": "set", "labels": {"scope_key": "global", "status": "critical"}, "value": 1},
    ]
    assert alert_metric.records[0]["labels"]["code"] == "recovery_messaging_blocked"
    assert active_alert_metric.records[-1]["labels"]["severity"] == "critical"
    assert logger.records[0]["message"] == "lifecycle_health_alert"
    assert alert_sink.records[0]["alert_type"] == "lifecycle_health_alert"


def test_lifecycle_health_signal_service_dashboard_orders_attention():
    uow = FakeUOW(lifecycle_states=[], lifecycle_transitions=[], notification_states=[])
    uow.lifecycle_health_states.rows = {
        "global": SimpleNamespace(
            scope_key="global",
            current_status="critical",
            latest_alert_codes=["recovery_messaging_blocked"],
            metrics={"scope_user_count": 42},
            last_evaluated_at=SimpleNamespace(isoformat=lambda: "2026-03-25T08:10:00"),
        ),
        "engaged": SimpleNamespace(
            scope_key="engaged",
            current_status="healthy",
            latest_alert_codes=[],
            metrics={"scope_user_count": 20},
            last_evaluated_at=SimpleNamespace(isoformat=lambda: "2026-03-25T08:08:00"),
        ),
    }
    service = LifecycleHealthSignalService(lambda: uow)

    report = run_async(service.get_health_dashboard(limit=10))

    assert report["summary"]["counts_by_health_status"]["critical"] == 1
    assert report["summary"]["alert_counts_by_code"]["recovery_messaging_blocked"] == 1
    assert report["attention"][0]["scope_key"] == "global"
    assert report["attention"][0]["alert_drilldowns"] == {}


def test_lifecycle_health_signal_service_detects_cross_domain_stage_drift(monkeypatch):
    status_metric = FakeMetric()
    rate_metric = FakeMetric()
    transition_metric = FakeMetric()
    alert_metric = FakeMetric()
    scope_count_metric = FakeMetric()
    active_alert_metric = FakeMetric()
    logger = FakeLogger()
    alert_sink = FakeAlertSink()

    monkeypatch.setattr(lifecycle_health_module, "LIFECYCLE_HEALTH_STATUS", status_metric)
    monkeypatch.setattr(lifecycle_health_module, "LIFECYCLE_HEALTH_RATE", rate_metric)
    monkeypatch.setattr(lifecycle_health_module, "LIFECYCLE_HEALTH_TRANSITIONS", transition_metric)
    monkeypatch.setattr(lifecycle_health_module, "LIFECYCLE_HEALTH_ALERTS", alert_metric)
    monkeypatch.setattr(lifecycle_health_module, "LIFECYCLE_HEALTH_SCOPES", scope_count_metric)
    monkeypatch.setattr(lifecycle_health_module, "LIFECYCLE_ACTIVE_ALERTS", active_alert_metric)
    monkeypatch.setattr(lifecycle_health_module, "logger", logger)

    now = lifecycle_health_module.utc_now()
    uow = FakeUOW(
        lifecycle_states=[SimpleNamespace(user_id=7, current_stage="at_risk")],
        lifecycle_transitions=[SimpleNamespace(user_id=7, to_stage="engaged", created_at=now)],
        notification_states=[
            SimpleNamespace(
                user_id=7,
                lifecycle_stage="engaged",
                lifecycle_policy={"lifecycle_notifications_enabled": True},
                suppressed_until=None,
            )
        ],
    )
    service = LifecycleHealthSignalService(lambda: uow, alert_sink=alert_sink)

    report = run_async(service.evaluate_scope("global"))
    dashboard = run_async(service.get_health_dashboard(limit=10))

    assert report["health"]["status"] == "critical"
    assert report["health"]["metrics"]["notification_stage_mismatches"] == 1
    assert report["health"]["metrics"]["transition_stage_mismatches"] == 1
    assert "lifecycle_state_drift_detected" in uow.lifecycle_health_states.rows["global"].latest_alert_codes
    drilldown = dashboard["attention"][0]["alert_drilldowns"]["lifecycle_state_drift_detected"]
    assert drilldown[0]["artifact_type"] == "notification_state"
    assert drilldown[0]["remediation_endpoint"] == "/admin/lifecycle/health/remediate"
